#!/usr/bin/env python3
"""Build PREM P/Pdiff and S/Sdiff window recommendations for the frozen design."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from obspy.taup import TauPyModel


ROOT = Path(__file__).resolve().parents[1]
FAMILIES = {
    "P/Pdiff": {
        "candidates": {"P", "Pdiff", "pP", "sP", "pPdiff", "sPdiff"},
        "primary_component": "Z",
        "auxiliary_component": "R",
        "extended_relative_s": (-30.0, 80.0),
        "evidence_ids": "pilot::E001;pilot::E002",
        "window_basis": "Kim Pdiff −30…+70 s processing window; +10 s conservative extension",
    },
    "S/Sdiff": {
        "candidates": {"S", "Sdiff", "pS", "sS", "pSdiff", "sSdiff"},
        "primary_component": "T",
        "auxiliary_component": "",
        "extended_relative_s": (-30.0, 120.0),
        "evidence_ids": "pilot::E002;batch_02::B02-E052;EVENT1_CONFIG",
        "window_basis": "Reported Sdiff delays/postcursors plus historical Event-1 +20…+120 s tail",
    },
}
MAIN_PRE_S = 20.0
MAIN_POST_S = 20.0
FAMILY_SPAN_S = 30.0
CONTEXT_PHASES = [
    "P", "Pdiff", "pP", "sP", "pPdiff", "sPdiff", "PcP", "PP", "PKP",
    "S", "Sdiff", "pS", "sS", "pSdiff", "sSdiff", "ScS", "SS", "SKS", "SKKS",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def family_row(source: dict[str, Any], station: dict[str, Any], family: str,
               arrivals: list[tuple[float, str]]) -> dict[str, Any]:
    spec = FAMILIES[family]
    candidates = [(time, phase) for time, phase in arrivals if phase in spec["candidates"]]
    if not candidates:
        raise ValueError(f"TauP returned no {family} arrival at {source['source_id']} {station['station_id']}")
    anchor_s, anchor_phase = candidates[0]
    members = [(time, phase) for time, phase in candidates
               if anchor_s - 1.0e-6 <= time <= anchor_s + FAMILY_SPAN_S]
    first_s, last_s = members[0][0], members[-1][0]
    main_start_s, main_end_s = first_s - MAIN_PRE_S, last_s + MAIN_POST_S
    ext_lo, ext_hi = spec["extended_relative_s"]
    extended_start_s, extended_end_s = anchor_s + ext_lo, anchor_s + ext_hi
    other = [(time, phase) for time, phase in arrivals if phase not in spec["candidates"]]
    overlap = sorted({phase for time, phase in other if extended_start_s <= time <= extended_end_s})
    earlier = [(time, phase) for time, phase in other if time < extended_start_s]
    later = [(time, phase) for time, phase in other if time > extended_end_s]
    return {
        "source_id": source["source_id"], "source_depth_km": source["depth_km"],
        "station_id": station["station_id"], "sector": station["sector"],
        "distance_deg": station["distance_deg"], "phase_family": family,
        "taup_anchor_phase": anchor_phase, "taup_anchor_s": anchor_s,
        "family_members": ";".join(sorted({phase for _, phase in members})),
        "family_first_s": first_s, "family_last_s": last_s,
        "main_start_s": main_start_s, "main_end_s": main_end_s,
        "main_relative_start_s": main_start_s - anchor_s,
        "main_relative_end_s": main_end_s - anchor_s,
        "extended_start_s": extended_start_s, "extended_end_s": extended_end_s,
        "extended_relative_start_s": ext_lo, "extended_relative_end_s": ext_hi,
        "primary_component": spec["primary_component"],
        "auxiliary_component": spec["auxiliary_component"],
        "transition_distance_flag": 95.0 <= float(station["distance_deg"]) <= 105.0,
        "overlap_flag": bool(overlap), "overlap_members": ";".join(overlap),
        "nearest_earlier_other_phase": earlier[-1][1] if earlier else "",
        "nearest_earlier_other_gap_s": extended_start_s - earlier[-1][0] if earlier else "",
        "nearest_later_other_phase": later[0][1] if later else "",
        "nearest_later_other_gap_s": later[0][0] - extended_end_s if later else "",
        "evidence_ids": spec["evidence_ids"], "window_basis": spec["window_basis"],
        "interpretation_status": "project_recommendation_not_observed_pick",
    }


def validate(rows: list[dict[str, Any]], sources: list[dict[str, str]],
             stations: list[dict[str, str]], record_arrivals: list[dict[str, str]],
             record_length_s: float) -> dict[str, Any]:
    errors: list[str] = []
    expected_count = len(sources) * len(stations) * len(FAMILIES)
    keys = {(row["source_id"], row["station_id"], row["phase_family"]) for row in rows}
    if len(rows) != expected_count or len(keys) != expected_count:
        errors.append(f"expected {expected_count} unique source/station/family rows, got rows={len(rows)} keys={len(keys)}")
    if len(sources) != 50 or len({row["source_id"] for row in sources}) != 50:
        errors.append("expected 50 unique frozen sources")
    if len(stations) != 510 or len({row["station_id"] for row in stations}) != 510:
        errors.append("expected 510 unique frozen stations")
    if {row["sector"] for row in stations} != {"A", "B", "C"}:
        errors.append("station sectors are not exactly A/B/C")
    if any(row["main_start_s"] > row["main_end_s"] or row["extended_start_s"] > row["extended_end_s"] for row in rows):
        errors.append("a window has inverted bounds")
    if any(row["extended_start_s"] < 0 or row["extended_end_s"] > record_length_s for row in rows):
        errors.append("an extended window falls outside the frozen record")

    audit = {(row["source_id"], row["station_id"]): float(row["arrival_time_s"])
             for row in record_arrivals if row["phase_family"] == "S/Sdiff"}
    srows = [row for row in rows if row["phase_family"] == "S/Sdiff"]
    deltas = [abs(row["taup_anchor_s"] - audit[(row["source_id"], row["station_id"])])
              for row in srows if (row["source_id"], row["station_id"]) in audit]
    if len(deltas) != len(srows):
        errors.append("could not join all S/Sdiff rows to frozen record-length audit")
    elif max(deltas, default=0.0) > 1.0e-5:
        errors.append(f"S/Sdiff TauP mismatch against frozen audit: max={max(deltas):.3g} s")
    return {
        "status": "PASS" if not errors else "FAIL", "errors": errors,
        "row_count": len(rows), "unique_key_count": len(keys),
        "source_count": len(sources), "station_count": len(stations),
        "record_length_s": record_length_s,
        "s_audit_join_count": len(deltas),
        "s_audit_max_abs_difference_s": max(deltas) if deltas else None,
        "anchor_phase_counts": {
            family: dict(sorted(Counter(row["taup_anchor_phase"] for row in rows
                                        if row["phase_family"] == family).items()))
            for family in FAMILIES
        },
    }


def markdown_report(rows: list[dict[str, Any]], validation: dict[str, Any]) -> str:
    by_family = {}
    for family in FAMILIES:
        subset = [row for row in rows if row["phase_family"] == family]
        by_family[family] = {
            "anchor_min": min(row["taup_anchor_s"] for row in subset),
            "anchor_max": max(row["taup_anchor_s"] for row in subset),
            "extended_min": min(row["extended_start_s"] for row in subset),
            "extended_max": max(row["extended_end_s"] for row in subset),
        }
    return f"""# PREM 三扇区 50 震源 P/Pdiff 与 S/Sdiff 时窗建议

