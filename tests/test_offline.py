"""Offline checks (no Ollaya): run with `make test`. The profile-specific tests pin their profile; the generic ones
(ETL round trip, expected query values) run on every profile/* directory."""
import json
import os
import shutil
import tempfile
import unittest
from decimal import Decimal, InvalidOperation
from pathlib import Path

from rdflib import Graph

from wsparql import etl
from wsparql.db import ProfileDb
from wsparql.pipeline import answer, candidates, extract_params, extract_period, select
from wsparql.profile import Profile, literal
from wsparql.tags import generate, slug

EU = "profile/eu-expense-poc"
PROFILES = sorted(p.parent for p in Path("profile").glob("*/csv"))
CATALOG = {
    "q01-total-expenses-by-project": {"description": "d", "tags": ["expense", "project", "total", "comparison"]},
    "q05-budget-vs-spent": {"description": "d", "tags": ["project", "budget", "expense", "remaining", "comparison"]},
    "q06-ineligible-expenses": {"description": "d", "tags": ["expense", "eligibility", "list"]},
}


class CandidatesTest(unittest.TestCase):
    def test_ranks_by_mean_tag_probability(self):
        probs = {"expense": 0.9, "project": 0.9, "budget": 0.95, "remaining": 0.9, "comparison": 0.5, "total": 0.2}
        ranked = candidates(probs, CATALOG, k=2)
        self.assertEqual([q for q, _ in ranked], ["q05-budget-vs-spent", "q01-total-expenses-by-project"])
        self.assertAlmostEqual(ranked[0][1], (0.9 + 0.95 + 0.9 + 0.9 + 0.5) / 5)

    def test_undetected_tags_count_as_zero_and_k_limits(self):
        ranked = candidates({"eligibility": 1.0}, CATALOG, k=1)
        self.assertEqual(ranked, [("q06-ineligible-expenses", 1.0 / 3)])


if __name__ == "__main__":
    unittest.main()


class SelectTest(unittest.TestCase):
    RANKED = [("q06-ineligible-expenses", 0.9), ("q01-total-expenses-by-project", 0.5)]

    def ask(self, choice, confidence):
        """Stub for ollaya.decide: records the criteria sent, answers with a fixed choice."""
        def _ask(question, questions):
            self.criteria = questions["select"]["criteria"]
            return {"select": {"choice": choice, "confidence": confidence, "probabilities": {}}}
        return _ask

    def test_criteria_are_candidates_plus_none(self):
        select("q", self.RANKED, CATALOG, self.ask("none", 0.9))
        self.assertEqual(list(self.criteria), ["q06-ineligible-expenses", "q01-total-expenses-by-project", "none"])

    def test_none_or_low_confidence_means_no_query(self):
        self.assertEqual(select("q", self.RANKED, CATALOG, self.ask("q06-ineligible-expenses", 0.9))[0], "q06-ineligible-expenses")
        self.assertIsNone(select("q", self.RANKED, CATALOG, self.ask("none", 0.9))[0])
        self.assertIsNone(select("q", self.RANKED, CATALOG, self.ask("q06-ineligible-expenses", 0.3))[0])


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
    PROBS = {t: 1.0 for t in ["expense", "project", "time", "date-range", "list"]}

    def ask(self, choice, acronym="LUMEN"):
        """Stub for ollaya.decide answering whichever choice question is asked."""
        answers = {"select": choice, "acronym": acronym}
        return lambda question, questions: {k: {"choice": answers[k], "confidence": 0.9, "probabilities": {}} for k in questions}

    def test_select_params_run(self):
        prof = Profile(EU)
        for q in prof.catalog.values():  # query tags come from profile.db query_tags (make query-tags), not the catalog file
            q["tags"] = ["expense"]
        prof.catalog[self.Q10]["tags"] = list(self.PROBS)
        out = answer("List LUMEN expenses for Q1 2026", self.PROBS, prof, self.ask(self.Q10))
        self.assertEqual((out["selected"], out["params"], out["missing"]), (self.Q10, {"acronym": "LUMEN", "from": "2026-01-01", "to": "2026-03-31"}, []))
        self.assertEqual(len(out["result"][1]), 6)
        out = answer("List LUMEN expenses", self.PROBS, prof, self.ask(self.Q10))
        self.assertEqual((out["missing"], out["result"]), (["from", "to"], None))
        out = answer("What is the weather in Brussels?", self.PROBS, prof, self.ask("none"))
        self.assertEqual((out["selected"], out["params"], out["result"], out["via"]), (None, {}, None, "fallback"))

    def test_fallback_when_the_tag_route_says_none(self):
        prof = Profile(EU)
        for q in prof.catalog.values():
            q["tags"] = ["expense"]
        def ask(question, questions):  # none over descriptions, Q10 over the SPARQL text
            if "select" in questions:
                raw = any(v.startswith("PREFIX") for v in questions["select"]["criteria"].values())
                return {"select": {"choice": self.Q10 if raw else "none", "confidence": 0.9, "probabilities": {}}}
            return {"acronym": {"choice": "LUMEN", "confidence": 0.9, "probabilities": {}}}
        out = answer("List LUMEN expenses for Q1 2026", self.PROBS, prof, ask)
        self.assertEqual((out["via"], out["tag_route"], out["selected"], len(out["result"][1])), ("fallback", (0.9, {}), self.Q10, 6))


    def test_direct_baseline(self):
        prof, seen = Profile(EU), {}
        def ask(question, questions):
            seen.update(questions)
            return {k: {"choice": {"select": self.Q10, "acronym": "LUMEN"}[k], "confidence": 0.9, "probabilities": {}} for k in questions}
        out = answer("List LUMEN expenses for Q1 2026", {}, prof, ask, direct=True)
        self.assertEqual(list(seen["select"]["criteria"]), [*prof.catalog, "none"])
        text = seen["select"]["criteria"][self.Q10]  # the .rq text without indentation or blank lines, labels for the opaque IRIs
        self.assertTrue(text.startswith("PREFIX ex:"))
        self.assertNotIn("\n ", text)
        self.assertNotIn("\n\n", text)
        self.assertIn("?project a ex:EuropeanProject ; ex:acronym ?acronym", text)
        self.assertIn("ex:chargedToWorkPackage ?workPackage", seen["select"]["criteria"][self.Q10])
        self.assertNotIn("ex:P", seen["select"]["criteria"][self.Q10])
        self.assertEqual(([q for q, _ in out["candidates"]], out["selected"], out["via"], len(out["result"][1])), (list(prof.catalog), self.Q10, "direct", 6))


