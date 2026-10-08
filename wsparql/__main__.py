import argparse
import json
import os
import sys
import urllib.error
from datetime import datetime

from wsparql import ollaya, pipeline
from wsparql.db import ProfileDb, fill
from wsparql.profile import Profile
from wsparql.tags import generate


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


def detect(prof, db, question, log=print):
    """Tag probabilities: last cached run_id when available, else Ollaya. Returns (probs, run_id or None)."""
    hit = db.get(prof.name, question, ollaya.MODEL, prof.version)
    if hit:
        log(f"tags: cache run_id {hit[1]}")
        return hit
    log("tags: Ollaya (not cached)")
    return call_ollaya(ollaya.detect_tags, question, prof.tags), None


NEED_QUERY_TAGS = {"candidates", "select", "ask", "demo", "eval"}


def load_tags(prof, db, with_query_tags=False):
    """prof.tags = the tag dictionary of this profile version; with_query_tags: each catalog query's tags = those detected
    at >= TAG_THRESHOLD in the latest query-tags run. Exits with the fix when something is missing. Returns the query_tags run_id."""
    prof.tags = db.tags(prof.name, prof.version)
    if not prof.tags:
        sys.exit(f"no tags for {prof.name} {prof.version} -> make tags-gen")
    if not with_query_tags:
        return None
    qt = db.query_tags(prof.name, ollaya.MODEL, prof.version)
    if missing := [q for q in prof.catalog if not qt or q not in qt[0]]:
        sys.exit(f"no query tags for {', '.join(missing)} ({prof.name} {prof.version} {ollaya.MODEL}) -> make query-tags")
    for qid in prof.catalog:
        prof.catalog[qid]["tags"] = [t for t, p in qt[0][qid].items() if p >= pipeline.TAG_THRESHOLD]
    return qt[1]


