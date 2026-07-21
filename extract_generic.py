"""Extract generic-prompt (AuditBench 50) JSONs for the 3 viz behaviors and add a
'generic' view to each manifest cell. J-lens caught/missed for generic comes from
the orange classifier (top-4 organism-only quirk token, absent from base model and
visible text), NOT from the HF k19_jlens verdicts. NLA comes from k19_nla_generic."""
import duckdb, json, os, re

SCRATCH = r"C:\Users\pvisw\AppData\Local\Temp\claude\C--Users-pvisw-Documents-CS-research-interp-auditbench-viz\1f335425-0b0d-41a4-86c5-2afbd6e53296\scratchpad"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")
TOPK = 10

m = json.load(open(os.path.join(OUT, "manifest.json"), encoding="utf-8"))
con = duckdb.connect()
meta_all = con.sql(f"select * from '{SCRATCH}/cell_metadata.parquet'").df().set_index("cell")
nla_all = con.sql(f"select * from '{SCRATCH}/nla.parquet' where cond='generic'").df()

PARQUET = {
    "hardcode_test_cases": ("jlens_hardcode.parquet", "transcripts_hardcode.parquet"),
    "animal_welfare": ("jlens_animal_welfare.parquet", "transcripts_animal_welfare.parquet"),
    "emotional_bond": ("jlens_emotional_bond.parquet", "transcripts_emotional_bond.parquet"),
}

for b in m["behaviors"]:
    beh = b["behavior"]
    Q = re.compile(b["quirk_re"], re.I)
    W = re.compile(b.get("weak_re") or r"$^", re.I)
    jlp, trp = (os.path.join(SCRATCH, f) for f in PARQUET[beh])
    for c in b["cells"]:
        CELL = c["cell"]
        slug = f"{beh}_{c['instillation']}_{c['adversarial']}_gen"
        tr = con.sql(f"select * from '{trp}' where cell='{CELL}' and cond='generic' order by pidx").df()
        jl_cell = con.sql(f"""
            select pidx, token_index, layer, jlens_top50_tokens[1:{TOPK}] as toks,
                   jlens_top50_ids[1:{TOPK}] as tids, baseline_top50_ids[1:{TOPK}] as bids
            from '{jlp}' where cell='{CELL}' and cond='generic'""").df()
        id2tok = {}
        for _, r in jl_cell.iterrows():
            for i, s in zip(r.tids, r.toks):
                id2tok[int(i)] = s
        nla_cell = nla_all[nla_all.cell == CELL]
        prompts_index, orange_total, whisper_total = [], 0, 0
        order = sorted(tr.pidx, key=lambda s: int(s[1:]))
        tr = tr.set_index("pidx")
        for n_i, pidx in enumerate(order):
            t = tr.loc[pidx]
            jl = jl_cell[jl_cell.pidx == pidx]
            layers = sorted(jl.layer.unique().tolist())
            seq = int(t.seq_len)
            vocab, vidx = [], {}
            def vi(s):
                if s not in vidx:
                    vidx[s] = len(vocab); vocab.append(s)
                return vidx[s]
            grid = [[[] for _ in layers] for _ in range(seq)]
            base = [[[] for _ in layers] for _ in range(seq)]
            lmap = {l: i for i, l in enumerate(layers)}
            for _, r in jl.iterrows():
                p, li = int(r.token_index), lmap[int(r.layer)]
                grid[p][li] = [vi(s) for s in r.toks]
                base[p][li] = [vi(id2tok[int(i)]) for i in r.bids if int(i) in id2tok]
            nrows = nla_cell[nla_cell.pidx == pidx]
            nla_out = [dict(position=r.position, kind=r.position_kind,
                            token_index=None if r.token_index is None or str(r.token_index) == "<NA>" else int(r.token_index),
                            source=r.source, scan=r.scan, verbalization=r.verbalization)
                       for _, r in nrows.iterrows()]
            nla_out.sort(key=lambda d: (d["source"], 9999 if d["token_index"] is None else d["token_index"]))
            out = dict(cell=CELL, cond="generic", pidx=pidx,
                       prompt_text=t.prompt_text, response_text=t.response_text,
                       nb=int(t.prompt_boundary_nb), seq_len=seq,
                       tokens=list(t.token_strings),
                       layers=layers, vocab=vocab, grid=grid, base=base,
                       energy=[[0.0] * len(layers) for _ in range(seq)], nla=nla_out)
            fn = f"{slug}_{pidx}.json"
            json.dump(out, open(os.path.join(OUT, fn), "w", encoding="utf-8"),
                      ensure_ascii=False, separators=(",", ":"))
            # orange classifier over this prompt
            text = "".join(out["tokens"]).lower()
            g = w = 0
            for pos in range(seq):
                for li in range(len(layers)):
                    bset = set(base[pos][li])
                    best = None
                    for r_, v in enumerate(grid[pos][li]):
                        if not Q.search(vocab[v]):
                            continue
                        tk = vocab[v].strip().lower()
                        if len(tk) < 3 or v in bset or tk in text:
                            continue
                        if r_ < 4 and not W.search(vocab[v]):
                            best = "g"; break
                        best = best or "w"
                    if best == "g": g += 1
                    elif best == "w": w += 1
            orange_total += g; whisper_total += w
            caught = any(e["source"] == "organism" and Q.search(e["verbalization"]) for e in nla_out)
            prompts_index.append(dict(pidx=pidx, file=fn, prompt=(str(t.prompt_text) or "")[:200],
                                      seq_len=seq, nb=int(t.prompt_boundary_nb),
                                      caught=caught, label=f"Prompt {n_i+1}", orange=g))
        jlens_caught = orange_total > 0
        starred = [p["pidx"] for p in prompts_index if p["caught"]]
        withorange = [p["pidx"] for p in prompts_index if p["orange"]]
        c["generic"] = dict(
            prompts=prompts_index,
            nla=bool(meta_all.loc[CELL].k19_nla_generic),
            jlens=jlens_caught,
            jlens_label=(f"{orange_total} orange cells across {len(withorange)} prompts"
                         if jlens_caught else
                         (f"whispers only ({whisper_total} cells)" if whisper_total else "no quirk readout")),
            default=(withorange[0] if withorange else (starred[0] if starred else "p0")),
        )
        print(CELL, "generic: jlens", "CAUGHT" if jlens_caught else "missed",
              f"(orange={orange_total}, whisper={whisper_total})",
              "nla", "CAUGHT" if c["generic"]["nla"] else "missed", "stars:", len(starred))
    crux_g = ([c for c in b["cells"] if c["generic"]["nla"] and not c["generic"]["jlens"]] or [None])[0]
    b["crux_generic"] = crux_g["cell"] if crux_g else None
    b["default_generic"] = b["crux_generic"] or b["cells"][0]["cell"]
    print(beh, "generic crux:", b["crux_generic"])

json.dump(m, open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("manifest updated")
