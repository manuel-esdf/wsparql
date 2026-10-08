"""Minimal Ollaya client: POST /v1/systemone with stdlib urllib (no SDK exists)."""
import json
import os
import urllib.request

HOST = os.environ["OLLAYA_HOST"]
MODEL = os.environ["OLLAYA_MODEL"]


def decide(state, questions):
    """Ask typed questions about `state`; returns the `answers` dict keyed like `questions`."""
    body = json.dumps({"model": MODEL, "state": state, "questions": questions}).encode()
    req = urllib.request.Request(f"http://{HOST}/v1/systemone", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)["answers"]


def detect_tags(question, tags):
    """One noul question per tag; returns {tag: probability} sorted by probability desc."""
    answers = decide(question, {t: {"type": "noul", "instructions": d} for t, d in tags.items()})
    return dict(sorted(((t, a["noul"]) for t, a in answers.items()), key=lambda x: -x[1]))
