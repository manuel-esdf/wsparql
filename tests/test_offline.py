"""Offline checks (no Ollaya): run with `make test`. The profile-specific tests pin their profile; the generic ones
(ETL round trip, expected query values) run on every profile/* directory."""
import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from rdflib import Graph

from wsparql import etl
from wsparql.db import ProfileDb
from wsparql.pipeline import answer, extract_params, extract_period, select
from wsparql.profile import Profile

EU = "profile/eu-expense-poc"
PROFILES = sorted(p.parent for p in Path("profile").glob("*/csv"))
class SelectTest(unittest.TestCase):
    def ask(self, choice, confidence):
        """Stub for ollaya.decide: records the criteria sent, answers with a fixed choice."""
        def _ask(question, questions):
            self.criteria = questions["select"]["criteria"]
            return {"select": {"choice": choice, "confidence": confidence, "probabilities": {}}}
        return _ask

    def test_criteria_are_all_readable_queries_plus_none(self):
        prof = Profile(EU)
        select("q", prof, self.ask("none", 0.9))
        self.assertEqual(list(self.criteria), [*prof.catalog, "none"])
        self.assertEqual(self.criteria["q01-total-expenses-by-project"], prof.readable["q01-total-expenses-by-project"])

    def test_none_or_low_confidence_means_no_query(self):
        prof = Profile(EU)
        qid = "q06-ineligible-expenses"
        self.assertEqual(select("q", prof, self.ask(qid, 0.9))[0], qid)
        self.assertIsNone(select("q", prof, self.ask("none", 0.9))[0])
        self.assertIsNone(select("q", prof, self.ask(qid, 0.3))[0])


class PeriodTest(unittest.TestCase):
    def test_quarter_months_year(self):
        self.assertEqual(extract_period("List LUMEN expenses for Q1 2026"), ("2026-01-01", "2026-03-31"))
        self.assertEqual(extract_period("What did we spend during the second quarter of 2026?"), ("2026-04-01", "2026-06-30"))
        self.assertEqual(extract_period("List LUMEN expenses between January and March 2026."), ("2026-01-01", "2026-03-31"))
        self.assertEqual(extract_period("What are Claire Roux's expenses in March 2026?"), ("2026-03-01", "2026-03-31"))
        self.assertEqual(extract_period("costs lumen 2026"), ("2026-01-01", "2026-12-31"))
        self.assertIsNone(extract_period("Show the expenses of the last six months."))


class FakeProfile:
    """What extract_params reads: the parameter kinds, the ABOX values of a property, what they name, the reporting periods."""
    parameters = {"acronym": "acronym", "from": "date", "to": "date", "kind": ["ERP", "CRP"]}
    periods = {"ERP1": ("2022-06-01", "2023-05-31")}
    values = staticmethod(lambda label: ["GRAPHIA", "LUMEN"])
    noun = staticmethod(lambda label: "European project")


class ParamsTest(unittest.TestCase):
    NAMES = ["acronym", "from", "to"]

    def ask(self, choice, confidence):
        return lambda question, questions: {"acronym": {"choice": choice, "confidence": confidence, "probabilities": {}}}

    def test_found_and_missing(self):
        never = lambda question, questions: self.fail("a value written in the question needs no Ollaya")
        found, how = extract_params("List LUMEN expenses for Q1 2026", self.NAMES, FakeProfile, never)
        self.assertEqual(found, {"acronym": "LUMEN", "from": "2026-01-01", "to": "2026-03-31"})
        self.assertEqual(sorted(how), self.NAMES)  # one explanation per requested parameter
        found, how = extract_params("Spending overview please.", self.NAMES, FakeProfile, self.ask("none", 0.9))
        self.assertEqual((found, sorted(how)), ({}, self.NAMES))
        self.assertEqual(extract_params("Lumen's spending", ["acronym"], FakeProfile, never)[0], {"acronym": "LUMEN"})  # word, any case
        self.assertEqual(extract_params("q", ["acronym"], FakeProfile, self.ask("LUMEN", 0.2))[0], {})
        found, how = extract_params("Who worked in ERP1 on the KoM 2023?", ["kind", "from", "to"], FakeProfile, never)
        self.assertEqual(found, {"from": "2022-06-01", "to": "2023-05-31"})  # the named period's dates, not the year; ERP1 is not the word ERP
        self.assertEqual(extract_params("List the ERP of the project", ["kind"], FakeProfile, never)[0], {"kind": "ERP"})


