"""Decision pipeline: detected tags -> ranked candidate queries -> Ollaya selects one or none -> query parameters -> result."""
import calendar
import re

from wsparql import ollaya


TAG_THRESHOLD = 0.5  # ponytail: a query's tags = those Ollaya detected at >= 0.5 on its description; the probabilities stay in query_tags


def candidates(tag_probs, catalog, k=3):
    """Rank catalog queries by the mean detected probability of their tags; returns the top k as [(qid, score)]."""
    # ponytail: plain mean; a query with a wide tag list is diluted: tighten its description (IDF weighting tested offline, no gain)
    scored = [(qid, sum(tag_probs.get(t, 0.0) for t in q["tags"]) / len(q["tags"])) for qid, q in catalog.items()]
    return sorted(scored, key=lambda x: -x[1])[:k]


MIN_CONFIDENCE = 0.4  # ponytail: fixed threshold; tune after `make eval` if it misroutes
NONE = "none"
SELECT_INSTRUCTIONS = ("The queries are templates: the project, employee, supplier and dates named in the question are filled in "
                       "afterwards. Which query computes the answer? Pick none only for an off-topic question or an answer no "
                       "query can compute.")


NONE_CRITERION = "Off-topic, or none of these queries computes the requested answer even with its parameters filled in"
DIRECT_INSTRUCTIONS = ("Which SPARQL query computes the answer to the question? ?acronym, ?from and ?to are parameters filled in "
                       "afterwards. Pick none only for an off-topic question or an answer no query computes.")


def choose(question, instructions, criteria, ask):
    """One Ollaya choice question over `criteria` plus `none`.
    Returns (qid or None for "no suitable query", confidence, {label: probability})."""
    criteria[NONE] = NONE_CRITERION
    a = ask(question, {"select": {"type": "choice", "instructions": instructions, "criteria": criteria}})["select"]
    qid = None if a["choice"] == NONE or a["confidence"] < MIN_CONFIDENCE else a["choice"]
    return qid, a["confidence"], a["probabilities"]


def select(question, ranked, catalog, ask=ollaya.decide):
    """The ranked candidates, described by their catalog description."""
    return choose(question, SELECT_INSTRUCTIONS, {qid: catalog[qid]["description"] for qid, _ in ranked}, ask)


def select_direct(question, prof, ask=ollaya.decide):
    """Baseline without tags: every catalog query, described by its raw SPARQL text."""
    return choose(question, DIRECT_INSTRUCTIONS, {qid: prof.queries[qid] for qid in prof.catalog}, ask)


MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
QUARTERS = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def extract_period(text):
    """(from, to) ISO dates: 'Q1 2026' / 'first quarter of 2026' -> quarter; month names -> first..last named month
    of that year ('between January and March 2026', 'March 2026'); a year alone -> whole year; no year -> None."""
    # ponytail: regex; switch to an Ollaya choice over quarters/years if phrasing varies ("last six months" -> None)
    t = text.lower()
    year = re.search(r"\b(20\d\d)\b", t)
    if not year:
        return None
    y = int(year.group(1))
    q = re.search(r"\bq([1-4])\b", t) or re.search(r"\b(first|second|third|fourth) quarter\b", t)
    if q:
        n = int(q.group(1)) if q.group(1).isdigit() else QUARTERS[q.group(1)]
        a, b = 3 * n - 2, 3 * n
    else:
        months = [MONTHS[m] for m in re.findall(r"\b(" + "|".join(MONTHS) + r")\b", t)]
        a, b = (min(months), max(months)) if months else (1, 12)
    return f"{y}-{a:02d}-01", f"{y}-{b:02d}-{calendar.monthrange(y, b)[1]}"


def extract_params(question, names, acronyms, ask=ollaya.decide):
    """Values for the named query parameters. Returns (found {name: value}, how {name: one-line explanation});
    a name absent from `found` is missing. acronym: one Ollaya choice over the ABOX acronyms plus none; from/to: extract_period."""
    found, how = {}, {}
    if "acronym" in names:
        criteria = {a: f"The question is about the project {a}" for a in acronyms}
        criteria[NONE] = "The question names no specific project"
        a = ask(question, {"acronym": {"type": "choice", "instructions": "Which European project is the question about?",
                                       "criteria": criteria}})["acronym"]
        if a["choice"] != NONE and a["confidence"] >= MIN_CONFIDENCE:
            found["acronym"] = a["choice"]
            how["acronym"] = f"Ollaya choice over {len(acronyms)} ABOX projects + none, confidence {a['confidence']:.2f}"
        else:
            how["acronym"] = f"Ollaya choice over {len(acronyms)} ABOX projects + none: {a['choice']} ({a['confidence']:.2f}, min {MIN_CONFIDENCE})"
    if {"from", "to"} & set(names):
        period = extract_period(question)
        if period:
            found["from"], found["to"] = period
        note = "regex: quarter, month name or year in the question" if period else "regex: no quarter, month name or year in the question"
        how.update({n: note for n in ("from", "to") if n in names})
    return found, how


def answer(question, tag_probs, prof, ask=ollaya.decide, direct=False):
    """Rank, select, extract the selected query's parameters, run it. Returns the demo blocks:
    {question, tags, candidates, selected, confidence, probabilities, params, how, missing, result};
    selected None = no suitable query; missing = declared params not found (query not run); result = (cols, rows) or None.
    direct: no tags, no ranking, select_direct over every query (baseline)."""
    if direct:
        ranked = [(qid, 0.0) for qid in prof.catalog]
        qid, conf, prob = select_direct(question, prof, ask)
    else:
        ranked = candidates(tag_probs, prof.catalog)
        qid, conf, prob = select(question, ranked, prof.catalog, ask)
    out = dict(question=question, tags=tag_probs, candidates=ranked, selected=qid, confidence=conf,
               probabilities=prob, params={}, how={}, missing=[], result=None)
    if qid:
        names = list(prof.catalog[qid].get("params", {}))
        if names:
            out["params"], out["how"] = extract_params(question, names, prof.acronyms, ask)
        out["missing"] = [n for n in names if n not in out["params"]]
        if not out["missing"]:
            out["result"] = prof.run(qid, out["params"])
    return out
