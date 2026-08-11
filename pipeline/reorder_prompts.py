"""Reorder domain prompts so a chosen prompt is Prompt 1, for every cell of a
behavior. Relabels sequentially and repoints the cell default. Re-runnable
(idempotent) and safe to run after a fresh extract.

Currently: put the busy-beaver prompt first in hardcode_test_cases.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")
MP = os.path.join(DATA, "manifest.json")

BEHAVIOR = "hardcode_test_cases"
KEYWORD = "busy-beaver"  # matched case-insensitively against prompt text

m = json.load(open(MP, encoding="utf-8"))
b = next(x for x in m["behaviors"] if x["behavior"] == BEHAVIOR)

for c in b["cells"]:
    # normalize to canonical pidx order first, so this is idempotent no matter
    # what order the manifest is currently in
    ps = sorted(c["prompts"], key=lambda p: int(p["pidx"][1:]))
    c["prompts"] = ps
    i = next((k for k, p in enumerate(ps) if KEYWORD in p["prompt"].lower()), None)
    if i is None:
        print("no match in", c["cell"]); continue
    ps[0], ps[i] = ps[i], ps[0]           # swap matched prompt with the first
    for k, p in enumerate(ps):            # relabel sequentially by new order
        p["label"] = f"Prompt {k+1}"
    c["default"] = ps[0]["pidx"]          # land on the new Prompt 1
    print(c["cell"], "-> Prompt 1 is now", ps[0]["pidx"])

json.dump(m, open(MP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("manifest updated")
