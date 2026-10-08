"""Offline checks (no Ollaya): run with `make test`."""
import os
import unittest

from wsparql.db import ProfileDb
from wsparql.pipeline import answer, candidates, extract_params, extract_period, select
from wsparql.profile import Profile
from wsparql.tags import generate, slug

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


class ParamsTest(unittest.TestCase):
    NAMES = ["acronym", "from", "to"]

    def ask(self, choice, confidence):
        return lambda question, questions: {"acronym": {"choice": choice, "confidence": confidence, "probabilities": {}}}

    def test_found_and_missing(self):
        found, how = extract_params("List LUMEN expenses for Q1 2026", self.NAMES, ["GRAPHIA", "LUMEN"], self.ask("LUMEN", 0.9))
        self.assertEqual(found, {"acronym": "LUMEN", "from": "2026-01-01", "to": "2026-03-31"})
        self.assertEqual(sorted(how), self.NAMES)  # one explanation per requested parameter
        found, how = extract_params("Spending overview please.", self.NAMES, ["LUMEN"], self.ask("none", 0.9))
        self.assertEqual((found, sorted(how)), ({}, self.NAMES))
        self.assertEqual(extract_params("q", ["acronym"], ["LUMEN"], self.ask("LUMEN", 0.2))[0], {})


class BindingsTest(unittest.TestCase):
    def test_q10_runs_with_bound_params(self):
        prof = Profile(os.environ["PROFILE"])
        q = "q10-project-expenses-in-period"
        self.assertEqual(prof.acronyms, ["GRAPHIA", "LUMEN", "OPENSCIENCE"])
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
        prof = Profile(os.environ["PROFILE"])
        for q in prof.catalog.values():  # query tags come from profile.db query_tags (make query-tags), not the catalog file
            q["tags"] = ["expense"]
        prof.catalog[self.Q10]["tags"] = list(self.PROBS)
        out = answer("List LUMEN expenses for Q1 2026", self.PROBS, prof, self.ask(self.Q10))
        self.assertEqual((out["selected"], out["params"], out["missing"]), (self.Q10, {"acronym": "LUMEN", "from": "2026-01-01", "to": "2026-03-31"}, []))
        self.assertEqual(len(out["result"][1]), 6)
        out = answer("List LUMEN expenses", self.PROBS, prof, self.ask(self.Q10))
        self.assertEqual((out["missing"], out["result"]), (["from", "to"], None))
        out = answer("What is the weather in Brussels?", self.PROBS, prof, self.ask("none"))
        self.assertEqual((out["selected"], out["params"], out["result"]), (None, {}, None))


    def test_direct_baseline(self):
        prof, seen = Profile(os.environ["PROFILE"]), {}
        def ask(question, questions):
            seen.update(questions)
            return {k: {"choice": {"select": self.Q10, "acronym": "LUMEN"}[k], "confidence": 0.9, "probabilities": {}} for k in questions}
        out = answer("List LUMEN expenses for Q1 2026", {}, prof, ask, direct=True)
        self.assertEqual(list(seen["select"]["criteria"]), [*prof.catalog, "none"])
        self.assertTrue(seen["select"]["criteria"][self.Q10].startswith("PREFIX"))  # the raw .rq text
        self.assertEqual(([q for q, _ in out["candidates"]], out["selected"], len(out["result"][1])), (list(prof.catalog), self.Q10, 6))


class TagsGenTest(unittest.TestCase):
    def test_profile_dictionary(self):
        rows = generate(os.environ["PROFILE"])
        self.assertEqual([t for t, _, _ in rows], [
            "employee", "european-project", "expense", "expense-category", "supplier", "work-package",  # R1, Company skipped
            "equipment", "other-goods-services", "personnel", "subcontracting", "travel",  # R2
            "amount", "budget", "eligible", "time",  # R3
            "total", "breakdown", "comparison", "ranking", "list", "trend", "month", "date-range"])  # R4
        self.assertTrue(all(d for _, d, _ in rows))
        self.assertEqual({t: s for t, _, s in rows}["travel"], "individual ex:Travel")
        self.assertEqual(slug("EuropeanProject"), "european-project")


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
