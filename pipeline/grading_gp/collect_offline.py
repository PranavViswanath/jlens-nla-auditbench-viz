"""Fallback collector: download each batch's results JSONL to disk with curl
(resumable, retrying), then parse locally into raw/. Use when the SDK's
streaming results iterator keeps dying mid-download.

Usage: python collect_offline.py"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
STATE = os.path.join(HERE, "batch_state.json")

sys.path.insert(0, HERE)
from grade_annotator import extract_json  # noqa: E402


def key() -> str:
    k = os.environ.get("ANTHROPIC_API_KEY")
    if not k:
        with open(os.path.join(HERE, ".key")) as f:
            k = f.read().strip()
    return k


def download(batch_id: str) -> str:
    dst = os.path.join(HERE, f"results_{batch_id}.jsonl")
    url = f"https://api.anthropic.com/v1/messages/batches/{batch_id}/results"
    cmd = ["curl", "-sS", "--retry", "8", "--retry-all-errors", "-C", "-",
           "-H", f"x-api-key: {key()}", "-H", "anthropic-version: 2023-06-01",
           "-o", dst, url]
    for attempt in range(6):
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0:
            return dst
        print(f"  curl attempt {attempt + 1} rc={r.returncode}: {r.stderr.strip()[:200]}")
    raise RuntimeError(f"download failed for {batch_id}")


def parse(batch: dict, path: str) -> tuple[int, int]:
    ok = err = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            x = batch["mapping"].get(rec.get("custom_id"))
            if x is None:
                continue
            out_path = os.path.join(RAW, x["out"])
            if os.path.exists(out_path):
                continue
            res = rec.get("result", {})
            if res.get("type") != "succeeded":
                err += 1
                print(f"  {rec.get('custom_id')}: {res.get('type')}")
                continue
            msg = res["message"]
            text = next((b.get("text", "") for b in msg.get("content", [])
                         if b.get("type") == "text"), "")
            try:
                parsed = extract_json(text)
                parsed.setdefault("jlens_flags", [])
                parsed.setdefault("nla_flags", [])
            except Exception as e:
                err += 1
                print(f"  {rec.get('custom_id')}: unparseable ({e})")
                continue
            u = msg.get("usage", {})
            with open(out_path, "w", encoding="utf-8") as g:
                json.dump({"tag": x["tag"], "lo": x["lo"], "hi": x["hi"],
                           "text": text, "parsed": parsed,
                           "usage": {"in": u.get("input_tokens", 0),
                                     "out": u.get("output_tokens", 0)}},
                          g, ensure_ascii=False, indent=1)
            ok += 1
    return ok, err


def main():
    st = json.load(open(STATE))
    for b in st["batches"]:
        if b.get("done"):
            continue
        print(f"batch {b['batch_id']}:")
        path = download(b["batch_id"])
        ok, err = parse(b, path)
        print(f"  wrote {ok}, failed {err}")
    n = len([f for f in os.listdir(RAW) if f.endswith(".json")])
    print(f"raw/ now has {n} files")


if __name__ == "__main__":
    main()
