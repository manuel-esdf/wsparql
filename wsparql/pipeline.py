"""Direct SPARQL query selection, parameter extraction and execution."""
import calendar
import re

from wsparql import ollaya


NONE = "none"
NONE_CRITERION = "Off-topic, or none of these queries computes the requested answer even with its parameters filled in"
# ponytail: "or contains among its rows" lets a breakdown answer a one-category question; without it selection says none


def direct_instructions(names):
    """The selection instructions name the catalog's parameters ("?acronym, ?from and ?to are parameters filled in afterwards")."""
    ps = [f"?{n}" for n in names]
    listed = f"{', '.join(ps[:-1])} and {ps[-1]}" if len(ps) > 1 else "".join(ps)
    return ("Which SPARQL query computes the answer to the question? " + (f"{listed} are parameters filled in afterwards. " if ps else "")
            + "Pick none only for an off-topic question or an answer no query computes or contains among its rows.")


def choose(question, instructions, criteria, ask, min_confidence):
    """One Ollaya choice question over `criteria` plus `none`.
    Returns (qid or None for "no suitable query", confidence, {label: probability})."""
    criteria[NONE] = NONE_CRITERION
    a = ask(question, {"select": {"type": "choice", "instructions": instructions, "criteria": criteria}})["select"]
    qid = None if a["choice"] == NONE or a["confidence"] < min_confidence else a["choice"]
    return qid, a["confidence"], a["probabilities"]


def select(question, prof, ask=ollaya.decide):
    """Choose over every catalog query, with ontology labels replacing opaque IRIs."""
    return choose(question, direct_instructions(prof.parameters), {qid: prof.readable[qid] for qid in prof.catalog}, ask, prof.min_confidence)


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


def named(values, question):
    """The values written in the question (whole words, case-insensitive), longest first."""
    return sorted((v for v in values if re.search(rf"(?<!\w){re.escape(v)}(?!\w)", question, re.I)), key=len, reverse=True)


def extract_params(question, names, prof, ask=ollaya.decide):
    """Values for the named query parameters; prof.parameters says what fills each: a property label (one of its ABOX
    values), a list (one of those words) or date (from/to). Returns (found {name: value}, how {name: one-line explanation});
    a name absent from `found` was not found. A value written in the question wins; else one Ollaya choice over the
    property's values plus none. from/to: the dates of a reporting period named in the question, else extract_period."""
    found, how, text = {}, {}, question
    for n in names:
        kind = prof.parameters[n]
        if kind == "date":
            continue
        values = kind if isinstance(kind, list) else prof.values(kind)
        if hit := named(values, question):
            found[n], how[n] = hit[0], "named in the question"
            text = text.replace(hit[0], " ")  # a name that holds a year ("Dagstuhl Workshop 2023") must not date the question
            continue
        if isinstance(kind, list):
            how[n] = f"none of {', '.join(kind)} in the question"
            continue
        noun = prof.noun(kind)
        criteria = {v: f"The question is about the {noun} {v}" for v in values}
        criteria[NONE] = f"The question names no specific {noun}"
        a = ask(question, {n: {"type": "choice", "instructions": f"Which {noun} is the question about?", "criteria": criteria}})[n]
        if a["choice"] != NONE and a["confidence"] >= prof.parameter_min_confidence:
            found[n] = a["choice"]
            how[n] = f"Ollaya choice over {len(values)} ABOX values + none, confidence {a['confidence']:.2f}"
        else:
            how[n] = f"Ollaya choice over {len(values)} ABOX values + none: {a['choice']} ({a['confidence']:.2f}, min {prof.parameter_min_confidence})"
    if {"from", "to"} & set(names):
        periods = named(prof.periods, question)
        period = prof.periods[periods[0]] if periods else extract_period(text)
        if period:
            found["from"], found["to"] = period
        note = (f"the dates of the reporting period {periods[0]}" if periods else
                "regex: quarter, month name or year in the question" if period else "regex: no quarter, month name or year in the question")
        how.update({n: note for n in ("from", "to") if n in names})
    return found, how


def answer(question, prof, ask=ollaya.decide):
    """Select a catalog query, extract parameters, and execute it when required values are present."""
    qid, conf, prob = select(question, prof, ask)
    out = dict(question=question, selected=qid, confidence=conf, probabilities=prob,
               params={}, how={}, missing=[], result=None)
    if qid:
        required = list(prof.catalog[qid].get("params", {}))
        names = required + list(prof.catalog[qid].get("optional", {}))
        if names:
            out["params"], out["how"] = extract_params(question, names, prof, ask)
        out["missing"] = [n for n in required if n not in out["params"]]
        if not out["missing"]:
            out["result"] = prof.run(qid, out["params"])
    return out