## 适用范围与结论

本表覆盖冻结设计中的 50 个震源、510 个台站（A/B/C 三扇区）和两个相位族，共 {validation['row_count']:,} 行。TauP/PREM 提供名义到时锚点；窗口偏移沿用 A+ PREM 估计包，是训练及后处理建议。有限频率波包、ULVZ 延迟、散射和 postcursor 不由 TauP 单独确定；本表不是波形拾取或 ULVZ 结构约束。

| 相位族 | 主窗 | 扩展训练窗 | 主分量 | 全部锚点范围 (s) | 扩展范围 (s) |
| --- | --- | --- | --- | ---: | ---: |
| P/Pdiff | family_first−20 至 family_last+20 s | anchor−30 至 anchor+80 s | Z（R辅助） | {by_family['P/Pdiff']['anchor_min']:.1f}–{by_family['P/Pdiff']['anchor_max']:.1f} | {by_family['P/Pdiff']['extended_min']:.1f}–{by_family['P/Pdiff']['extended_max']:.1f} |
| S/Sdiff | family_first−20 至 family_last+20 s | anchor−30 至 anchor+120 s | T | {by_family['S/Sdiff']['anchor_min']:.1f}–{by_family['S/Sdiff']['anchor_max']:.1f} | {by_family['S/Sdiff']['extended_min']:.1f}–{by_family['S/Sdiff']['extended_max']:.1f} |

