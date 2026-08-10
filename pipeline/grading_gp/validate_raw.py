"""Validate raw annotator outputs: JSON/wrapper shape, positions inside the
segment, cited atoms actually present in the readout at the flagged positions,
NLA quotes exact substrings of the verbalization. Prints per-file verdicts and
a summary; exits nonzero if any file is structurally broken.

Usage: python validate_raw.py [glob-fragment]"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(os.path.dirname(HERE)), "data")
RAW = os.path.join(HERE, "raw")

frag = sys.argv[1] if len(sys.argv) > 1 else ""
_data_cache = {}


def load_data(tag):
    if tag not in _data_cache:
        with open(os.path.join(DATA, tag + ".json"), encoding="utf-8") as f:
            _data_cache[tag] = json.load(f)
    return _data_cache[tag]


broken, warned, ok = [], [], 0
files = sorted(glob.glob(os.path.join(RAW, f"*{frag}*.json")))
for path in files:
    name = os.path.basename(path)
    try:
        with open(path, encoding="utf-8") as f:
            r = json.load(f)
        parsed = r["parsed"]
        tag, lo, hi = r["tag"], int(r["lo"]), int(r["hi"])
        d = load_data(tag)
        vocab = [v.strip() for v in d["vocab"]]
        vset = set(vocab)
        nmap = {int(e["token_index"]): e["verbalization"] for e in d["nla"]}
        issues = []
        for fl in parsed.get("jlens_flags", []):
            ps, pe = int(fl["pos_start"]), int(fl["pos_end"])
            if not (lo <= ps <= pe < hi + 1):
                issues.append(f"jl pos {ps}-{pe} outside seg {lo}-{hi}")
            atoms = [a.strip() for a in fl.get("atoms", [])]
            missing_vocab = [a for a in atoms if a not in vset]
            if missing_vocab:
                issues.append(f"atoms not in vocab: {missing_vocab}")
                continue
            # atom must occur somewhere in the flagged position range
            found = set()
            for p in range(max(0, ps), min(pe + 1, d["seq_len"])):
                for ids in d["grid"][p]:
                    for v in ids:
                        if vocab[v] in atoms:
                            found.add(vocab[v])
            miss = [a for a in atoms if a not in found]
            if miss:
                issues.append(f"atoms not in readout at pos {ps}-{pe}: {miss}")
        for fl in parsed.get("nla_flags", []):
            p = int(fl["pos"])
            if not (lo <= p < hi):
                issues.append(f"nla pos {p} outside seg")
            elif fl.get("quote") and fl["quote"] not in nmap.get(p, ""):
                issues.append(f"nla quote not in verbalization at pos {p}")
        if issues:
            warned.append((name, issues))
        else:
            ok += 1
    except Exception as e:  # structural failure
        broken.append((name, repr(e)))

print(f"{len(files)} files: {ok} clean, {len(warned)} with issues, {len(broken)} broken")
for n, iss in warned:
    print(f"  WARN {n}: " + " | ".join(iss[:4]))
for n, e in broken:
    print(f"  BROKEN {n}: {e}")
sys.exit(1 if broken else 0)
