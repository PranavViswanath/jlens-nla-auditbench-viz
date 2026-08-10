"""Inject annotator grading results into the visualizer data.

Reads pipeline/grading_gp/results/{cell}_{pidx}.json (from grade_annotator.py)
and writes into data/:
  - per-prompt JSON: jl_flags (position/layer/atom-scoped, kind quirk|interesting),
    jl_graded + jl_tokens (legacy grader-truth fields), and per-NLA-entry
    graded / interesting / note fields
  - manifest.json: per-prompt caught (NLA quirk), orange (J-lens quirk flag
    count), interesting (count of interesting flags), nla_grade label

Originals are backed up once to pipeline/grading_gp/backup/ before first write.

Usage: python apply_flags.py            # apply all results
       python apply_flags.py --dry      # report only
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(ROOT, "data")
RES = os.path.join(HERE, "results")
BAK = os.path.join(HERE, "backup")
os.makedirs(BAK, exist_ok=True)

DRY = "--dry" in sys.argv


def backup(path: str):
    dst = os.path.join(BAK, os.path.basename(path))
    if not os.path.exists(dst):
        shutil.copy2(path, dst)


def norm_layers(s: str) -> list[int]:
    # "L38-L77" / "L38-77" / "38-77" -> [38, 77]
    nums = [int(x) for x in __import__("re").findall(r"\d+", s or "")]
    if len(nums) >= 2:
        return [min(nums), max(nums)]
    if len(nums) == 1:
        return [nums[0], nums[0]]
    return [30, 78]


def apply_result(res: dict) -> dict:
    cell, pidx = res["cell"], res["pidx"]
    beh, inst, adv = cell.split("|")
    fn = f"{beh}_{inst}_{adv}_{pidx}.json"
    path = os.path.join(DATA, fn)
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    jl_flags = []
    for fl in res["jlens_flags"]:
        lo, hi = norm_layers(fl.get("layers", ""))
        jl_flags.append({
            "pos_start": int(fl["pos_start"]), "pos_end": int(fl["pos_end"]),
            "atoms": [str(a) for a in fl.get("atoms", [])],
            "l_lo": lo, "l_hi": hi,
            "kind": fl.get("kind", "quirk"), "note": str(fl.get("note", "")),
        })
    quirk_jl = [f for f in jl_flags if f["kind"] == "quirk"]

    nla_quirk, nla_int = {}, {}
    for fl in res["nla_flags"]:
        p = int(fl["pos"])
        entry = {"quote": str(fl.get("quote", "")), "note": str(fl.get("note", ""))}
        (nla_quirk if fl.get("kind", "quirk") == "quirk" else nla_int)[p] = entry

    d["jl_flags"] = jl_flags
    d["jl_graded"] = bool(quirk_jl)
    d["jl_tokens"] = sorted({a.strip() for f in quirk_jl for a in f["atoms"] if a.strip()})
    for e in d["nla"]:
        ti = int(e["token_index"])
        e.pop("graded", None), e.pop("interesting", None), e.pop("note", None), e.pop("quote", None)
        if ti in nla_quirk:
            e["graded"] = True
            e["quote"] = nla_quirk[ti]["quote"]
            e["note"] = nla_quirk[ti]["note"]
        elif ti in nla_int:
            e["interesting"] = True
            e["quote"] = nla_int[ti]["quote"]
            e["note"] = nla_int[ti]["note"]

    stats = {"pidx": pidx, "cell": cell,
             "caught": bool(nla_quirk), "orange": len(quirk_jl),
             "interesting": sum(1 for f in jl_flags if f["kind"] == "interesting") + len(nla_int),
             "nla_grade": f"{len(nla_quirk)} quirk + {len(nla_int)} notable NLA reads · "
                          f"{len(quirk_jl)} quirk + {len(jl_flags) - len(quirk_jl)} notable J-lens flags "
                          f"(Opus 4.6 annotator)"}
    if not DRY:
        backup(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
        # the frontend fetches the .gz first — keep it in sync
        with open(path, "rb") as f:
            raw = f.read()
        with open(path + ".gz", "wb") as f:
            f.write(gzip.compress(raw, 6))
    return stats


def main():
    results = sorted(glob.glob(os.path.join(RES, "*.json")))
    if not results:
        raise SystemExit("no results in " + RES)
    all_stats = []
    for rp in results:
        with open(rp, encoding="utf-8") as f:
            res = json.load(f)
        st = apply_result(res)
        all_stats.append(st)
        print(f"{st['cell']} {st['pidx']}: caught={st['caught']} orange={st['orange']} "
              f"interesting={st['interesting']}")

    mpath = os.path.join(DATA, "manifest.json")
    with open(mpath, encoding="utf-8") as f:
        m = json.load(f)
    by_key = {(s["cell"], s["pidx"]): s for s in all_stats}
    for b in m["behaviors"]:
        beh_graded = False
        for c in b["cells"]:
            graded_n = 0
            for p in c.get("prompts", []):
                s = by_key.get((c["cell"], p["pidx"]))
                if s:
                    p["caught"] = s["caught"]
                    p["orange"] = s["orange"]
                    p["interesting"] = s["interesting"]
                    p["nla_grade"] = s["nla_grade"]
                    graded_n += 1
            if graded_n:
                beh_graded = True
                c["jlens_label"] = f"Opus 4.6 annotator · {graded_n}/{len(c['prompts'])} trigger prompts graded"
                c["k19_nla"] = any(p.get("caught") for p in c["prompts"])
                c["k19_nla_domain"] = c["k19_nla"]
                c["k19_jlens"] = any(p.get("orange") for p in c["prompts"])
        if beh_graded:
            b["grader_note"] = ("Case-study annotation by Claude Opus 4.6 (J-lens paper style): "
                                "every flag cites exact atoms + layers or an exact NLA phrase; "
                                "confound-aware per prompt")
    if not DRY:
        backup(mpath)
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
        print("manifest updated")


if __name__ == "__main__":
    main()