class TagsGenTest(unittest.TestCase):
    def test_eu_expense_dictionary(self):
        rows = generate(EU)
        self.assertEqual([t for t, _, _ in rows], [  # each rule in IRI order (opaque IRIs, numbered in declaration order)
            "european-project", "work-package", "employee", "supplier", "expense", "expense-category",  # R1, Company skipped
            "personnel", "travel", "equipment", "subcontracting", "other-goods-and-services",  # R2
            "time", "budget", "amount", "eligible",  # R3
            "total", "breakdown", "comparison", "ranking", "list", "trend", "month", "date-range"])  # R4
        self.assertTrue(all(d for _, d, _ in rows))
        self.assertEqual({t: s for t, _, s in rows}["travel"], "individual ex:I02")
        self.assertEqual(slug("EuropeanProject"), "european-project")

    def test_c3po_dictionary(self):
        rows = generate("profile/c3po")
        self.assertEqual([t for t, _, _ in rows], [
            # R1: a class counts the individuals of its TBOX subclasses (employee 5, reporting period 9);
            # external employee (1), European project (1) and the personnel cost classes (0) skipped
            "employee", "invoice", "work-package", "reporting-period", "internal-employee", "task", "timesheet", "travel",
            "european-reporting-period", "coordinator-reporting-period", "payslip",
            # R2: no TBOX individuals. R3: 21 numeric properties, the dates as `time`
            "total-travel-cost", "budget-spent", "budget-remaining", "total-budget", "total-personnel-cost",
            "external-employee-hourly-rate", "hours-worked", "person-month-allocated", "time", "invoice-amount",
            "annual-productive-hours", "gross-monthly-salary", "employer-social-contribution", "hourly-rate", "exchange-rate",
            "person-month-spent", "project-duration", "total-gross-salary", "total-employer-social-contribution",
            "annual-personnel-cost", "cost-amount", "monthly-productive-hours",
            "total", "breakdown", "comparison", "ranking", "list", "trend", "month", "date-range"])  # R4
        self.assertEqual({t: s for t, _, s in rows}["employee"], "class c3po:C3PO_0000018")


