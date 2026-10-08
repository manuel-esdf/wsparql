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


def print_tags(probs, min_prob=0.0):
    print_table(["tag", "prob"], [[t, f"{v:.2f}"] for t, v in probs.items() if v >= min_prob])


def print_selection(prof, ranked, qid, conf, prob):
    print_table(["candidate", "score", "prob", "description"],
                [[q, f"{s:.2f}", f"{prob[q]:.2f}", prof.catalog[q]["description"]] for q, s in ranked]
                + [[pipeline.NONE, "", f"{prob[pipeline.NONE]:.2f}", "no suitable query"]])
    best = max(prob, key=prob.get)
    print(f"selected: {qid} (confidence {conf:.2f})" if qid
          else f"no suitable query (choice {best} {conf:.2f}, min confidence {pipeline.MIN_CONFIDENCE})")


def print_answer(prof, out):
    """The README demo blocks after the question: tags, candidates + selection, parameters, result."""
    print_tags(out["tags"], 0.5)
    print()
    print_selection(prof, out["candidates"], out["selected"], out["confidence"], out["probabilities"])
    if not out["selected"]:
        return
    print()
    if out["how"]:
        print_table(["param", "value", "how"], [[n, out["params"].get(n, "-"), h] for n, h in out["how"].items()])
    else:
        print(f"params: {out['selected']} takes no parameters")
    if out["missing"]:
        print(f"no suitable query (missing parameter {', '.join(out['missing'])})")
    else:
        cols, rows = out["result"]
        print(f"\nresult: {len(rows)} rows")
        print_table(cols, rows)


def call_ollaya(fn, *args):
    try:
        return fn(*args)
    except urllib.error.URLError as e:
        sys.exit(f"Ollaya unreachable at {ollaya.HOST} ({e.reason}) -> make ollaya-check")


