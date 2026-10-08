"""Decision pipeline: detected tags -> ranked candidate queries -> Ollaya selects one or none (-> params in step 5)."""
from wsparql import ollaya


def candidates(tag_probs, catalog, k=3):
    """Rank catalog queries by the mean detected probability of their tags; returns the top k as [(qid, score)]."""
    # ponytail: plain mean; weight rare tags higher (IDF) if ubiquitous tags like "expense" blur the ranking
    scored = [(qid, sum(tag_probs.get(t, 0.0) for t in q["tags"]) / len(q["tags"])) for qid, q in catalog.items()]
    return sorted(scored, key=lambda x: -x[1])[:k]


MIN_CONFIDENCE = 0.4  # ponytail: fixed threshold; tune after `make eval` if it misroutes
NONE = "none"
SELECT_INSTRUCTIONS = "Which predefined query answers the question? Pick none if no query fits."


def select(question, ranked, catalog, ask=ollaya.decide):
    """One Ollaya choice question over the ranked candidates plus `none`.
    Returns (qid or None for "no suitable query", confidence, {label: probability})."""
    criteria = {qid: catalog[qid]["description"] for qid, _ in ranked}
    criteria[NONE] = "None of these queries answers the question"
    a = ask(question, {"select": {"type": "choice", "instructions": SELECT_INSTRUCTIONS, "criteria": criteria}})["select"]
    qid = None if a["choice"] == NONE or a["confidence"] < MIN_CONFIDENCE else a["choice"]
    return qid, a["confidence"], a["probabilities"]
