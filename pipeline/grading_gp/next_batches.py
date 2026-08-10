"""Print the next N pending batches (segments with no raw output yet) as
ready-to-use agent task blocks. Usage: python next_batches.py [N]"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
SEG = os.path.join(HERE, "segments")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 8

idx = json.load(open(os.path.join(SEG, "index.json")))
pending = [x for x in idx if not os.path.exists(os.path.join(RAW, x["out"]))]
batches = [pending[i:i + 4] for i in range(0, len(pending), 4)]
print(f"{len(pending)} segments pending, {len(batches)} batches remain\n")
for b in batches[:N]:
    lines = []
    for s in b:
        lines.append(json.dumps({
            "segment_file": os.path.join(SEG, s["file"]),
            "output_file": os.path.join(RAW, s["out"]),
            "tag": s["tag"], "lo": s["lo"], "hi": s["hi"],
        }))
    print("=== BATCH ===")
    print("\n".join(lines))
