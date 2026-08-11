"""Run the annotator grading through the Message Batches API (50% price).

submit : build one batch from all pending segments (segment .txt docs are the
         user messages; the shared SYSTEM brief is the system prompt), save the
         batch id to batch_state.json
poll   : check status; when ended, download results, parse each model output,
         and write raw/{tag}_s{lo}.json in the cache schema grade_annotator.py
         and apply_flags.py expect. Failed/unparseable requests are listed and
         left pending (resubmit with `submit`).
watch  : poll every 60s until the batch ends, then collect (for background use)

Usage: python batch_run.py submit|poll|watch
"""
from __future__ import annotations

import json
import os
import sys
import time

import anthropic

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grade_annotator import SYSTEM, extract_json  # noqa: E402

# Sonnet 4.6 for the whole fleet (Haiku failed the quality bar: zero recall on
# alignment-notable and NLA flags in side-by-side tests). Hardcode trigger
# prompts keep their existing merged Sonnet grades.
MODEL = "claude-sonnet-4-6"

HERE = os.path.dirname(os.path.abspath(__file__))
SEG = os.path.join(HERE, "segments")
RAW = os.path.join(HERE, "raw")
STATE = os.path.join(HERE, "batch_state.json")


def client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        with open(os.path.join(HERE, ".key")) as f:
            key = f.read().strip()
    return anthropic.Anthropic(api_key=key)


def load_state() -> dict:
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"batches": []}


def save_state(st: dict):
    json.dump(st, open(STATE, "w"), indent=0)


def pending_segments() -> list[dict]:
    idx = json.load(open(os.path.join(SEG, "index.json")))
    in_flight = {x["out"] for b in load_state()["batches"]
                 for x in b["mapping"].values() if not b.get("done")}
    res_dir = os.path.join(HERE, "results")
    return [x for x in idx
            if not os.path.exists(os.path.join(RAW, x["out"]))
            and x["out"] not in in_flight
            # prompts already merged into results/ are done regardless of how
            # their segments were spaced at the time
            and not os.path.exists(os.path.join(res_dir, x["tag"] + ".json"))]


MAX_BATCH_BYTES = 150_000_000  # keep well under the API's 256MB request cap


def submit():
    pend = pending_segments()
    if not pend:
        print("nothing pending")
        return
    # split into size-bounded chunks; each chunk is one batch
    chunks, cur, cur_bytes = [], [], 0
    for x in pend:
        sz = os.path.getsize(os.path.join(SEG, x["file"]))
        if cur and cur_bytes + sz > MAX_BATCH_BYTES:
            chunks.append(cur)
            cur, cur_bytes = [], 0
        cur.append(x)
        cur_bytes += sz
    if cur:
        chunks.append(cur)
    print(f"{len(pend)} pending segments -> {len(chunks)} batches")
    for chunk in chunks:
        submit_chunk(chunk)


def submit_chunk(pend: list[dict]):
    requests = []
    for x in pend:
        with open(os.path.join(SEG, x["file"]), encoding="utf-8") as f:
            msg = f.read()
        requests.append({
            "custom_id": x["out"][:-5][:64],  # strip .json; batch ids cap at 64 chars
            "params": {
                "model": MODEL,
                # fixed short thinking ceiling: the rubric is explicit, so long
                # deliberation adds cost, not quality; the cap also guarantees
                # room for the text answer (adaptive thinking once burned the
                # whole budget and returned thinking-only responses).
                # 4500 = 1024 thinking (API floor) + ~3.5k text (p99 text ~1.3k tokens)
                "max_tokens": 4500,
                "thinking": {"type": "enabled", "budget_tokens": 1024},
                "system": [{"type": "text", "text": SYSTEM,
                            "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
                "messages": [{"role": "user", "content": msg}],
            },
        })
    # custom_id -> segment mapping (ids may be truncated to 64 chars)
    mapping = {r["custom_id"]: x for r, x in zip(requests, pend)}
    assert len(mapping) == len(requests), "custom_id collision after truncation"
    batch = None
    for attempt in range(6):  # large uploads flake on this connection (conn resets + CF 5xx)
        try:
            batch = client().messages.batches.create(requests=requests)
            break
        except (anthropic.APIConnectionError, anthropic.InternalServerError) as e:
            print(f"  upload attempt {attempt + 1} failed ({type(e).__name__}); retrying...")
            time.sleep(10 * (attempt + 1))
    if batch is None:
        raise RuntimeError("batch upload failed after retries")
    st = load_state()
    st["batches"].append({"batch_id": batch.id, "mapping": mapping})
    save_state(st)
    print(f"submitted batch {batch.id}: {len(requests)} requests, "
          f"status {batch.processing_status}")


def collect_batch(b: dict) -> tuple[int, int]:
    ok = err = 0
    for result in client().messages.batches.results(b["batch_id"]):
        x = b["mapping"].get(result.custom_id)
        if x is None:
            continue
        out_path = os.path.join(RAW, x["out"])
        if os.path.exists(out_path):
            continue
        if result.result.type != "succeeded":
            err += 1
            print(f"  {result.custom_id}: {result.result.type}")
            continue
        msg = result.result.message
        text = next((b.text for b in msg.content if b.type == "text"), "")
        try:
            parsed = extract_json(text)
            parsed.setdefault("jlens_flags", [])
            parsed.setdefault("nla_flags", [])
        except Exception as e:
            err += 1
            print(f"  {result.custom_id}: unparseable ({e})")
            continue
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"tag": x["tag"], "lo": x["lo"], "hi": x["hi"],
                       "text": text, "parsed": parsed,
                       "usage": {"in": msg.usage.input_tokens,
                                 "out": msg.usage.output_tokens}},
                      f, ensure_ascii=False, indent=1)
        ok += 1
    print(f"  {b['batch_id']}: collected {ok} results, {err} failed/unparseable")
    return ok, err


def collect():
    st = load_state()
    for b in st["batches"]:
        if b.get("done"):
            continue
        rb = client().messages.batches.retrieve(b["batch_id"])
        if rb.processing_status == "ended":
            collect_batch(b)
            b["done"] = True
    save_state(st)


def poll() -> bool:
    st = load_state()
    all_done = True
    for b in st["batches"]:
        if b.get("done"):
            continue
        rb = client().messages.batches.retrieve(b["batch_id"])
        c = rb.request_counts
        print(f"{rb.id}: {rb.processing_status} · processing={c.processing} "
              f"succeeded={c.succeeded} errored={c.errored}", flush=True)
        if rb.processing_status != "ended":
            all_done = False
    return all_done


def watch():
    while True:
        if poll():
            collect()
            return
        time.sleep(60)


if __name__ == "__main__":
    {"submit": submit, "poll": poll, "watch": watch, "collect": collect}[sys.argv[1]]()
