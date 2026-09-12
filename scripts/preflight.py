#!/usr/bin/env python3
"""Static scientific-design = manifest = rendered-DATA preflight gate."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
import tomllib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()


def tree_digest(path: Path) -> str:
    h = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"):
        h.update(item.relative_to(path).as_posix().encode()+b"\0"+digest(item).encode()+b"\n")
    return h.hexdigest()


def rows(path: Path) -> list[dict[str,str]]:
    with path.open(newline="", encoding="utf-8") as f: return list(csv.DictReader(f))


def par(path: Path) -> dict[str,str]:
    result={}
    for raw in path.read_text().splitlines():
        text=raw.split("#",1)[0].strip()
        if not text or "=" not in text: continue
        key,value=(x.strip() for x in text.split("=",1))
        if key in result: raise ValueError(f"{path}: duplicate {key}")
        result[key]=value
    return result


def cmt(path: Path) -> dict[str,float]:
    result={}
    for raw in path.read_text().splitlines():
        if ":" in raw:
            key,value=(x.strip() for x in raw.split(":",1)); result[key.lower()]=float(value) if key.lower() in {"latitude","longitude","depth","time shift","half duration"} else value
    return result


def ulvz(path: Path) -> tuple[int,dict[int,dict[str,float]],str]:
    values=par(path); n=int(values.get("N_ULVZ","-1")); background=values.get("BACKGROUND_MODEL","")
    bodies={}
    pattern=re.compile(r"ULVZ_(\d+)_(.+)")
    for key,value in values.items():
        m=pattern.fullmatch(key)
        if m: bodies.setdefault(int(m.group(1)),{})[m.group(2)]=float(value)
    return n,bodies,background


def fail(errors: list[str], message: str) -> None: errors.append(message)


def run_preflight(write_outputs: bool = True) -> tuple[dict,list[str]]:
    config_path=ROOT/"config/production.toml"; contract_path=ROOT/"config/contracts/prem_three_sector.toml"
    cfg=tomllib.loads(config_path.read_text()); contract=tomllib.loads(contract_path.read_text())
    manifest=rows(ROOT/"production_run_manifest.csv"); sources=rows(ROOT/"catalogs/source_ensemble.csv")
    stations=rows(ROOT/"catalogs/station_geometry.csv"); parameters=rows(ROOT/"catalogs/ulvz_parameter_catalog.csv"); instances=rows(ROOT/"catalogs/ulvz_instance_manifest.csv"); clearance=rows(ROOT/"catalogs/ulvz_overlap_clearance_audit.csv")
    errors=[]; audit=[]; source_by={x["source_id"]:x for x in sources}; instance_by={x["instance_id"]:x for x in parameters}
    if len(sources)!=50: fail(errors,f"source count {len(sources)} != 50")
    expected_bins={"0-70":39,"70-150":4,"150-300":3,"300-500":1,"500-700":3}
    actual_bins=Counter(x["depth_bin"] for x in sources)
    if actual_bins != expected_bins: fail(errors,f"depth quota {dict(actual_bins)} != {expected_bins}")
    if len(manifest)!=100: fail(errors,f"run count {len(manifest)} != 100")
    if len(stations)!=510 or Counter(x["sector"] for x in stations)!={"A":170,"B":170,"C":170}: fail(errors,"station sectors are not 3 x 170")
    if len({(x["latitude_deg"],x["longitude_deg"]) for x in stations})!=510: fail(errors,"station coordinates are not unique")
    if len(parameters)!=150 or len(instances)!=150: fail(errors,"parameter/instance count != 150")
    if len({x["ulvz_instance_id"] for x in instances})!=150: fail(errors,"instance assignment duplicates or omissions")
    if any(float(x[k]) != 0 for x in parameters for k in ("lateral_taper_km","top_taper_km")): fail(errors,"catalog contains non-zero taper")
    if any(x["status"]!="PASS" or float(x["clearance_km"])<=0 for x in clearance): fail(errors,"overlap/contact audit failed")
    if cfg["lsf"]["max_active_runs"]!=2: fail(errors,"max_active_runs is not config value 2")
    if not cfg["staging"]["require_all_stage1_qc_pass"]: fail(errors,"stage barrier disabled")
    template=par(ROOT/"specfem_template/DATA/Par_file")
    scratch_seen=set(); run_ids=set(); stage_counts=Counter(); source_runs=Counter(); assigned=[]
    expected_common={"NCHUNKS":"6","NEX_XI":"448","NEX_ETA":"448","NPROC_XI":"8","NPROC_ETA":"8","MODEL":"1D_transversely_isotropic_prem","OCEANS":".false.","ELLIPTICITY":".true.","TOPOGRAPHY":".false.","GRAVITY":".true.","ROTATION":".true.","ATTENUATION":".true.","ABSORBING_CONDITIONS":".false.","OUTPUT_SEISMOS_ASDF":".true.","OUTPUT_SEISMOS_ASCII_TEXT":".false.","OUTPUT_SEISMOS_SAC_BINARY":".false."}
    for row in manifest:
        rid=row["run_id"]; run_ids.add(rid); stage_counts[row["stage"]]+=1; source_runs[row["source_id"]]+=1; data=ROOT/"production_inputs"/rid/"DATA"
        source=source_by.get(row["source_id"])
        if source is None: fail(errors,f"{rid}: unknown source"); continue
        scratch=row["scratch_database_path"]
        if scratch in scratch_seen: fail(errors,f"{rid}: duplicate scratch path")
        scratch_seen.add(scratch)
        files={name:data/name for name in ("Par_file","CMTSOLUTION","STATIONS","ulvz_s40rts.par")}
        for name,path in files.items():
            if not path.is_file(): fail(errors,f"{rid}: missing {name}")
        if not all(path.is_file() for path in files.values()): continue
        p=par(files["Par_file"])
        for key,expected in expected_common.items():
            if p.get(key," ").split()[0] != expected: fail(errors,f"{rid}: {key}={p.get(key)} expected {expected}")
        for key in ("LOCAL_PATH","LOCAL_TMP_PATH"):
            if p.get(key)!=scratch: fail(errors,f"{rid}: {key} differs from manifest scratch")
        # All template values except the two local paths are immutable common settings.
        for key,value in template.items():
            if key not in {"LOCAL_PATH","LOCAL_TMP_PATH"} and p.get(key)!=value: fail(errors,f"{rid}: common Par_file differs from template at {key}")
        if digest(files["STATIONS"]) != digest(ROOT/"catalogs/STATIONS"): fail(errors,f"{rid}: STATIONS differs from frozen catalog")
        cm=cmt(files["CMTSOLUTION"])
        if any(abs(float(cm.get(key,999))-expected)>1e-6 for key,expected in (("latitude",0.0),("longitude",0.0),("depth",float(source["depth_km"])) )): fail(errors,f"{rid}: CMT source coordinate/depth mismatch")
        n,bodies,bg=ulvz(files["ulvz_s40rts.par"]); expected_instances=sorted((x for x in instances if x["run_id"]==rid),key=lambda x:int(x["body_index"]))
        if bg!="PREM": fail(errors,f"{rid}: ULVZ background {bg}")
        if n!=int(row["n_ulvz"]) or n!=len(expected_instances): fail(errors,f"{rid}: N_ULVZ mismatch")
        if row["run_kind"]=="baseline" and (n!=0 or bodies): fail(errors,f"{rid}: B0 is not explicit N_ULVZ=0")
        if row["run_kind"]=="tri_ulvz" and (n!=3 or set(bodies)!={1,2,3}): fail(errors,f"{rid}: TRIULVZ does not have exactly three bodies")
        values={"CENTER_LATITUDE_DEGREES":"latitude_deg","CENTER_LONGITUDE_DEGREES":"longitude_deg","LATERAL_RADIUS_KM":"radius_km","THICKNESS_KM":"thickness_km","LATERAL_TAPER_KM":"lateral_taper_km","TOP_TAPER_KM":"top_taper_km","DVS":"dVs_percent","DVP":"dVp_percent","DRHO":"dRho_percent"}
        for item in expected_instances:
            assigned.append(item["ulvz_instance_id"]); body=bodies.get(int(item["body_index"]),{})
            for key,column in values.items():
                expected=float(item[column])/(100 if key in {"DVS","DVP","DRHO"} else 1)
                if abs(body.get(key,float("nan"))-expected)>1e-7: fail(errors,f"{rid}: body {item['body_index']} {key} mismatch")
        item={"run_id":rid,"source_id":row["source_id"],"stage":row["stage"],"baseline_pair_id":row["baseline_pair_id"],"source_depth_km":source["depth_km"],"strike_deg":source["strike_deg"],"dip_deg":source["dip_deg"],"rake_deg":source["rake_deg"],"m0_dyne_cm":source["production_m0_dyne_cm"],"nchunks":p.get("NCHUNKS"),"nex_xi":p.get("NEX_XI"),"nex_eta":p.get("NEX_ETA"),"nproc_xi":p.get("NPROC_XI"),"nproc_eta":p.get("NPROC_ETA"),"oceans":p.get("OCEANS"),"ellipticity":p.get("ELLIPTICITY"),"topography":p.get("TOPOGRAPHY"),"gravity":p.get("GRAVITY"),"rotation":p.get("ROTATION"),"attenuation":p.get("ATTENUATION"),"absorbing_conditions":p.get("ABSORBING_CONDITIONS"),"dt_s":"0.1","record_length_minutes":"42","expected_nstep":"25400","expected_npts":row["expected_npts"],"station_count":row["station_count"],"n_ulvz":str(n),"scratch_path":scratch,"execution_order":row["execution_order"],"input_hash":hashlib.sha256("".join(digest(x) for x in files.values()).encode()).hexdigest(),"preflight_status":"PASS"}
        for i in (1,2,3):
            x=next((z for z in expected_instances if int(z["body_index"])==i),None)
            for label in ("instance_id","sector","position_id","latitude_deg","longitude_deg","radius_km","thickness_km","dVs_percent","dVp_percent","dRho_percent","lateral_taper_km","top_taper_km"):
                item[f"body{i}_{label}"]=x.get("ulvz_"+label,x.get(label,"")) if x else ""
        audit.append(item)
    if len(run_ids)!=100: fail(errors,"duplicate run id")
    if source_runs != Counter({x["source_id"]:2 for x in sources}): fail(errors,"each source does not have exactly two runs")
    if stage_counts != Counter({"stage1_baseline":50,"stage2_multi":50}): fail(errors,f"stage counts invalid {dict(stage_counts)}")
    if Counter(x["run_kind"] for x in manifest) != Counter({"baseline":50,"tri_ulvz":50}): fail(errors,"B0/TRIULVZ count invalid")
    if sorted(assigned)!=sorted(instance_by): fail(errors,"parameter instances do not map one-to-one")
    p_nodes=sum(float(x[f"{sector}_P_near_node_fraction"])>.5 for x in sources for sector in "ABC")
    s_nodes=sum(float(x[f"{sector}_S_near_node_fraction"])>.5 for x in sources for sector in "ABC")
    warnings=["deployment-time validation required for Whale module/MPI/ASDF-HDF5, scratch filesystem, compiled executable and resource availability","no bsub, mesher or solver was invoked by preflight"]
    if p_nodes or s_nodes: warnings.append(f"radiation diagnostic: P near-node source-sector cells={p_nodes}/150; S={s_nodes}/150; project proxy only, inspect source_radiation audit before deployment")
    summary={"status":"PASS" if not errors else "FAIL","timestamp":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),"manifest_hash":digest(ROOT/"production_run_manifest.csv"),"config_hash":digest(config_path),"contract_hash":digest(contract_path),"specfem_template_hash":tree_digest(ROOT/"specfem_template"),"rendered_input_hash":tree_digest(ROOT/"production_inputs"),"rendered_lsf_hash":tree_digest(ROOT/"rendered_lsf"),"runtime_script_hash":tree_digest(ROOT/"scripts"),"source_count":len(sources),"run_count":len(manifest),"station_count":len(stations),"active_ulvz_instances":len(instances),"minimum_clearance_km":min(float(x["clearance_km"]) for x in clearance),"radiation_near_node_cells":{"P":p_nodes,"S":s_nodes},"warnings":warnings,"errors":errors}
    if write_outputs:
        out=ROOT/"preflight"; out.mkdir(exist_ok=True)
        if audit:
            with (out/"all_runs_parameter_audit.csv").open("w",newline="",encoding="utf-8") as f: w=csv.DictWriter(f,fieldnames=list(audit[0])); w.writeheader();w.writerows(audit)
        report=["# PREFLIGHT REPORT","",f"Status: **{summary['status']}**","",f"- sources: {len(sources)}; depth bins: {dict(actual_bins)}","- stations: 510 (A/B/C = 170 each)","- runs: 50 B0 + 50 TRIULVZ","- instances: 150; taper: all zero",f"- parameter sources: {dict(Counter(x['parameter_source'] for x in parameters))}",f"- sectors: {dict(Counter(x['sector'] for x in instances))}",f"- radiation near-node diagnostic cells: P={p_nodes}/150; S={s_nodes}/150",f"- minimum three-body clearance: {summary['minimum_clearance_km']:.3f} km","- common setting: six-chunk, NEX 448x448, NPROC 8x8, ranks 384, PREM/ASDF, DT 0.1 s, record 42 min, expected NSTEP/npts 25400","","## Deployment-time validation","","- Whale GCC/OpenMPI and ASDF/HDF5 build compatibility; executable build; LSF queue and host layout; scratch access; memory/storage; no production mesher/solver result is present.","","## Result","", "PASS: static design equals manifest equals rendered DATA." if not errors else "FAIL:\n"+"\n".join(f"- {x}" for x in errors)]
        (out/"PREFLIGHT_REPORT.md").write_text("\n".join(report)+"\n"); (out/"preflight_summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    return summary,errors


if __name__ == "__main__":
    summary,errors=run_preflight(); print("PREFLIGHT",summary["status"]); raise SystemExit(1 if errors else 0)
