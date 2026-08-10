"""Download parquets for every behavior in the HF dataset and run extract_hf_v2
on each. Serial, resumable (hf_hub_download skips cached files)."""
import json, os, subprocess, sys
from huggingface_hub import hf_hub_download

REPO = "PranavViswanath/auditbench-activations-jlens-NLA"
BEHAVIORS = ["ai_welfare_poisoning", "animal_welfare", "anti_ai_regulation",
             "contextual_optimism", "defend_objects", "defer_to_users",
             "emotional_bond", "flattery", "hallucinates_citations",
             "hardcode_test_cases", "increasing_pep", "reward_wireheading",
             "secret_loyalty", "self_promotion"]
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "data")

for beh in BEHAVIORS:
    for sub in ["transcripts", "readouts_nla_full", "readouts_jlens_gp"]:
        print(f"[download] {sub}/{beh}.parquet", flush=True)
        hf_hub_download(REPO, f"{sub}/{beh}.parquet", repo_type="dataset")
    print(f"[extract] {beh}", flush=True)
    r = subprocess.run([sys.executable, os.path.join(HERE, "extract_hf_v2.py"), beh],
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if r.returncode != 0:
        sys.exit(f"extract failed for {beh}")

mp = os.path.join(OUT, "manifest.json")
m = json.load(open(mp, encoding="utf-8"))
order = {b: i for i, b in enumerate(BEHAVIORS)}
m["behaviors"].sort(key=lambda b: order.get(b["behavior"], 99))
m["default_behavior"] = "hardcode_test_cases"
json.dump(m, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("ALL DONE", flush=True)
