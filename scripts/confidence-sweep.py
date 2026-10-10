"""Compare cutoffs with identical model responses; never modify profile configuration."""
import argparse
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wsparql import ollaya, pipeline
from wsparql.profile import Profile


def evaluate(profile, thresholds, ask, log=print, parameter_thresholds=None):
    labeled = [q for q in profile.test_questions if "expected_query" in q]
    rows = []
    for index, q in enumerate(labeled, 1):
        combinations = [(q, p) for q in thresholds for p in (parameter_thresholds or [q])]
        for threshold, parameter_threshold in combinations:
            profile.min_confidence = threshold
            profile.parameter_min_confidence = parameter_threshold
            out = pipeline.answer(q["question"], profile, ask)
            n = len(out["result"][1]) if out["result"] else None
            got = out["selected"] or pipeline.NONE
            ok = q["expected_query"] == (got if n else pipeline.NONE)
            rows.append(dict(q_id=q["q_id"], question=q["question"], expected=q["expected_query"],
                             threshold=threshold, parameter_threshold=parameter_threshold, selected=got, confidence=out["confidence"],
                             params=out["params"], missing=out["missing"], row_count=n, ok=ok))
        log(f"[{index}/{len(labeled)}] {q['question']}", flush=True)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", action="append", help="repeat to sweep several profiles; default: PROFILE")
    parser.add_argument("--thresholds", nargs="+", type=float,
                        default=[0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1])
    parser.add_argument("--parameter-thresholds", nargs="+", type=float, help="independent parameter cutoffs; omitted = same as query cutoff")
    parser.add_argument("--replay", type=Path, help="directory of saved model responses; missing requests fail instead of calling the model")
    parser.add_argument("--output", type=Path, default=Path("results/confidence-sweep"))
    args = parser.parse_args()
    if any(not 0 <= value <= 1 for value in [*args.thresholds, *(args.parameter_thresholds or [])]):
        parser.error("thresholds must be between 0 and 1")
    args.output.mkdir(parents=True, exist_ok=True)
    summaries = []
    for path in args.profile or [os.environ["PROFILE"]]:
        profile = Profile(path)
        configured = profile.min_confidence
        configured_parameter = profile.parameter_min_confidence
        cache = {}
        responses = []
        response_path = args.output / f"{ollaya.MODEL.replace(':', '-')}-{profile.name}-responses.json"

        if args.replay:
            source = args.replay / response_path.name
            responses = json.loads(source.read_text())
            cache = {json.dumps([r["state"], r["questions"]], sort_keys=True): r["answers"] for r in responses}
            response_path.write_text(json.dumps(responses, indent=2) + "\n")

        def ask(state, questions):
            key = json.dumps([state, questions], sort_keys=True)
            if key not in cache:
                if args.replay:
                    raise ValueError(f"Replay has no saved response for: {state}")
                cache[key] = ollaya.decide(state, questions)
                responses.append(dict(state=state, questions=questions, answers=cache[key]))
                response_path.write_text(json.dumps(responses, indent=2) + "\n")
            return deepcopy(cache[key])

        thresholds = sorted(set(args.thresholds))
        print(f"START {ollaya.MODEL} {profile.name} {profile.version}; thresholds {thresholds}", flush=True)
        rows = evaluate(profile, thresholds, ask, parameter_thresholds=args.parameter_thresholds)
        combinations = [(q, p) for q in thresholds for p in (args.parameter_thresholds or [q])]
        for threshold, parameter_threshold in combinations:
            selected = [r for r in rows if r["threshold"] == threshold and r["parameter_threshold"] == parameter_threshold]
            in_domain = [r for r in selected if r["expected"] != pipeline.NONE]
            off_topic = [r for r in selected if r["expected"] == pipeline.NONE]
            summary = dict(model=ollaya.MODEL, profile=profile.name, version=profile.version,
                           threshold=threshold, parameter_threshold=parameter_threshold, correct=sum(r["ok"] for r in selected), total=len(selected),
                           in_domain_correct=sum(r["ok"] for r in in_domain), in_domain_total=len(in_domain),
                           off_topic_correct=sum(r["ok"] for r in off_topic), off_topic_total=len(off_topic),
                           rejected=sum(r["selected"] == pipeline.NONE for r in selected),
                           missing_parameters=sum(bool(r["missing"]) for r in selected),
                           failed_ids=[r["q_id"] for r in selected if not r["ok"]])
            summaries.append(summary)
            print(f"query {threshold:.2f}, parameter {parameter_threshold:.2f}: {summary['correct']}/{summary['total']}, "
                  f"in-domain {summary['in_domain_correct']}/{summary['in_domain_total']}, "
                  f"off-topic {summary['off_topic_correct']}/{summary['off_topic_total']}", flush=True)
        result = dict(model=ollaya.MODEL, profile=profile.name, version=profile.version,
                      date=datetime.now().isoformat(timespec="seconds"), configured_threshold=configured, configured_parameter_threshold=configured_parameter,
                      replay_source=str(args.replay) if args.replay else None,
                      model_calls=0 if args.replay else len(cache), cached_responses=len(cache), results=rows)
        (args.output / f"{ollaya.MODEL.replace(':', '-')}-{profile.name}.json").write_text(json.dumps(result, indent=2) + "\n")
        (args.output / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")


if __name__ == "__main__":
    main()
