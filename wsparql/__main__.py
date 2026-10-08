import argparse
import os
import sys
import urllib.error

from wsparql import ollaya, pipeline
from wsparql.cache import TagCache, fill
from wsparql.profile import Profile


def print_table(cols, rows):
    widths = [max(len(x) for x in col) for col in zip(cols, *rows)]
    for r in [cols, *rows]:
        print("  ".join(x.ljust(w) for x, w in zip(r, widths)))


def call_ollaya(fn, *args):
    try:
        return fn(*args)
    except urllib.error.URLError as e:
        sys.exit(f"Ollaya unreachable at {ollaya.HOST} ({e.reason}) -> make ollaya-check")


def question_or_default(p, prof, question):
    if question and question.strip():
        return question
    if not prof.tag_questions:
        p.error("no question supplied and profile tests/tag-questions.csv has no questions")
    print(f"Q: {prof.tag_questions[0][1]}", flush=True)
    return prof.tag_questions[0][1]


def detect(prof, cache, question, log=print):
    """Tag probabilities: last cached run_id when available, else Ollaya. Returns (probs, run_id or None)."""
    hit = cache.get(prof.name, question, ollaya.MODEL, prof.version)
    if hit:
        log(f"tags: cache run_id {hit[1]}")
        return hit
    log("tags: Ollaya (not cached)")
    return call_ollaya(ollaya.detect_tags, question, prof.tags), None


def main():
    p = argparse.ArgumentParser(prog="wsparql")
    p.add_argument("--profile", default=os.environ["PROFILE"])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sparql", help="run one catalog query; without an id, run all and print row counts")
    s.add_argument("query_id", nargs="?")
    t = sub.add_parser("tags", help="detect tags for a question with Ollaya (one noul question per tag)")
    t.add_argument("question")
    c = sub.add_parser("candidates", help="rank catalog queries by tag overlap (top 3); tags from the cache when the question is cached, else Ollaya")
    c.add_argument("question", nargs="?", help="defaults to the first profile tests/tag-questions.csv question")
    sl = sub.add_parser("select", help="rank candidates, then Ollaya picks the best query or none (choice question)")
    sl.add_argument("question", nargs="?", help="defaults to the first profile tests/tag-questions.csv question")
    sub.add_parser("eval", help="route every demo-questions.yaml question; expected vs selected, exit 1 on any mismatch")
    sub.add_parser("tags-cache", help="detect tags for every tests/tag-questions.csv question, store them in profile/profile.db (new run_id)")
    args = p.parse_args()
    prof = Profile(args.profile)
    cache = TagCache(prof.db_path)

    if args.cmd == "sparql":
        if args.query_id:
            print_table(*prof.run(args.query_id))
        else:
            for qid in prof.queries:
                print(f"{qid:<36} {len(prof.run(qid)[1]):>3} rows")
    elif args.cmd == "tags":
        probs = call_ollaya(ollaya.detect_tags, args.question, prof.tags)
        print_table(["tag", "prob"], [[t, f"{v:.2f}"] for t, v in probs.items()])
    elif args.cmd == "candidates":
        question = question_or_default(p, prof, args.question)
        probs, _ = detect(prof, cache, question)
        print_table(["tag", "prob"], [[t, f"{v:.2f}"] for t, v in probs.items() if v >= 0.5])
        print()
        print_table(["candidate", "score", "description"],
                    [[q, f"{s:.2f}", prof.catalog[q]["description"]] for q, s in pipeline.candidates(probs, prof.catalog)])
    elif args.cmd == "select":
        question = question_or_default(p, prof, args.question)
        probs, _ = detect(prof, cache, question)
        ranked = pipeline.candidates(probs, prof.catalog)
        qid, conf, prob = call_ollaya(pipeline.select, question, ranked, prof.catalog)
        print_table(["candidate", "score", "prob", "description"],
                    [[q, f"{s:.2f}", f"{prob[q]:.2f}", prof.catalog[q]["description"]] for q, s in ranked]
                    + [[pipeline.NONE, "", f"{prob[pipeline.NONE]:.2f}", "no suitable query"]])
        best = max(prob, key=prob.get)
        print(f"selected: {qid} (confidence {conf:.2f})" if qid
              else f"no suitable query (choice {best} {conf:.2f}, min confidence {pipeline.MIN_CONFIDENCE})")
    elif args.cmd == "eval":
        ok = 0
        for d in prof.demo_questions:
            q, expected = d["question"], d["expected_query"]
            probs, _ = detect(prof, cache, q, log=lambda *_: None)
            qid, conf, _ = call_ollaya(pipeline.select, q, pipeline.candidates(probs, prof.catalog), prof.catalog)
            ok += qid == expected
            print(f"{'ok  ' if qid == expected else 'FAIL'} {expected:<32} {qid or 'no suitable query':<32} {conf:.2f} | {q}", flush=True)
        print(f"{ok}/{len(prof.demo_questions)}")
        sys.exit(0 if ok == len(prof.demo_questions) else 1)
    elif args.cmd == "tags-cache":
        run_id = call_ollaya(fill, prof, cache, ollaya.MODEL)
        print(f"cached {len(prof.tag_questions)} questions in {prof.db_path} (run_id {run_id}, total rows {cache.count()})")


if __name__ == "__main__":
    main()
