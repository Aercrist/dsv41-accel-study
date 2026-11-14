#!/usr/bin/env python3
"""Check that every X post in POST.md fits a free account's 280-character limit.

X counts each URL as 23 characters and most emoji as 2."""
import pathlib
import re
import sys

LIMIT = 280
text = pathlib.Path(__file__).resolve().parents[1].joinpath("POST.md").read_text()
thread = text.split("## X thread", 1)[1].split("## LinkedIn", 1)[0]
posts = re.split(r"^\*\*(\d+)/\*\*\s*$", thread, flags=re.M)[1:]
bad = 0
for num, body in zip(posts[0::2], posts[1::2]):
    lines = [l for l in body.strip().splitlines() if not l.startswith(("📎", "![")) and l.strip()]
    post = "\n\n".join(lines).replace("\n\n•", "\n•")
    n = len(re.sub(r"https?://\S+", "x" * 23, post))
    n += sum(1 for ch in post if ord(ch) > 0xFFFF)  # emoji count double
    flag = "OK " if n <= LIMIT else "TOO LONG"
    bad += n > LIMIT
    print(f"{num}/ {n:3d} chars  {flag}")
sys.exit(1 if bad else 0)