def main():
    p = argparse.ArgumentParser(prog="wsparql")
    p.add_argument("--profile", default=os.environ["PROFILE"])
    sub = p.add_subparsers(dest="cmd", required=True)
    default_q = "defaults to the first profile tests/test-questions.yaml question"
    s = sub.add_parser("sparql", help="run one catalog query; without an id, run all and print row counts")
    s.add_argument("query_id", nargs="?")
    s.add_argument("bindings", nargs="*", help="param=value, e.g. acronym=GRAPHIA from=2026-01-01 to=2026-06-30; missing = catalog example")
    sub.add_parser("tags-gen", help="derive the tag dictionary from tbox.ttl + abox.ttl (classes, TBOX individuals, datatype properties) plus fixed intent tags, store in profile/profile.db tags (deterministic: no run_id, rows of the profile version replaced); no Ollaya")
    sub.add_parser("query-tags", help="Ollaya assesses every tag of the dictionary against each catalog query description (one noul per tag), store {tag: prob} per query in profile/profile.db query_tags (new run_id); a query's tags = those >= 0.5")
    sub.add_parser("tags", help="detect tags for a question with Ollaya (one noul question per tag of the dictionary)").add_argument("question", nargs="?", help=default_q)
    sub.add_parser("candidates", help="rank catalog queries by tag overlap (top 3); question tags from the cache when the question is cached, else Ollaya; query tags from the latest query-tags run").add_argument("question", nargs="?", help=default_q)
    sub.add_parser("select", help="rank candidates, then Ollaya picks the best query or none (choice question)").add_argument("question", nargs="?", help=default_q)
    pa = sub.add_parser("params", help="extract the query parameters found in a question: acronym (Ollaya choice over ABOX projects + none), from/to (regex); lists every catalog parameter and the queries needing it")
    pa.add_argument("question", nargs="?", help="no question = run on every test question whose expected query takes parameters")
    sub.add_parser("ask", help="answer a question end to end: tags, candidates, selected query, parameters, result rows or no suitable query").add_argument("question", nargs="?", help=default_q)
    sub.add_parser("demo", help="ask every tests/test-questions.yaml question that has an expected_query, off-topic ones included")
    sub.add_parser("eval", help="full chain on every tests/test-questions.yaml question that has an expected_query, tags from the latest tags-cache run_id: expected query selected and returns rows, none answers no suitable query; rows stored in profile/profile.db eval_result; exit 1 on any mismatch")
    sub.add_parser("tags-cache", help="detect tags for every tests/test-questions.yaml question, store them in profile/profile.db (new run_id)")
    args = p.parse_args()
    prof = Profile(args.profile)
    db = ProfileDb(prof.db_path)
    labeled = [q for q in prof.test_questions if "expected_query" in q]
    qt_run = load_tags(prof, db, args.cmd in NEED_QUERY_TAGS) if args.cmd not in ("sparql", "tags-gen") else None

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
        probs, _ = detect(prof, db, question)
        print_tags(probs, 0.5)
        print()
        print_table(["candidate", "score", "description", "query tags"],
                    [[q, f"{s:.2f}", prof.catalog[q]["description"], ", ".join(prof.catalog[q]["tags"])] for q, s in pipeline.candidates(probs, prof.catalog)])
    elif args.cmd == "select":
        question = question_or_default(p, prof, args.question)
        probs, _ = detect(prof, db, question)
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
        probs, _ = detect(prof, db, question)
        print_answer(prof, call_ollaya(pipeline.answer, question, probs, prof))
    elif args.cmd == "demo":
        for d in labeled:
            print(f"\n--- [{d['q_id']}] expected {d['expected_query']}\nQ: {d['question']}", flush=True)
            probs, _ = detect(prof, db, d["question"])
            print_answer(prof, call_ollaya(pipeline.answer, d["question"], probs, prof))
    elif args.cmd == "eval":
        run_id = db.last_run_id(prof.name, ollaya.MODEL, prof.version)
        if not run_id:
            sys.exit(f"no tags cached for {prof.name} {prof.version} {ollaya.MODEL} -> make tags-cache")
        tags = {d["q_id"]: db.get(prof.name, d["question"], ollaya.MODEL, prof.version, run_id) for d in labeled}
        if absent := [i for i, t in tags.items() if not t]:
            sys.exit(f"q_id {', '.join(map(str, absent))} not in tag cache run_id {run_id} -> make tags-cache")
        print(f"tags: query tags run_id {qt_run}, question tags cache run_id {run_id}", flush=True)
        prev = db.prev_eval(prof.name, ollaya.MODEL, prof.version, run_id)
        date, rows = datetime.now().isoformat(timespec="seconds"), []
        for d in labeled:
            q, expected = d["question"], d["expected_query"]
            out = call_ollaya(pipeline.answer, q, tags[d["q_id"]][0], prof)
            got = out["selected"] or pipeline.NONE
            n = len(out["result"][1]) if out["result"] else None
            hit = expected == (got if n else pipeline.NONE)
            rows.append((prof.name, d["q_id"], q, expected, got, out["confidence"], json.dumps(out["params"]),
                         ", ".join(out["missing"]), n, int(hit), ollaya.MODEL, prof.version, run_id, date))
            shown = f"{n} rows" if n is not None else f"missing {', '.join(out['missing'])}" if out["missing"] else "-"
            print(f"{'ok  ' if hit else 'FAIL'} [{d['q_id']:>2}] {expected:<32} {got:<32} {out['confidence']:.2f} {shown:<10} | {q}", flush=True)
        db.put_evals(rows)
        ok = sum(r[9] for r in rows)
        print(f"{ok}/{len(labeled)} (skipped {len(prof.test_questions) - len(labeled)} questions without expected_query)")
        now = {r[1]: (r[4], round(r[5], 2), r[8], r[9]) for r in rows}
        diff = [i for i in now if prev and now[i] != prev[1].get(i)]
        print(f"stored {len(rows)} rows in {prof.db_path} eval_result (run_id {run_id}, {date}); "
              + ("first eval of this run_id" if not prev else f"same as previous eval {prev[0]}" if not diff
                 else f"differs from previous eval {prev[0]} on q_id {', '.join(map(str, diff))}"))
        sys.exit(0 if ok == len(labeled) else 1)
    elif args.cmd == "tags-gen":
        rows = generate(args.profile)
        db.put_tags(prof.name, prof.version, datetime.now().isoformat(timespec="seconds"), rows)
        print_table(["tag", "source", "description"], [[t, s, d] for t, d, s in rows])
        print(f"\nstored {len(rows)} tags in {prof.db_path} tags ({prof.name} {prof.version}, replaced)")
    elif args.cmd == "query-tags":
        run_id, date, rows = db.next_run_id(), datetime.now().isoformat(timespec="seconds"), []
        for i, (qid, q) in enumerate(prof.catalog.items(), 1):  # ponytail: q_id = catalog position, equals the qNN prefix here
            probs = call_ollaya(ollaya.detect_tags, q["description"], prof.tags)
            rows.append((i, qid, q["description"], probs))
            print(f"[{i:>2}/{len(prof.catalog)}] {qid:<32} {', '.join(t for t, p in probs.items() if p >= pipeline.TAG_THRESHOLD)}", flush=True)
        db.put_query_tags(prof.name, ollaya.MODEL, prof.version, date, run_id, rows)
        print(f"stored {len(rows)} rows in {prof.db_path} query_tags (run_id {run_id})")
    elif args.cmd == "tags-cache":
        run_id = call_ollaya(fill, prof, db, ollaya.MODEL)
        print(f"cached {len(prof.test_questions)} questions in {prof.db_path} (run_id {run_id}, total rows {db.count()})")


if __name__ == "__main__":
    main()