不同深度震源和三扇区几何均按各自的 TauP/PREM 路径计算。P 与 Pdiff、S 与 Sdiff 的最早分支会随距离切换；95°–105°行标记为 `transition_distance_flag=true`，此一维模型切换不代表有限频率物理边界。具体锚点分支计数见 `phase_window_validation.json`。

## 证据与窗口映射

- **文献处理结果：** Kim 等报告 Pdiff 窗为 PREM 到时 −30 至 +70 s（`pilot::E001`，`extraction/pilot_evidence_matrix.csv`，第2行，PDF 页索引2、印刷页2、Fig. 1）；同一研究报告 Pdiff 延迟约10–30 s、Sdiff 延迟约25–45 s（`pilot::E002`，同表第3行，PDF 页索引3、印刷页3、Fig. 1F）。
- **文献观测：** Li 等报告 Sdiff postcursor 在10–20 s周期约35–50 s、短周期约50–70 s（`batch_02::B02-E052`，`extraction/batch_02_evidence_matrix.csv`，第20行，PDF 页索引2、印刷页3、Fig. 3）。
- **项目历史处理：** Event‑1 分析的 S/Sdiff extended tail 为 `family_last+20` 至 `family_last+120 s`，见 `/import/freenas-m-01-seismology/xjiang/ulvz_database/scripts/run_event1_reanalysis.py` 的 `CONFIG['windows']`；该历史配置作为处理先例。
- **项目建议：** P/Pdiff 扩展窗将 Kim 的 −30…+70 s 向后延长10 s；S/Sdiff 采用历史分析中的 +120 s 尾窗。两项设置是处理建议，不是观测到时或跨研究综合估计。

## 使用与审查

1. `taup_anchor_s` 是 TauP 最早候选分支到时；`taup_anchor_phase` 保留实际相名，不应将 P/S 锚点改称 Pdiff/Sdiff。
2. 主窗用于主波包测量；扩展窗容纳候选延迟与后续能量。`overlap_flag=true` 时保留重叠信息，训练或评估应按该标记分层。
3. 同源 B0/TRIULVZ 波形可用后，再按分量和扇区复核建议窗口；此表本身不表示模型验证通过。

