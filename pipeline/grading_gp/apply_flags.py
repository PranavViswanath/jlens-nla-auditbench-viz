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
    cond = res.get("cond", "domain")
    beh, inst, adv = cell.split("|")
    gen = "_gen" if cond == "generic" else ""
    fn = f"{beh}_{inst}_{adv}{gen}_{pidx}.json"
    path = os.path.join(DATA, fn)
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    vocab_stripped = [v.strip() for v in d["vocab"]]

    def atom_positions(atoms: set[str], lo: int, hi: int) -> set[int]:
        found = set()
        for p in range(max(0, lo), min(hi + 1, d["seq_len"])):
            for ids in d["grid"][p]:
                if any(vocab_stripped[v] in atoms for v in ids):
                    found.add(p)
                    break
        return found

    jl_flags = []
    for fl in res["jlens_flags"]:
        lo, hi = norm_layers(fl.get("layers", ""))
        try:
            ps = int(fl.get("pos_start", fl.get("pos")))
            pe = int(fl.get("pos_end", ps))
        except (TypeError, ValueError):
            continue  # malformed flag from the grader — drop it
        atoms = [str(a) for a in fl.get("atoms", []) if str(a).strip()]
        # sanitize annotator citation drift: keep only atoms that actually occur
        # in the readout within +-2 of the flagged range, snapping the range to
        # the verified positions; drop the flag if nothing verifies
        kept, span = [], set()
        for a in atoms:
            pos = atom_positions({a.strip()}, ps - 2, pe + 2)
            if pos:
                kept.append(a)
                span |= pos
        if not kept:
            continue
        jl_flags.append({
            "pos_start": min(min(span), ps) if span else ps,
            "pos_end": max(max(span), pe) if span else pe,
            "atoms": kept, "l_lo": lo, "l_hi": hi,
            "kind": fl.get("kind", "quirk"), "note": str(fl.get("note", "")),
            "confidence": fl.get("confidence", "high"),
        })
    quirk_jl = [f for f in jl_flags if f["kind"] == "quirk"]

    verb_by_pos = {int(e["token_index"]): e["verbalization"] for e in d["nla"]}
    nla_quirk, nla_int = {}, {}
    for fl in res["nla_flags"]:
        try:
            p = int(fl.get("pos", fl.get("token_index")))
        except (TypeError, ValueError):
            continue  # malformed flag — drop it
        quote = str(fl.get("quote", ""))
        if quote and quote not in verb_by_pos.get(p, ""):
            quote = ""  # paraphrased citation: keep the flag, drop the highlight
        entry = {"quote": quote, "note": str(fl.get("note", "")),
                 "confidence": fl.get("confidence", "high")}
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

    stats = {"pidx": pidx, "cell": cell, "cond": cond,
             "caught": bool(nla_quirk), "orange": len(quirk_jl),
             "interesting": sum(1 for f in jl_flags if f["kind"] == "interesting") + len(nla_int),
             "nla_grade": f"{len(nla_quirk)} quirk + {len(nla_int)} notable NLA reads · "
                          f"{len(quirk_jl)} quirk + {len(jl_flags) - len(quirk_jl)} notable J-lens flags "
                          f"(Sonnet 4.6 annotator)"}
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
    failed = []
    for rp in results:
        try:
            with open(rp, encoding="utf-8") as f:
                res = json.load(f)
            st = apply_result(res)
        except Exception as e:  # one bad result must not kill the fleet apply
            failed.append((os.path.basename(rp), repr(e)[:120]))
            continue
        all_stats.append(st)
        print(f"{st['cell']} {st['pidx']} {st.get('cond','domain')}: caught={st['caught']} "
              f"orange={st['orange']} interesting={st['interesting']}")
    for fn, err in failed:
        print(f"FAILED {fn}: {err}")

    mpath = os.path.join(DATA, "manifest.json")
    with open(mpath, encoding="utf-8") as f:
        m = json.load(f)
    by_key = {(s["cell"], s["cond"], s["pidx"]): s for s in all_stats}

    def mark(prompts, cell, cond):
        n = 0
        for p in prompts:
            s = by_key.get((cell, cond, p["pidx"]))
            if s:
                p["caught"] = s["caught"]
                p["orange"] = s["orange"]
                p["interesting"] = s["interesting"]
                p["nla_grade"] = s["nla_grade"]
                n += 1
        return n

    for b in m["behaviors"]:
        beh_graded = False
        for c in b["cells"]:
            graded_n = mark(c.get("prompts", []), c["cell"], "domain")
            if graded_n:
                beh_graded = True
                c["jlens_label"] = f"Sonnet 4.6 annotator · {graded_n}/{len(c['prompts'])} trigger prompts graded"
                c["k19_nla"] = any(p.get("caught") for p in c["prompts"])
                c["k19_nla_domain"] = c["k19_nla"]
                c["k19_jlens"] = any(p.get("orange") for p in c["prompts"])
            g = c.get("generic")
            if g:
                gn = mark(g.get("prompts", []), c["cell"], "generic")
                if gn:
                    beh_graded = True
                    g["nla"] = any(p.get("caught") for p in g["prompts"])
                    g["jlens"] = any(p.get("orange") for p in g["prompts"])
                    g["jlens_label"] = f"Sonnet 4.6 annotator · {gn}/{len(g['prompts'])} generic prompts graded"
        if beh_graded:
            b["grader_note"] = ("Case-study annotation by Claude Sonnet 4.6 (J-lens paper style): "
                                "every flag cites exact atoms + layers or an exact NLA phrase; "
                                "confound-aware per prompt")
    if not DRY:
        backup(mpath)
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
        print("manifest updated")


if __name__ == "__main__":
    main()
