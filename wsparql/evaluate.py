"""Batch evaluations: run a profile's test questions through Ollaya and persist the results."""
from datetime import datetime

from wsparql import ollaya


def run_tag_questions(profile, store, model, log=print):
    """Detect tags for every question in tests/tag-questions.csv; one row per question. Returns the run number."""
    tags_test = store.next_tags_test()  # same value on every row of this run
    date = datetime.now().isoformat(timespec="seconds")
    n = len(profile.tag_questions)
    for q_id, question in profile.tag_questions:
        probs = ollaya.detect_tags(question, profile.tags)
        store.save_tags(q_id, question, probs, model, profile.version, date, tags_test)
        top = "  ".join(f"{p:.2f} {t}" for t, p in list(probs.items())[:3])
        log(f"[{q_id:>2}/{n}] {top} | {question}")
    return tags_test
