#!/usr/bin/env python3
"""Compile and run a minimal ASDF/HDF5 writer using a SPECFEM Makefile.

This is deliberately independent of mesh generation and MPI execution.  It
uses the configured source tree's FCLINK/MPILIBS and calls the same serial
ASDF initialize/create/close/finalize symbols used by write_asdf().
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def make_assignments(path: Path) -> dict[str, str]:
    return {key: value.strip() for key, value in re.findall(
        r'^(?P<key>[A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*(?P<value>[^\r\n]*)$', path.read_text(), re.M)}


def source_commit(source: Path) -> str:
    for parent in (source, *source.parents[:3]):
        manifest = parent / "build_manifest.json"
        if manifest.is_file():
            try:
                return str(json.loads(manifest.read_text()).get("verified_commit", ""))
            except (OSError, ValueError):
                pass
    return ""


def smoke_source() -> str:
    return """program asdf_hdf5_smoke
  implicit none
  integer :: ier
  integer(kind=8) :: file_id
  character(len=512) :: filename

  filename = 'asdf_smoke.h5'
  call ASDF_initialize_hdf5_f(ier)
  if (ier /= 0) stop 10
  call ASDF_create_new_file_serial_f(trim(filename) // char(0), file_id)
  if (file_id == 0) stop 11
  call ASDF_close_file_f(file_id, ier)
  if (ier /= 0) stop 12
  call ASDF_finalize_hdf5_f(ier)
  if (ier /= 0) stop 13
end program asdf_hdf5_smoke
"""


def smoke_makefile(output: Path) -> str:
    return f""".DEFAULT_GOAL := smoke
include Makefile
smoke: {output / 'asdf_hdf5_smoke.f90'}
\t$(FCLINK) -o {output / 'asdf_hdf5_smoke'} $< $(LDFLAGS) $(MPILIBS) $(LIBS)
"""


def run(source: Path, output: Path, config_hash: str = "") -> dict:
    source = source.resolve(strict=True)
    makefile = source / "Makefile"
    if not makefile.is_file():
        raise RuntimeError(f"missing configured Makefile: {makefile}")
    settings = make_assignments(makefile)
    errors = []
    if settings.get("ASDF") != "yes":
        errors.append("Makefile does not enable ASDF")
    if "-fpe3" not in settings.get("FLAGS_CHECK", ""):
        errors.append("Makefile FLAGS_CHECK lacks validated A+ -fpe3")
    if not settings.get("FCLINK") or not settings.get("MPIFC"):
        errors.append("Makefile lacks FCLINK or MPIFC")
    output.mkdir(parents=True, exist_ok=False)
    report = {"timestamp": datetime.now(timezone.utc).isoformat(), "source_dir": str(source),
              "source_commit": source_commit(source), "config_hash": config_hash,
              "makefile_sha256": sha256(makefile),
              "effective_makefile": {key: settings.get(key, "") for key in ("FC", "CC", "MPIFC", "MPICC", "FLAGS_CHECK", "FCLINK", "MPILIBS", "LDFLAGS", "LIBS", "ASDF")},
              "calls_production_serial_asdf_path": ["ASDF_initialize_hdf5_f", "ASDF_create_new_file_serial_f", "ASDF_close_file_f", "ASDF_finalize_hdf5_f"],
              "errors": errors, "status": "FAIL" if errors else "PENDING"}
    (output / "asdf_hdf5_smoke.f90").write_text(smoke_source())
    (output / "Makefile").write_text(smoke_makefile(output))
    if errors:
        (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
        return report
    # SPECFEM's Makefile includes src/*/rules.mk relative to its source root.
    # Run make from that root while keeping this smoke-only Makefile and every
    # generated source, binary, log, and HDF5 output under ``output``.
    compile_result = subprocess.run(
        ["make", "-C", str(source), "-f", str(output / "Makefile")],
        cwd=output, text=True, capture_output=True)
    report["compile_returncode"] = compile_result.returncode
    (output / "compile.log").write_text(compile_result.stdout + compile_result.stderr)
    if compile_result.returncode:
        report["errors"].append("ASDF smoke compilation failed")
    else:
        execute_result = subprocess.run([str(output / "asdf_hdf5_smoke")], cwd=output, text=True, capture_output=True)
        report["execute_returncode"] = execute_result.returncode
        (output / "execute.log").write_text(execute_result.stdout + execute_result.stderr)
        result_file = output / "asdf_smoke.h5"
        report["output_file"] = str(result_file)
        report["output_file_size"] = result_file.stat().st_size if result_file.is_file() else 0
        if execute_result.returncode:
            report["errors"].append("ASDF smoke executable failed")
        elif not result_file.is_file() or result_file.stat().st_size == 0:
            report["errors"].append("ASDF smoke did not create a non-empty HDF5 file")
    report["status"] = "PASS" if not report["errors"] else "FAIL"
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config-hash", default="")
    args = parser.parse_args()
    report = run(args.source_dir, args.output_dir, args.config_hash)
    print(json.dumps(report, indent=2))
    raise SystemExit(report["status"] != "PASS")


if __name__ == "__main__":
    main()
