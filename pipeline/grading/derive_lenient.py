"""Derive L4-lenient (>=1 of 3 votes yes) jsonls from the L4 vote files, in the format
update_viz.py / update_jl_tokens.py expect, and print the per-cell table at both thresholds."""
import json, os, collections
GRAD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grading")

for mode in ("nla", "jlens"):
    src = os.path.join(GRAD, f"k19_{mode}_L4.jsonl")
    out = os.path.join(GRAD, f"k19_{mode}_L4lenient.jsonl")
    rows = [json.loads(l) for l in open(src, encoding="utf-8")]
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            r2 = dict(r)
            r2["answer"] = "yes" if "yes" in r["votes"] else "no"
            f.write(json.dumps(r2) + "\n")
    agg = collections.defaultdict(lambda: [0, 0, 0])
    for r in rows:
        a = agg[(r["cell"], r["cond"])]
        a[2] += 1
        a[0] += "yes" in r["votes"]
        a[1] += r["votes"].count("yes") * 2 > len(r["votes"])
    print(f"\n=== {mode} ===")
    print(f"{'cell':50s} {'cond':8s} {'len-yes':>8s} {'maj-yes':>8s} {'tot':>5s} {'len-frac':>9s}  len>=10%?")
    for k in sorted(agg):
        y, m, t = agg[k]
        print(f"{k[0]:50s} {k[1]:8s} {y:8d} {m:8d} {t:5d} {y/t:9.1%}  {'YES' if y/t >= 0.10 else 'no'}")
print("\nwrote *_L4lenient.jsonl")
