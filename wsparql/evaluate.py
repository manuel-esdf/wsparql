"""Batch evaluations: run a profile's test questions through Ollaya and persist the results."""
from datetime import datetime

from wsparql import ollaya


def run_tag_questions(profile, store, model, log=print):
    """Detect tags for every question in tests/tag-questions.txt; one row per question. Returns the run number."""
    tags_test = store.next_tags_test()  # same value on every row of this run
    date = datetime.now().isoformat(timespec="seconds")
    n = len(profile.tag_questions)
    for i, question in enumerate(profile.tag_questions, 1):
        probs = ollaya.detect_tags(question, profile.tags)
        store.save_tags(tags_test, date, profile.version, model, question, probs)
        top = "  ".join(f"{p:.2f} {t}" for t, p in list(probs.items())[:3])
        log(f"[{i:>2}/{n}] {top} | {question}")
    return tags_test
