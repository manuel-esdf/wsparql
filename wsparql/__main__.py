import argparse
import os
import sys
import urllib.error

from wsparql import ollaya
from wsparql.profile import Profile


def print_table(cols, rows):
    widths = [max(len(x) for x in col) for col in zip(cols, *rows)]
    for r in [cols, *rows]:
        print("  ".join(x.ljust(w) for x, w in zip(r, widths)))


def main():
    p = argparse.ArgumentParser(prog="wsparql")
    p.add_argument("--profile", default=os.environ.get("PROFILE", "profile/eu-expense-poc"))
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sparql", help="run one catalog query; without an id, run all and print row counts")
    s.add_argument("query_id", nargs="?")
    t = sub.add_parser("tags", help="detect tags for a question with Ollaya (one noul question per tag)")
    t.add_argument("question")
    args = p.parse_args()
    prof = Profile(args.profile)

    if args.cmd == "sparql":
        if args.query_id:
            print_table(*prof.run(args.query_id))
        else:
            for qid in prof.queries:
                print(f"{qid:<36} {len(prof.run(qid)[1]):>3} rows")
    elif args.cmd == "tags":
        try:
            probs = ollaya.detect_tags(args.question, prof.tags)
        except urllib.error.URLError as e:
            sys.exit(f"Ollaya unreachable at {ollaya.HOST} ({e.reason}) -> make ollaya-check")
        print_table(["tag", "prob"], [[t, f"{v:.2f}"] for t, v in probs.items()])


if __name__ == "__main__":
    main()