class DbTest(unittest.TestCase):
    KEY = ("p", "winnow", "1.0.0")

    def test_tags_replaced_and_ollaya_runs_share_the_counter(self):
        db = ProfileDb(":memory:")
        self.assertIsNone(db.tags("p", "1.0.0"))
        db.put_tags("p", "1.0.0", "d1", [("a", "A", "intent"), ("c", "C", "intent")])
        db.put_tags("p", "1.0.0", "d2", [("a", "A2", "intent"), ("b", "B", "class ex:B")])  # deterministic: replaced, no run_id
        self.assertEqual(db.tags("p", "1.0.0"), {"a": "A2", "b": "B"})
        self.assertIsNone(db.tags("p", "2.0.0"))
        db.put("p", 1, "q?", {"a": 0.1}, "winnow", "1.0.0", "d1", db.next_run_id())
        db.put_query_tags("p", "winnow", "1.0.0", "d3", db.next_run_id(), [(1, "q01", "desc", {"a": 0.9})])
        self.assertEqual(db.query_tags("p", "winnow", "1.0.0"), ({"q01": {"a": 0.9}}, 2))  # one counter over query_tags + tag_cache
        self.assertIsNone(db.query_tags("p", "other", "1.0.0"))

    def test_tag_runs_and_eval_rows(self):
        db = ProfileDb(":memory:")
        self.assertIsNone(db.last_run_id(*self.KEY))
        db.put("p", 1, "q?", {"a": 0.1}, "winnow", "1.0.0", "d1", 1)
        db.put("p", 1, "q?", {"a": 0.9}, "winnow", "1.0.0", "d2", 2)
        self.assertEqual(db.get("p", "q?", "winnow", "1.0.0"), ({"a": 0.9}, 2))
        self.assertEqual(db.get("p", "q?", "winnow", "1.0.0", run_id=1), ({"a": 0.1}, 1))
        self.assertIsNone(db.get("p", "q?", "winnow", "1.0.0", run_id=3))
        self.assertEqual((db.last_run_id(*self.KEY), db.last_run_id("p", "other", "1.0.0")), (2, None))
        self.assertIsNone(db.prev_eval(*self.KEY, 2))
        row = ("p", 1, "q?", "q01", "q01", 0.987, '{"acronym": "LUMEN"}', "", 3, 1, "winnow", "1.0.0", 2, "e1")
        db.put_evals([row, ("p", 2, "w?", "none", "none", 1.0, "{}", "", None, 1, "winnow", "1.0.0", 2, "e1")])
        self.assertEqual(db.prev_eval(*self.KEY, 2), ("e1", {1: ("q01", 0.99, 3, 1), 2: ("none", 1.0, None, 1)}))
        db.put_evals([row[:-1] + ("e2",)])  # same (profile, q_id, run_id): replaced, not added
        self.assertEqual(db.conn.execute("SELECT COUNT(*), MAX(date) FROM eval_result").fetchone(), (2, "e2"))


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
    @staticmethod
    def norm(v):
        """Numbers at 6 decimals (the ETL types `0` as `0.0`; summation order moves the 28th digit of a SUM), else as is."""
        try:
            return f"{Decimal(v):.6f}"
        except InvalidOperation:
            return v

    def test_every_case_reproduces_the_expected_values(self):
        """profile/*/tests/expected.json = [{q_id, query, params, rows, expected}]: the draft's cq/expected.json values
        (the cells of each competency query, flattened; CQ3's "city, country" split, the merged query returns them apart)
        with the query and parameters that answer the competency question since the siblings merged. Every expected value
        must be among the returned cells (a merged query returns more columns) and the row count must match. Sets: the
        draft deduplicated two of its lists (CQ3, CQ7). Raw graph.query, so IRIs compare in full."""
        for f in sorted(Path("profile").glob("*/tests/expected.json")):
            prof, cases = Profile(f.parent.parent), json.loads(f.read_text())
            self.assertEqual(sorted({c["query"] for c in cases}), sorted(prof.catalog), f"{f}: every catalog query has a case")
            for c in cases:
                with self.subTest(profile=prof.name, q_id=c["q_id"]):
                    rows = list(prof.graph.query(prof.queries[c["query"]], initBindings={k: literal(v) for k, v in c["params"].items()}))
                    got = {self.norm(str(x)) for row in rows for x in row if x is not None}
                    self.assertEqual(len(rows), c["rows"])
                    self.assertEqual({self.norm(v) for v in c["expected"]} - got, set())
