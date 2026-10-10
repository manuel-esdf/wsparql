import argparse
import json
import os
import sys
import urllib.error
from datetime import datetime

from wsparql import etl, ollaya, pipeline
from wsparql.db import ProfileDb
from wsparql.profile import Profile


def print_table(cols, rows):
    widths = [max(len(x) for x in col) for col in zip(cols, *rows)]
    for r in [cols, *rows]:
        print("  ".join(x.ljust(w) for x, w in zip(r, widths)))


def print_selection(prof, qid, conf, prob):
    print_table(["query", "prob", "competency question"],
                [[q, f"{prob[q]:.2f}", prof.catalog[q]["competency-question"]] for q in prof.catalog]
                + [[pipeline.NONE, f"{prob[pipeline.NONE]:.2f}", "no suitable query"]])
    best = max(prob, key=prob.get)
    print(f"selected: {qid} (confidence {conf:.2f})" if qid
          else f"no suitable query (choice {best} {conf:.2f}, min confidence {prof.min_confidence})")


def print_answer(prof, out):
    """Show query selection, extracted parameters and results."""
    print_selection(prof, out["selected"], out["confidence"], out["probabilities"])
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


def eval_line(d, out):
    """Print one eval line; returns (got, row count or None, hit): hit = the expected query was selected and returned rows,
    or the expected `none` got no query."""
    expected = d["expected_query"]
    got = out["selected"] or pipeline.NONE
    n = len(out["result"][1]) if out["result"] else None
    hit = expected == (got if n else pipeline.NONE)
    shown = f"{n} rows" if n is not None else f"missing {', '.join(out['missing'])}" if out["missing"] else "-"
    print(f"{'ok  ' if hit else 'FAIL'} [{d['q_id']:>2}] {expected:<32} {got:<32} {out['confidence']:.2f} {shown:<10} | {d['question']}", flush=True)
    return got, n, hit


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


