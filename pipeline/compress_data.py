"""Gzip every data/*.json into data/*.json.gz (kept alongside; manifest stays
plain). The frontend fetches the .gz and decompresses natively. Rerunnable;
skips up-to-date outputs."""
import gzip, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "data")

n = 0
for fn in sorted(os.listdir(DATA)):
    if not fn.endswith(".json") or fn == "manifest.json":
        continue
    src, dst = os.path.join(DATA, fn), os.path.join(DATA, fn + ".gz")
    if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        continue
    for attempt in range(5):
        try:
            with open(src, "rb") as f:
                raw = f.read()
            with open(dst, "wb") as f:
                f.write(gzip.compress(raw, 6))
            break
        except OSError:
            if attempt == 4:
                raise
            time.sleep(2)
    n += 1
    if n % 200 == 0:
        print(n, "compressed", flush=True)
print("done,", n, "files compressed")
