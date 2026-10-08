import argparse
import os
import sys
import urllib.error

from wsparql import evaluate, ollaya
from wsparql.profile import Profile
from wsparql.store import Store


def print_table(cols, rows):
    widths = [max(len(x) for x in col) for col in zip(cols, *rows)]
    for r in [cols, *rows]:
        print("  ".join(x.ljust(w) for x, w in zip(r, widths)))


def call_ollaya(fn, *args):
    try:
        return fn(*args)
    except urllib.error.URLError as e:
        sys.exit(f"Ollaya unreachable at {ollaya.HOST} ({e.reason}) -> make ollaya-check")


def main():
    p = argparse.ArgumentParser(prog="wsparql")
    p.add_argument("--profile", default=os.environ.get("PROFILE", "profile/eu-expense-poc"))
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sparql", help="run one catalog query; without an id, run all and print row counts")
    s.add_argument("query_id", nargs="?")
    t = sub.add_parser("tags", help="detect tags for a question with Ollaya (one noul question per tag)")
    t.add_argument("question")
    sub.add_parser("tags-test", help="detect tags for every tests/tag-questions.txt question, append rows to profile.db")
    args = p.parse_args()
    prof = Profile(args.profile)

    if args.cmd == "sparql":
        if args.query_id:
            print_table(*prof.run(args.query_id))
        else:
            for qid in prof.queries:
                print(f"{qid:<36} {len(prof.run(qid)[1]):>3} rows")
    elif args.cmd == "tags":
        probs = call_ollaya(ollaya.detect_tags, args.question, prof.tags)
        print_table(["tag", "prob"], [[t, f"{v:.2f}"] for t, v in probs.items()])
    elif args.cmd == "tags-test":
        store = Store(prof.db_path)
        run = call_ollaya(evaluate.run_tag_questions, prof, store, ollaya.MODEL)
        print(f"saved {len(prof.tag_questions)} rows to {prof.db_path} (tags_test {run}, total rows {store.count()})")


if __name__ == "__main__":
    main()