def question_or_default(p, prof, question):
    if not question or not question.strip():
        if not prof.test_questions:
            p.error("no question supplied and profile tests/test-questions.yaml has no questions")
        question = prof.test_questions[0]["question"]
    print(f"Q: {question}", flush=True)
    return question


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
    default_q = "defaults to the first profile tests/test-questions.yaml question"
    s = sub.add_parser("sparql", help="run one catalog query; without an id, run all and print row counts")
    s.add_argument("query_id", nargs="?")
    s.add_argument("bindings", nargs="*", help="param=value, e.g. acronym=GRAPHIA from=2026-01-01 to=2026-06-30; missing = catalog example")
    sub.add_parser("tags", help="detect tags for a question with Ollaya (one noul question per tag)").add_argument("question", nargs="?", help=default_q)
    sub.add_parser("candidates", help="rank catalog queries by tag overlap (top 3); tags from the cache when the question is cached, else Ollaya").add_argument("question", nargs="?", help=default_q)
    sub.add_parser("select", help="rank candidates, then Ollaya picks the best query or none (choice question)").add_argument("question", nargs="?", help=default_q)
    pa = sub.add_parser("params", help="extract the query parameters found in a question: acronym (Ollaya choice over ABOX projects + none), from/to (regex); lists every catalog parameter and the queries needing it")
    pa.add_argument("question", nargs="?", help="no question = run on every test question whose expected query takes parameters")
    sub.add_parser("ask", help="answer a question end to end: tags, candidates, selected query, parameters, result rows or no suitable query").add_argument("question", nargs="?", help=default_q)
    sub.add_parser("demo", help="ask every tests/test-questions.yaml question that has an expected_query, off-topic ones included")
    sub.add_parser("eval", help="full chain on every tests/test-questions.yaml question that has an expected_query: expected query selected and returns rows, none answers no suitable query; exit 1 on any mismatch")
    sub.add_parser("tags-cache", help="detect tags for every tests/test-questions.yaml question, store them in profile/profile.db (new run_id)")
    args = p.parse_args()
    prof = Profile(args.profile)
    cache = TagCache(prof.db_path)
    labeled = [q for q in prof.test_questions if "expected_query" in q]

    if args.cmd == "sparql":
        if args.query_id:
            if args.query_id not in prof.queries:
                p.error(f"unknown query id {args.query_id!r}; one of: {', '.join(prof.queries)}")
            declared = prof.catalog[args.query_id].get("params", {})
            if bad := [b for b in args.bindings if "=" not in b]:
                p.error(f"ARGS must be param=value pairs, got {' '.join(bad)!r}")
            given = dict(b.split("=", 1) for b in args.bindings)
            if unknown := set(given) - set(declared):
                p.error(f"{args.query_id} takes {', '.join(declared) or 'no parameters'}, not {', '.join(sorted(unknown))}")
            params = {**declared, **given}
            if params:
                print("params: " + " ".join(f"{k}={v}" for k, v in params.items()) + ("" if given else " (catalog example)"))
            print_table(*prof.run(args.query_id, params))
        else:
            for qid in prof.queries:
                print(f"{qid:<36} {len(prof.run(qid, prof.catalog[qid].get('params'))[1]):>3} rows")
    elif args.cmd == "tags":
        print_tags(call_ollaya(ollaya.detect_tags, question_or_default(p, prof, args.question), prof.tags))
    elif args.cmd == "candidates":
        question = question_or_default(p, prof, args.question)
        probs, _ = detect(prof, cache, question)
        print_tags(probs, 0.5)
        print()
        print_table(["candidate", "score", "description"],
                    [[q, f"{s:.2f}", prof.catalog[q]["description"]] for q, s in pipeline.candidates(probs, prof.catalog)])
    elif args.cmd == "select":
        question = question_or_default(p, prof, args.question)
        probs, _ = detect(prof, cache, question)
        ranked = pipeline.candidates(probs, prof.catalog)
        print_selection(prof, ranked, *call_ollaya(pipeline.select, question, ranked, prof.catalog))
    elif args.cmd == "params":
        needed_by = {n: [qid for qid, q in prof.catalog.items() if n in q.get("params", {})]
                     for n in sorted({n for q in prof.catalog.values() for n in q.get("params", {})})}
        names = list(needed_by)
        if args.question and args.question.strip():
            print(f"Q: {args.question}", flush=True)
            found, how = call_ollaya(pipeline.extract_params, args.question, names, prof.acronyms)
            print_table(["param", "value", "how", "needed by"],
                        [[n, found.get(n, "-"), how[n], ", ".join(qids)] for n, qids in needed_by.items()])
        else:  # working examples: every test question whose expected query takes parameters
            examples = [q for q in prof.test_questions if prof.catalog.get(q.get("expected_query"), {}).get("params")]
            rows = []
            for q in examples:
                found, _ = call_ollaya(pipeline.extract_params, q["question"], names, prof.acronyms)
                rows.append([str(q["q_id"]), q["question"], q["expected_query"], *[found.get(n, "-") for n in names]])
            print_table(["q_id", "question", "expected_query", *names], rows)
    elif args.cmd == "ask":
        question = question_or_default(p, prof, args.question)
        probs, _ = detect(prof, cache, question)
        print_answer(prof, call_ollaya(pipeline.answer, question, probs, prof))
    elif args.cmd == "demo":
        for d in labeled:
            print(f"\n--- [{d['q_id']}] expected {d['expected_query']}\nQ: {d['question']}", flush=True)
            probs, _ = detect(prof, cache, d["question"])
            print_answer(prof, call_ollaya(pipeline.answer, d["question"], probs, prof))
    elif args.cmd == "eval":
        ok = 0
        for d in labeled:
            q, expected = d["question"], d["expected_query"]
            probs, _ = detect(prof, cache, q, log=lambda *_: None)
            out = call_ollaya(pipeline.answer, q, probs, prof)
            got = out["selected"] or pipeline.NONE
            rows = f"{len(out['result'][1])} rows" if out["result"] else f"missing {', '.join(out['missing'])}" if out["missing"] else "-"
            hit = expected == (got if out["result"] and out["result"][1] else pipeline.NONE)
            ok += hit
            print(f"{'ok  ' if hit else 'FAIL'} [{d['q_id']:>2}] {expected:<32} {got:<32} {out['confidence']:.2f} {rows:<10} | {q}", flush=True)
        print(f"{ok}/{len(labeled)} (skipped {len(prof.test_questions) - len(labeled)} questions without expected_query)")
        sys.exit(0 if ok == len(labeled) else 1)
    elif args.cmd == "tags-cache":
        run_id = call_ollaya(fill, prof, cache, ollaya.MODEL)
        print(f"cached {len(prof.test_questions)} questions in {prof.db_path} (run_id {run_id}, total rows {cache.count()})")


if __name__ == "__main__":
    main()
