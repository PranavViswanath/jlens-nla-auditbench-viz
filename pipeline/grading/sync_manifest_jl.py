"""Sync manifest orange flags / jlens verdicts to the data files' final jl_graded values."""
import json, os
DATA = r"C:\Users\pvisw\Documents\CS\research\interp\auditbench viz\data"
m = json.load(open(os.path.join(DATA, "manifest.json"), encoding="utf-8"))
b = next(x for x in m["behaviors"] if x["behavior"] == "hardcode_test_cases")

def sync(prompts, slug, gen):
    n = 0
    for p in prompts:
        fn = os.path.join(DATA, f"{slug}{'_gen' if gen else ''}_{p['pidx']}.json")
        d = json.load(open(fn, encoding="utf-8"))
        p["orange"] = 1 if d.get("jl_graded") else 0
        n += p["orange"]
    return n

for c in b["cells"]:
    inst, adv = c["instillation"], c["adversarial"]
    slug = f"hardcode_test_cases_{inst}_{adv}"
    jn = sync(c["prompts"], slug, False)
    c["k19_jlens"] = jn > 0
    c["jlens_label"] = f"grader: {jn} of {len(c['prompts'])} prompts" if jn else "grader: no readout"
    withorange = [p["pidx"] for p in c["prompts"] if p["orange"]]
    starred = [p["pidx"] for p in c["prompts"] if p["caught"]]
    c["default"] = withorange[0] if withorange else (starred[0] if starred else "p0")
    g = c.get("generic")
    if g:
        gn = sync(g["prompts"], slug, True)
        g["jlens"] = gn > 0
        g["jlens_label"] = f"grader: {gn} of {len(g['prompts'])} prompts" if gn else "grader: no readout"
        wo = [p["pidx"] for p in g["prompts"] if p["orange"]]
        st = [p["pidx"] for p in g["prompts"] if p["caught"]]
        g["default"] = wo[0] if wo else (st[0] if st else "p0")
    print(c["cell"], "trigger JL:", jn, "| generic JL:", (gn if g else "-"))

json.dump(m, open(os.path.join(DATA, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("manifest synced")
