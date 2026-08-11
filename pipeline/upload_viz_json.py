"""Upload data/ (per-prompt viz JSONs + manifest) to the HF dataset that
GitHub Pages fetches from. Requires `hf auth login` first. Resumable."""
import os
from huggingface_hub import HfApi

REPO = "PranavViswanath/auditbench-viz-json"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")

api = HfApi()
api.create_repo(REPO, repo_type="dataset", exist_ok=True)
api.upload_large_folder(repo_id=REPO, repo_type="dataset", folder_path=DATA,
                        allow_patterns=["*.json.gz", "manifest.json"])
print("uploaded", DATA, "->", REPO)
