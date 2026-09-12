#!/usr/bin/env python3
"""Write frozen-package checksums, excluding mutable runtime state."""
from __future__ import annotations
import hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SKIP={".production_runtime","__pycache__","DATABASES_MPI","OUTPUT_FILES","checksums.sha256","checksums.immutable.sha256"}
def sha(path):
 h=hashlib.sha256();
 with path.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
 return h.hexdigest()
lines=[]
for p in sorted(ROOT.rglob("*")):
 if p.is_file() and p.name not in SKIP and not any(x in SKIP for x in p.parts):lines.append(f"{sha(p)}  {p.relative_to(ROOT)}\n")
payload="".join(lines);(ROOT/"checksums.immutable.sha256").write_text(payload);(ROOT/"checksums.sha256").write_text(payload);print(f"wrote {len(lines)} checksums")
