"""Decision pipeline, pure Python: detected tags -> ranked candidate queries (-> selection, params in later steps)."""


def candidates(tag_probs, catalog, k=3):
    """Rank catalog queries by the mean detected probability of their tags; returns the top k as [(qid, score)]."""
    # ponytail: plain mean; weight rare tags higher (IDF) if ubiquitous tags like "expense" blur the ranking
    scored = [(qid, sum(tag_probs.get(t, 0.0) for t in q["tags"]) / len(q["tags"])) for qid, q in catalog.items()]
    return sorted(scored, key=lambda x: -x[1])[:k]
