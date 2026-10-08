"""Offline checks (no Ollaya): run with `make test`."""
import unittest

from wsparql.pipeline import candidates

CATALOG = {
    "q01-total-expenses-by-project": {"tags": ["expense", "project", "total", "comparison"]},
    "q05-budget-vs-spent": {"tags": ["project", "budget", "expense", "remaining", "comparison"]},
    "q06-ineligible-expenses": {"tags": ["expense", "eligibility", "list"]},
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
