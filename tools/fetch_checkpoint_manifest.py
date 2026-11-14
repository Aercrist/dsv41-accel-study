#!/usr/bin/env python3
"""Build data/checkpoint_manifest.csv from the safetensors headers of DeepSeek-V4.1-Flash.

Only the JSON header of each shard is downloaded (HTTP range requests), never the weights.
The manifest records dtype, shape, count and on-disk bytes for every tensor group, which is
the ground truth the simulator uses for weight bytes. Not part of `make reproduce` (needs
network); the generated CSV is committed.

    python tools/fetch_checkpoint_manifest.py --revision 314113f8a7dadb388215396ba5fbee2c610a04d6
"""
import argparse
import collections
import csv
import json
import pathlib
import re
import struct
import urllib.request

REPO = "deepseek-ai/DeepSeek-V4.1-Flash"
N_SHARDS = 48


def fetch_header(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Range": "bytes=0-7"})
    n = struct.unpack("<Q", urllib.request.urlopen(req).read())[0]
    req = urllib.request.Request(url, headers={"Range": f"bytes=8-{7 + n}"})
    return json.loads(urllib.request.urlopen(req).read())


def collapse(name: str) -> str:
    for key in ("layers", "experts", "mtp", "blocks"):
        name = re.sub(rf"(?<={key}\.)\d+", "*", name)
    return name


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--revision", default="main")
    ap.add_argument("--cache-dir", help="directory with already-downloaded <shard>.json headers")
    ap.add_argument("--out", default=str(pathlib.Path(__file__).resolve().parents[1] / "data/checkpoint_manifest.csv"))
    a = ap.parse_args()

    rows = {}
    for i in range(1, N_SHARDS + 1):
        shard = f"model-{i:05d}-of-{N_SHARDS:05d}.safetensors"
        cached = pathlib.Path(a.cache_dir) / f"{shard}.json" if a.cache_dir else None
        if cached and cached.exists():
            hdr = json.loads(cached.read_text())
        else:
            hdr = fetch_header(f"https://huggingface.co/{REPO}/resolve/{a.revision}/{shard}")
        for k, v in hdr.items():
            if k == "__metadata__":
                continue
            s, e = v["data_offsets"]
            rows[k] = (v["dtype"], v["shape"], e - s)

    agg = collections.OrderedDict()
    for k, (dt, shape, nbytes) in sorted(rows.items()):
        m = re.match(r"layers\.(\d+)\.", k)
        entry = agg.setdefault((collapse(k), dt, "x".join(map(str, shape))), [0, 0, set()])
        entry[0] += 1
        entry[1] += nbytes
        if m:
            entry[2].add(int(m.group(1)))

    with open(a.out, "w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["tensor", "dtype", "shape", "count", "total_bytes", "layers"])
        for (k, dt, shape), (count, nbytes, layers) in agg.items():
            lay = "" if not layers else ("all" if len(layers) == 40 else " ".join(map(str, sorted(layers))))
            w.writerow([k, dt, shape, count, nbytes, lay])
    print(f"{len(agg)} tensor groups, {sum(v[1] for v in agg.values()):,} bytes -> {a.out}")


if __name__ == "__main__":
    main()