`catalogs/station_phase_windows.csv` 给出逐源—逐站—逐相位族建议；`catalogs/phase_window_method.json` 记录规则、输入哈希与解释状态；`catalogs/phase_window_source_inventory.csv` 记录输入大小和 SHA-256；`catalogs/phase_window_validation.json` 验证结果为 **{validation['status']}**，包含 {validation['row_count']:,} 行，S/Sdiff 到时与冻结审计表最大差 {validation['s_audit_max_abs_difference_s']:.3g} s。
"""


def build(package_root: Path = ROOT) -> dict[str, Any]:
    package_root = package_root.resolve()
    source_path = package_root / "catalogs/source_ensemble.csv"
    station_path = package_root / "catalogs/station_geometry.csv"
    record_path = package_root / "catalogs/record_length_arrivals.csv"
    contract_path = package_root / "config/contracts/prem_three_sector.toml"
    sources = read_csv(source_path)
    stations = read_csv(station_path)
    record_arrivals = read_csv(record_path)
    contract_text = contract_path.read_text(encoding="utf-8")
    record_minutes = 42.0
    for line in contract_text.splitlines():
        if line.strip().startswith("record_length_minutes"):
            record_minutes = float(line.split("=", 1)[1].strip())
            break
    record_length_s = record_minutes * 60.0
    model = TauPyModel(model="prem")
    arrivals_cache: dict[tuple[float, float], list[tuple[float, str]]] = {}
    rows: list[dict[str, Any]] = []
    for source in sources:
        depth = float(source["depth_km"])
        for station in stations:
            distance = round(float(station["distance_deg"]), 6)
            cache_key = (depth, distance)
            if cache_key not in arrivals_cache:
                arrivals_cache[cache_key] = sorted(
                    (float(item.time), str(item.name)) for item in model.get_travel_times(
                        depth, distance, phase_list=CONTEXT_PHASES))
            station_row = dict(station)
            station_row["distance_deg"] = distance
            rows.extend(family_row(source, station_row, family, arrivals_cache[cache_key])
                        for family in FAMILIES)
    rows.sort(key=lambda row: (row["source_id"], row["station_id"], row["phase_family"]))
    validation = validate(rows, sources, stations, record_arrivals, record_length_s)
    if validation["status"] != "PASS":
        raise RuntimeError("; ".join(validation["errors"]))

    output_rows = []
    inventory_inputs = [
        ("catalogs/source_ensemble.csv", package_root / "catalogs/source_ensemble.csv", "package_read_only_input"),
        ("catalogs/station_geometry.csv", package_root / "catalogs/station_geometry.csv", "package_read_only_input"),
        ("catalogs/record_length_arrivals.csv", package_root / "catalogs/record_length_arrivals.csv", "package_read_only_input"),
        ("config/contracts/prem_three_sector.toml", package_root / "config/contracts/prem_three_sector.toml", "package_read_only_input"),
        ("../../extraction/pilot_evidence_matrix.csv", package_root.parents[1] / "extraction/pilot_evidence_matrix.csv", "repository_read_only_input"),
        ("../../extraction/batch_02_evidence_matrix.csv", package_root.parents[1] / "extraction/batch_02_evidence_matrix.csv", "repository_read_only_input"),
    ]
    for relative, path, access in inventory_inputs:
        if path.is_file():
            output_rows.append({"source_file": relative, "bytes": path.stat().st_size,
                                "sha256": sha256(path), "access": access})
    write_csv(package_root / "catalogs/station_phase_windows.csv", rows)
    write_csv(package_root / "catalogs/phase_window_source_inventory.csv", output_rows)
    method = {
        "taup_model": "prem", "phase_context": CONTEXT_PHASES,
        "main_window": {"before_family_first_s": MAIN_PRE_S,
                        "after_family_last_s": MAIN_POST_S,
                        "family_member_span_s": FAMILY_SPAN_S},
        "families": {name: spec | {"candidates": sorted(spec["candidates"])}
                     for name, spec in FAMILIES.items()},
        "frequency_hz": [0.05, 0.10], "sample_rate_hz": 10.0,
        "record_length_s": record_length_s,
        "interpretation": "project_recommendation_not_observed_pick",
        "window_table": "catalogs/station_phase_windows.csv",
        "input_inventory": "catalogs/phase_window_source_inventory.csv",
    }
    (package_root / "catalogs/phase_window_method.json").write_text(
        json.dumps(method, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (package_root / "catalogs/phase_window_validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (package_root / "catalogs/phase_window_estimate_zh.md").write_text(
        markdown_report(rows, validation), encoding="utf-8")
    return validation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(build(args.package_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
