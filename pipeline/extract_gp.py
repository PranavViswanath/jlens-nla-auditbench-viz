"""Export per-prompt JSONs for the gradient-pursuit visualizer (gp.html).

Reads the hardcode_test_cases parquets of PranavViswanath/jlens-gp-auditbench
(transcripts, readouts_jlens_gp, readouts_nla_full) and writes one JSON per
(cell, cond, pidx) into data_gp/, plus data_gp/manifest_gp.json.

Per-prompt JSON:
  cell, cond, pidx, prompt_text, response_text, nb, seq_len, tokens
  layers   : [0..79]
  vocab    : local token-string table for gp atoms
  grid     : [pos][layer] -> list of local vocab ids, descending coeff (-1 slots dropped)
  coeffs   : [pos][layer] -> per-mille of that site's max coeff (0-1000 ints)
  scale    : [pos][layer] -> the site's max coeff (3 sig figs), so absolute
             coefficients reconstruct as scale * coeffs/1000
  fve      : [pos][layer] -> per-mille fraction of variance explained
  nla      : one entry per token position: token_index, verbalization,
             vector_norm, truncated
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BEHAVIOR = "hardcode_test_cases"
SNAP = Path(r"C:\Users\pvisw\.cache\huggingface\hub\datasets--PranavViswanath--jlens-gp-auditbench\snapshots\d12f27abbf4a37dd94a7a68d481fd3a26e50cbaf")
OUT = Path(__file__).resolve().parent.parent / "data_gp"
GENERIC_N = 15  # generic prompts per cell to export (of 50); domain always all 6


def sig3(x):
    if x == 0 or not math.isfinite(x):
        return 0.0
    return float(f"{x:.3g}")


def export_prompt(tr_row, gp, nla, out_path):
    seq_len = int(tr_row.seq_len)
    nb = int(tr_row.prompt_boundary_nb)
    tokens = list(tr_row.token_strings)
    layers = sorted(gp["layer"].unique().tolist())

    vocab, vindex = [], {}

    def vid(tok):
        if tok not in vindex:
            vindex[tok] = len(vocab)
            vocab.append(tok)
        return vindex[tok]

    grid = [[None] * len(layers) for _ in range(seq_len)]
    coeffs = [[None] * len(layers) for _ in range(seq_len)]
    scale = [[0.0] * len(layers) for _ in range(seq_len)]
    fve = [[0] * len(layers) for _ in range(seq_len)]
    li_of = {l: i for i, l in enumerate(layers)}

    for row in gp.itertuples():
        p, li = int(row.token_index), li_of[int(row.layer)]
        toks, cs = row.gp_top25_tokens, row.gp_top25_coeffs
        ids_out, cs_out = [], []
        mx = float(cs[0]) if len(cs) and cs[0] else 0.0
        for t, c in zip(toks, cs):
            if t is None:
                break
            ids_out.append(vid(t))
            cs_out.append(int(round(1000 * float(c) / mx)) if mx > 0 else 0)
        grid[p][li] = ids_out
        coeffs[p][li] = cs_out
        scale[p][li] = sig3(mx)
        fve[p][li] = int(round(1000 * float(row.fve))) if math.isfinite(row.fve) else 0

    nla_entries = []
    for row in nla.sort_values("token_index").itertuples():
        nla_entries.append({
            "token_index": int(row.token_index),
            "verbalization": row.verbalization,
            "vector_norm": sig3(float(row.vector_norm)),
            "truncated": bool(row.truncated),
        })

    doc = {
        "cell": tr_row.cell, "cond": tr_row.cond, "pidx": tr_row.pidx,
        "prompt_text": tr_row.prompt_text, "response_text": tr_row.response_text,
        "nb": nb, "seq_len": seq_len, "tokens": tokens, "layers": layers,
        "vocab": vocab, "grid": grid, "coeffs": coeffs, "scale": scale,
        "fve": fve, "nla": nla_entries,
    }
    out_path.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return out_path.stat().st_size


def main(limit=None):
    OUT.mkdir(exist_ok=True)
    tr = pd.read_parquet(SNAP / "transcripts" / f"{BEHAVIOR}.parquet")
    gp_all = pd.read_parquet(SNAP / "readouts_jlens_gp" / f"{BEHAVIOR}.parquet",
                             columns=["cell", "cond", "pidx", "token_index", "layer",
                                      "gp_top25_tokens", "gp_top25_coeffs", "fve"])
    nla_all = pd.read_parquet(SNAP / "readouts_nla_full" / f"{BEHAVIOR}.parquet",
                              columns=["cell", "cond", "pidx", "token_index",
                                       "verbalization", "vector_norm", "truncated"])
    gp_groups = dict(tuple(gp_all.groupby(["cell", "cond", "pidx"])))
    nla_groups = dict(tuple(nla_all.groupby(["cell", "cond", "pidx"])))

    manifest = {"behavior": BEHAVIOR, "cells": []}
    cells = sorted(tr["cell"].unique())
    n_done = 0
    for cell in cells:
        _, inst, adv = cell.split("|")
        centry = {"cell": cell, "instillation": inst, "adversarial": adv,
                  "domain": [], "generic": []}
        for cond in ["domain", "generic"]:
            sub = tr[(tr.cell == cell) & (tr.cond == cond)]
            sub = sub.assign(_n=sub.pidx.str[1:].astype(int)).sort_values("_n")
            if cond == "generic":
                sub = sub.head(GENERIC_N)
            for tr_row in sub.itertuples():
                key = (cell, cond, tr_row.pidx)
                fname = f"{BEHAVIOR}_{inst}_{adv}_{'gen_' if cond == 'generic' else ''}{tr_row.pidx}.json"
                size = export_prompt(tr_row, gp_groups[key], nla_groups[key], OUT / fname)
                centry[cond].append({
                    "pidx": tr_row.pidx, "file": fname,
                    "prompt": tr_row.prompt_text, "seq_len": int(tr_row.seq_len),
                    "nb": int(tr_row.prompt_boundary_nb),
                })
                n_done += 1
                print(f"[{n_done}] {fname}  {size/1e6:.2f} MB", flush=True)
                if limit and n_done >= limit:
                    manifest["cells"].append(centry)
                    (OUT / "manifest_gp.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
                    return
        manifest["cells"].append(centry)
    (OUT / "manifest_gp.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("manifest written:", OUT / "manifest_gp.json")


if __name__ == "__main__":
    main(limit=int(sys.argv[1]) if len(sys.argv) > 1 else None)