class BindingsTest(unittest.TestCase):
    def test_q10_runs_with_bound_params(self):
        prof = Profile(EU)
        q = "q10-project-expenses-in-period"
        self.assertEqual((prof.values("acronym"), prof.noun("acronym"), prof.periods), (["GRAPHIA", "LUMEN", "OPENSCIENCE"], "European project", {}))
        self.assertEqual(len(prof.run(q, {"acronym": "LUMEN", "from": "2026-01-01", "to": "2026-03-31"})[1]), 6)  # the old hard-coded query
        self.assertEqual(len(prof.run(q, {"acronym": "GRAPHIA", "from": "2026-01-01", "to": "2026-06-30"})[1]), 3)


class AnswerTest(unittest.TestCase):
    Q10 = "q10-project-expenses-in-period"

    def ask(self, choice, acronym="LUMEN"):
        """Stub for ollaya.decide answering whichever choice question is asked."""
        answers = {"select": choice, "acronym": acronym}
        return lambda question, questions: {k: {"choice": answers[k], "confidence": 0.9, "probabilities": {}} for k in questions}

    def test_select_params_run(self):
        prof = Profile(EU)
        out = answer("List LUMEN expenses for Q1 2026", prof, self.ask(self.Q10))
        self.assertEqual((out["selected"], out["params"], out["missing"]), (self.Q10, {"acronym": "LUMEN", "from": "2026-01-01", "to": "2026-03-31"}, []))
        self.assertEqual(len(out["result"][1]), 6)
        out = answer("List LUMEN expenses", prof, self.ask(self.Q10))
        self.assertEqual((out["missing"], out["result"]), (["from", "to"], None))
        out = answer("What is the weather in Brussels?", prof, self.ask("none"))
        self.assertEqual((out["selected"], out["params"], out["result"]), (None, {}, None))

    def test_direct_selection_uses_labeled_sparql(self):
        prof, seen = Profile(EU), {}
        def ask(question, questions):
            seen.update(questions)
            return {k: {"choice": {"select": self.Q10, "acronym": "LUMEN"}[k], "confidence": 0.9, "probabilities": {}} for k in questions}
        out = answer("List LUMEN expenses for Q1 2026", prof, ask)
        self.assertEqual(list(seen["select"]["criteria"]), [*prof.catalog, "none"])
        text = seen["select"]["criteria"][self.Q10]  # the .rq text without indentation or blank lines, labels for the opaque IRIs
        self.assertTrue(text.startswith("PREFIX ex:"))
        self.assertNotIn("\n ", text)
        self.assertNotIn("\n\n", text)
        self.assertIn("?project a ex:EuropeanProject ; ex:acronym ?acronym", text)
        self.assertIn("ex:chargedToWorkPackage ?workPackage", seen["select"]["criteria"][self.Q10])
        self.assertNotIn("ex:P", seen["select"]["criteria"][self.Q10])
        self.assertEqual((out["selected"], len(out["result"][1])), (self.Q10, 6))


class DbTest(unittest.TestCase):
    def test_independent_runs_and_previous_model_version(self):
        db = ProfileDb(":memory:")
        self.addCleanup(db.conn.close)
        self.assertIsNone(db.prev_eval("p", "winnow", "1.0.0"))
        self.assertEqual(db.next_run_id(), 1)
        row = ("p", 1, "q?", "q01", "q01", 0.987, '{"acronym": "LUMEN"}', "", 3, 1, "winnow", "1.0.0", 1, "e1")
        db.put_evals([row])
        self.assertEqual(db.next_run_id(), 2)
        self.assertEqual(db.prev_eval("p", "winnow", "1.0.0"), ("e1", {1: ("q01", 0.99, 3, 1)}))
        db.put_evals([row[:12] + (2, "e2")])
        self.assertEqual(db.prev_eval("p", "winnow", "1.0.0")[0], "e2")
        self.assertIsNone(db.prev_eval("p", "decider", "1.0.0"))
        self.assertIsNone(db.prev_eval("p", "winnow", "2.0.0"))
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM direct_eval").fetchone()[0], 2)

    def test_failed_write_is_atomic(self):
        import sqlite3
        db = ProfileDb(":memory:")
        self.addCleanup(db.conn.close)
        row = ("p", 1, "q?", "none", "none", 1.0, "{}", "", None, 1, "winnow", "1", 1, "d")
        with self.assertRaises(sqlite3.IntegrityError):
            db.put_evals([row, row])
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM direct_eval").fetchone()[0], 0)