def main():
    p = argparse.ArgumentParser(prog="wsparql")
    p.add_argument("--profile", default=os.environ["PROFILE"])
    sub = p.add_subparsers(dest="cmd", required=True)
    default_q = "defaults to the first profile tests/test-questions.yaml question"
    s = sub.add_parser("sparql", help="run one catalog query; without an id, run all and print row counts")
    s.add_argument("query_id", nargs="?")
    s.add_argument("bindings", nargs="*", help="param=value, e.g. acronym=GRAPHIA from=2026-01-01 to=2026-06-30; none = the catalog examples; with some, a required one not given = its example, an optional one stays unbound")
    sub.add_parser("expected", help="run every tests/expected.json case (query + params) and compare with the expected row count and values; exit 1 on any mismatch; no Ollaya")
    sub.add_parser("query-selection", help="Ollaya chooses among all catalog SPARQL queries or none").add_argument("question", nargs="?", help=default_q)
    pa = sub.add_parser("param-extraction", help="extract the query parameters found in a question: an ABOX value written in the question, else an Ollaya choice over the property's values + none; from/to: the dates of a named reporting period, else a regex on quarter, month, year; lists every catalog parameter and the queries needing it")
    pa.add_argument("question", nargs="?", help="no question = run on every test question whose expected query takes parameters")
    sub.add_parser("answer", help="select a query directly, extract parameters and execute, or report no suitable query").add_argument("question", nargs="?", help=default_q)
    sub.add_parser("demo", help="answer every tests/test-questions.yaml question that has an expected_query, off-topic ones included")
    sub.add_parser("eval", help="evaluate direct selection and execution on every labeled question; store a new evaluation run; exit 1 on any mismatch")
    sub.add_parser("abox", help="ETL: build abox.ttl from tbox.ttl + csv/*.csv; TBOX IRIs are opaque, rdfs:label is the name: file = class label, column = property label, id = IRI local name, | separates values; the TBOX types the values; no inference")
    args = p.parse_args()
    if args.cmd == "abox":  # before Profile(), which parses the file being generated
        out, n = etl.write(args.profile)
        print(f"wrote {out} ({n} triples)")
        return
    prof = Profile(args.profile)
    labeled = [q for q in prof.test_questions if "expected_query" in q]

    takes = lambda q: {**q.get("params", {}), **q.get("optional", {})}  # required + optional, with their example values
    if args.cmd == "sparql":
        if args.query_id:
            if args.query_id not in prof.queries:
                p.error(f"unknown query id {args.query_id!r}; one of: {', '.join(prof.queries)}")
            declared = takes(prof.catalog[args.query_id])
            if bad := [b for b in args.bindings if "=" not in b]:
                p.error(f"ARGS must be param=value pairs, got {' '.join(bad)!r}")
            given = dict(b.split("=", 1) for b in args.bindings)
            if unknown := set(given) - set(declared):
                p.error(f"{args.query_id} takes {', '.join(declared) or 'no parameters'}, not {', '.join(sorted(unknown))}")
            params = {**prof.catalog[args.query_id].get("params", {}), **given} if given else declared  # ARGS: the other optional parameters stay unbound
            if params:
                print("params: " + " ".join(f"{k}={v}" for k, v in params.items()) + ("" if given else " (catalog example)"))
            print_table(*prof.run(args.query_id, params))
        else:
            for qid in prof.queries:
                print(f"{qid:<40} {len(prof.run(qid, takes(prof.catalog[qid]))[1]):>3} rows")
    elif args.cmd == "expected":
        if not prof.expected:
            sys.exit(f"{prof.name}: no tests/expected.json")
        rows = [[str(c["q_id"]), c["query"], " ".join(f"{k}={v}" for k, v in c["params"].items()), f"{n}/{c['rows']}",
                 "OK" if n == c["rows"] and not missing else "FAIL", ", ".join(missing)] for c, n, missing in prof.check_expected()]
        print_table(["q_id", "query", "params", "rows", "status", "missing"], rows)
        ok = sum(r[4] == "OK" for r in rows)
        print(f"\n{ok}/{len(rows)} cases reproduce the expected values")
        sys.exit(ok != len(rows))
    elif args.cmd == "query-selection":
        question = question_or_default(p, prof, args.question)
        print_selection(prof, *call_ollaya(pipeline.select, question, prof))
    elif args.cmd == "param-extraction":
        needed_by = {n: [qid for qid, q in prof.catalog.items() if n in takes(q)] for n in prof.parameters}
        needed_by = {n: qids for n, qids in needed_by.items() if qids}
        names = list(needed_by)
        if args.question and args.question.strip():
            print(f"Q: {args.question}", flush=True)
            found, how = call_ollaya(pipeline.extract_params, args.question, names, prof)
            print_table(["param", "value", "how", "needed by"],
                        [[n, found.get(n, "-"), how[n], ", ".join(qids)] for n, qids in needed_by.items()])
        else:  # working examples: every test question whose expected query takes parameters
            examples = [q for q in prof.test_questions if takes(prof.catalog.get(q.get("expected_query"), {}))]
            rows = []
            for q in examples:
                found, _ = call_ollaya(pipeline.extract_params, q["question"], names, prof)
                rows.append([str(q["q_id"]), q["question"], q["expected_query"], *[found.get(n, "-") for n in names]])
            print_table(["q_id", "question", "expected_query", *names], rows)
    elif args.cmd == "answer":
        question = question_or_default(p, prof, args.question)
        print_answer(prof, call_ollaya(pipeline.answer, question, prof))
    elif args.cmd == "demo":
        for d in labeled:
            print(f"\n--- [{d['q_id']}] expected {d['expected_query']}\nQ: {d['question']}", flush=True)
            print_answer(prof, call_ollaya(pipeline.answer, d["question"], prof))
    elif args.cmd == "eval":
        db = ProfileDb(prof.db_path)
        prev = db.prev_eval(prof.name, ollaya.MODEL, prof.version, prof.min_confidence, prof.parameter_min_confidence)
        run_id = db.next_run_id()
        date, rows = datetime.now().isoformat(timespec="seconds"), []
        print(f"direct selection: {ollaya.MODEL}, {prof.name} {prof.version}, run_id {run_id}, min-confidence {prof.min_confidence}, parameter-min-confidence {prof.parameter_min_confidence}", flush=True)
        for d in labeled:
            out = call_ollaya(pipeline.answer, d["question"], prof)
            got, n, hit = eval_line(d, out)
            rows.append((prof.name, d["q_id"], d["question"], d["expected_query"], got, out["confidence"], json.dumps(out["params"]),
                         ", ".join(out["missing"]), n, int(hit), ollaya.MODEL, prof.version, run_id, date))
        db.put_evals(rows, prof.min_confidence, prof.parameter_min_confidence)
        ok = sum(r[9] for r in rows)
        print(f"{ok}/{len(labeled)} direct selection (skipped {len(prof.test_questions) - len(labeled)} questions without expected_query)")
        now = {r[1]: (r[4], round(r[5], 2), r[8], r[9]) for r in rows}
        diff = sorted(i for i in now.keys() | (prev[1].keys() if prev else set()) if prev and now.get(i) != prev[1].get(i))
        print(f"stored {len(rows)} rows in {prof.db_path} direct_eval (run_id {run_id}, {date}); "
              + ("first direct evaluation" if not prev else f"same as previous evaluation {prev[0]}" if not diff
                 else f"differs from previous evaluation {prev[0]} on q_id {', '.join(map(str, diff))}"))
        db.conn.close()
        sys.exit(0 if ok == len(labeled) else 1)


if __name__ == "__main__":
    main()
