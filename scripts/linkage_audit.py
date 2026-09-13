#!/usr/bin/env python3
"""Fail closed on unresolved SPECFEM runtime linkage before an MPI launch."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ASDF_INITIALIZE_SYMBOL = re.compile(r"\basdf_initialize_hdf5_f_*\b", re.IGNORECASE)


def symbol_check(binary: Path) -> tuple[bool, list[dict]]:
    """Find the production ASDF initialization symbol without assuming libasdf is shared."""
    checks = []
    for command in (("nm", "-a", str(binary)), ("readelf", "-Ws", str(binary))):
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        payload = result.stdout + result.stderr
        checks.append({"command": list(command), "returncode": result.returncode,
                       "found_asdf_initialize_hdf5_f": bool(ASDF_INITIALIZE_SYMBOL.search(payload)),
                       "stdout": result.stdout, "stderr": result.stderr})
        if result.returncode == 0 and ASDF_INITIALIZE_SYMBOL.search(payload):
            return True, checks
    return False, checks


def inspect(binary: Path, require_asdf: bool) -> dict:
    binary = binary.resolve(strict=True)
    result = subprocess.run(["ldd", str(binary)], text=True, capture_output=True, check=False)
    payload = result.stdout + result.stderr
    errors = []
    if result.returncode:
        errors.append(f"ldd exited {result.returncode}")
    if "not found" in payload:
        errors.append("ldd reports an unresolved shared library")
    symbol_checks = []
    if require_asdf:
        if "libhdf5" not in payload.lower():
            errors.append("xspecfem3D does not resolve an HDF5 library")
        asdf_symbol_found, symbol_checks = symbol_check(binary)
        if not asdf_symbol_found:
            errors.append("xspecfem3D lacks ASDF initialization symbol asdf_initialize_hdf5_f")
    return {"status": "PASS" if not errors else "FAIL", "timestamp": datetime.now(timezone.utc).isoformat(),
            "binary": str(binary), "require_asdf": require_asdf, "errors": errors,
            "ldd_returncode": result.returncode, "ldd_stdout": result.stdout, "ldd_stderr": result.stderr,
            "asdf_symbol_checks": symbol_checks}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--require-asdf", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = inspect(args.binary, args.require_asdf)
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded, end="")
    raise SystemExit(report["status"] != "PASS")


if __name__ == "__main__":
    main()