class EvalCliTest(unittest.TestCase):
    def test_eval_runs_without_preprocessing_and_preserves_history(self):
        from wsparql import __main__ as cli
        prof = Profile(EU)
        prof.test_questions = [
            {"q_id": 1, "question": "List LUMEN expenses for Q1 2026", "expected_query": AnswerTest.Q10},
            {"q_id": 2, "question": "Weather?", "expected_query": "none"},
            {"q_id": 3, "question": "Ambiguous question"},
        ]
        def ask(question, questions):
            choice = AnswerTest.Q10 if "LUMEN" in question else "none"
            return {"select": {"choice": choice, "confidence": 0.9, "probabilities": {}}}
        with tempfile.TemporaryDirectory() as directory:
            prof.db_path = Path(directory) / "profile.db"
            output = io.StringIO()
            with patch.object(cli, "Profile", return_value=prof), \
                 patch.object(cli.pipeline, "answer", side_effect=lambda question, profile: answer(question, profile, ask)), \
                 patch("sys.argv", ["wsparql", "eval"]), redirect_stdout(output):
                for _ in range(2):
                    with self.assertRaises(SystemExit) as result:
                        cli.main()
                    self.assertEqual(result.exception.code, 0)
            db = ProfileDb(prof.db_path)
            self.addCleanup(db.conn.close)
            self.assertEqual(db.conn.execute("SELECT run_id, COUNT(*) FROM direct_eval GROUP BY run_id").fetchall(), [(1, 2), (2, 2)])
            self.assertEqual(db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("direct_eval",)])
            self.assertIn("same as previous evaluation", output.getvalue())
            self.assertIn("skipped 1", output.getvalue())


class EtlTest(unittest.TestCase):
    def test_csv_round_trip_equals_the_committed_abox(self):
        for path in PROFILES:
            with self.subTest(profile=path.name):
                committed = set(Graph().parse(path / "abox.ttl"))  # no blank nodes: set equality is graph equality
                self.assertEqual(set(etl.build(path)), committed, "csv/ and abox.ttl differ -> make abox")

    def test_rejects_bad_value_unknown_column_and_dangling_reference(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(os.path.join(EU, "tbox.ttl"), d)
            os.mkdir(os.path.join(d, "csv"))
            expense = lambda text: Path(d, "csv", "Expense.csv").write_text(text)
            expense("id,amount,expenseDate\nE1,10.00,2026-13-01\n")
            with self.assertLogs("rdflib"), self.assertRaisesRegex(ValueError, "E1.expenseDate"):
                etl.build(d)
            expense("id,amount,colour\nE1,10.00,red\n")
            self.assertRaisesRegex(ValueError, "colour", etl.build, d)
            expense("id,amount,supplier\nE1,10.00,Nobody\n")
            self.assertRaisesRegex(ValueError, "Nobody", etl.build, d)
            expense("id,amount,category\nE1,10.00,Travel\n")  # TBOX individuals are valid references
            self.assertEqual(len(etl.build(d)), 3)


class ExpectedRowsTest(unittest.TestCase):
    def test_every_case_reproduces_the_expected_values(self):
        """profile/*/tests/expected.json = [{q_id, query, params, rows, expected}]: the draft's cq/expected.json values
        (the cells of each competency query, flattened; CQ3's "city, country" split, the merged query returns them apart)
        with the query and parameters that answer the competency question since the siblings merged. Every expected value
        must be among the returned cells (a merged query returns more columns) and the row count must match. Sets: the
        draft deduplicated two of its lists (CQ3, CQ7). See make expected."""
        for f in sorted(Path("profile").glob("*/tests/expected.json")):
            prof = Profile(f.parent.parent)
            self.assertEqual(sorted({c["query"] for c in prof.expected}), sorted(prof.catalog), f"{f}: every catalog query has a case")
            for c, n, missing in prof.check_expected():
                with self.subTest(profile=prof.name, q_id=c["q_id"]):
                    self.assertEqual(n, c["rows"])
                    self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
