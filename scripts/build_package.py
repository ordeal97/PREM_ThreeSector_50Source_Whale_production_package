#!/usr/bin/env python3
"""Build the frozen, portable PREM three-sector production-input package.

This generator is deliberately local-only: it writes static design, DATA and
LSF artifacts and never invokes LSF, xmeshfem3D, or xspecfem3D.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from obspy.taup import TauPyModel


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OLD = REPO / "packages" / "Aplus_Whale_production_package"
CATALOG = REPO / "results" / "simulation_plan_Aplus_PREM_20260818T142325Z" / "global_cmt_parent_catalog.csv"
BASE_PAR = REPO / "simulations" / "test2chunk" / "v02_6chunk_src01" / "DATA" / "Par_file"
SOURCE_COMMIT = "72f0c39117df9395c12fa901a9ae99fa3e7bdfd9"
SOURCE_REPOSITORY = "git@github.com:ordeal97/ulvz_specfem.git"
SOURCE_SEED = 20260911
ASSIGNMENT_SEED = 20260912
QUOTAS = [(0.0, 70.0, {"strike_slip": 15, "thrust": 19, "normal": 5}),
          (70.0, 150.0, {"strike_slip": 2, "thrust": 1, "normal": 1}),
          (150.0, 300.0, {"strike_slip": 1, "thrust": 1, "normal": 1}),
          (300.0, 500.0, {"strike_slip": 1, "thrust": 0, "normal": 0}),
          (500.0, 700.0, {"strike_slip": 1, "thrust": 0, "normal": 2})]
SECTORS = (("A", 0.0), ("B", 120.0), ("C", 240.0))
CMB_KM = 3480.0
DT = 0.1
RECORD_MINUTES = 42
EXPECTED_NSTEP = 25400
EXPECTED_NPTS = 25400


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def par_replace(payload: str, replacements: dict[str, str]) -> str:
    result = []
    for line in payload.splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        result.append(f"{line.split('=', 1)[0]}= {replacements[key]}" if key in replacements else line)
    return "\n".join(result) + "\n"


def sph_xyz(lat: float, lon: float) -> np.ndarray:
    la, lo = math.radians(lat), math.radians(lon)
    return np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])


def xyz_ll(v: np.ndarray) -> tuple[float, float]:
    v = v / np.linalg.norm(v)
    return math.degrees(math.asin(v[2])), ((math.degrees(math.atan2(v[1], v[0])) + 180) % 360) - 180


def rotate_source_axis(lat: float, lon: float, deg: float) -> tuple[float, float]:
    # Source is (0,0), i.e. the x-axis. Positive source azimuth uses -RH x rotation.
    theta = -math.radians(deg); c, s = math.cos(theta), math.sin(theta)
    x, y, z = sph_xyz(lat, lon)
    return xyz_ll(np.array([x, c*y - s*z, s*y + c*z]))


def takeoff_cache(depth: float, distances: list[float]) -> dict[tuple[str, float], float]:
    model = TauPyModel(model="prem"); values = {}
    for distance in distances:
        for label, phases in (("P", ["P", "Pdiff"]), ("S", ["S", "Sdiff"])):
            arrivals = model.get_travel_times(depth, distance, phase_list=phases)
            if arrivals: values[label, distance] = math.radians(min(arrivals, key=lambda a: a.time).takeoff_angle)
    return values


def tensor(s: float, d: float, r: float) -> np.ndarray:
    # North/East/Down double couple, normalized scalar moment.
    st, di, ra = map(math.radians, (s, d, r)); sd, cd = math.sin(di), math.cos(di)
    sr, cr, ss, cs = math.sin(ra), math.cos(ra), math.sin(st), math.cos(st)
    s2d, s2s, c2d, c2s = math.sin(2*di), math.sin(2*st), math.cos(2*di), math.cos(2*st)
    mnn = -(sd*cr*s2s + s2d*sr*ss**2); mee = sd*cr*s2s - s2d*sr*cs**2; mdd = s2d*sr
    mne = sd*cr*c2s + .5*s2d*sr*s2s; mnd = -(cd*cr*c2s + c2d*sr*ss); med = cd*cr*s2s - c2d*sr*cs
    return np.array([[mnn,mne,mnd],[mne,mee,med],[mnd,med,mdd]])


def station_geometry() -> tuple[list[dict], list[dict]]:
    original = [line.split() for line in (OLD / "provenance" / "STATIONS").read_text().splitlines() if line.strip()]
    stations, audits = [], []
    for sector, rotation in SECTORS:
        for station_id, network, lat, lon, elev, burial in original:
            out_lat, out_lon = rotate_source_axis(float(lat), float(lon), rotation)
            name = f"{sector}{station_id}"
            # delta / initial azimuth are source-centred and invariant under this rotation.
            vector = sph_xyz(out_lat, out_lon)
            distance = math.degrees(math.acos(max(-1, min(1, vector[0]))) )
            azimuth = (math.degrees(math.atan2(vector[1], vector[2])) + 360) % 360
            stations.append({"station_id": name, "network": f"{sector}X", "latitude_deg": f"{out_lat:.8f}", "longitude_deg": f"{out_lon:.8f}", "elevation_m": elev, "burial_m": burial, "sector": sector, "base_station_id": station_id, "distance_deg": f"{distance:.8f}", "initial_azimuth_deg": f"{azimuth:.8f}"})
            audits.append({"station_id": name, "sector": sector, "base_station_id": station_id, "rotation_deg": rotation, "distance_deg": f"{distance:.8f}", "relative_azimuth_deg": f"{((azimuth - rotation) % 360):.8f}", "longitude_wrapped": str(-180 <= out_lon < 180).lower()})
    return stations, audits


def radiation(candidate: dict, base_stations: list[dict], cache: dict[float, dict]) -> tuple[float, dict]:
    m = tensor(float(candidate["strike_deg"]), float(candidate["dip_deg"]), float(candidate["rake_deg"]))
    depth = float(candidate["centroid_depth_km"]); local = cache.setdefault(depth, takeoff_cache(depth, sorted({round(float(s["distance_deg"]), 6) for s in base_stations})))
    rows, score = [], 0.0
    for sector, rot in SECTORS:
        for family in ("P", "S"):
            values = []
            for station in base_stations:
                distance = round(float(station["distance_deg"]), 6); inc = local.get((family, distance))
                azimuth = math.radians(float(station["initial_azimuth_deg"]) + rot)
                n = np.array([math.sin(inc)*math.cos(azimuth), math.sin(inc)*math.sin(azimuth), math.cos(inc)])
                p = float(n @ m @ n); values.append(abs(p) if family == "P" else float(np.linalg.norm(m @ n - p*n)))
            rms, node = float(np.sqrt(np.mean(np.square(values)))), float(np.mean(np.array(values) < .05))
            rows.append({"sector": sector, "phase_family": family, "rms_proxy": rms, "near_node_fraction": node})
            score += rms - 2.0*node
    return score, {f"{x['sector']}_{x['phase_family']}_{k}": v for x in rows for k, v in x.items() if k not in {"sector", "phase_family"}}


def sources(base_stations: list[dict]) -> tuple[list[dict], list[dict], dict]:
    with CATALOG.open(newline="") as f: catalog = list(csv.DictReader(f))
    cache, selected, audit = {}, [], []
    for lo, hi, mechanics in QUOTAS:
        for mechanism, amount in mechanics.items():
            if not amount: continue
            pool = sorted((x for x in catalog if lo <= float(x["centroid_depth_km"]) < hi and x["mechanism_class"] == mechanism), key=lambda x: (float(x["centroid_depth_km"]), x["event_id"]))
            # Twenty deterministic quantile candidates provide depth spread before radiation selection.
            indices = sorted({min(len(pool)-1, int((i+.5)*len(pool)/20)) for i in range(20)})
            scored = []
            for index in indices:
                cand = pool[index]; score, detail = radiation(cand, base_stations, cache)
                scored.append((score, cand, detail, index))
            scored.sort(key=lambda x: (-x[0], x[1]["event_id"]))
            for rank, (score, cand, detail, index) in enumerate(scored):
                audit.append({"event_id": cand["event_id"], "depth_bin_km": f"{lo:g}-{hi:g}", "mechanism_class": mechanism, "candidate_quantile_index": index, "radiation_score": f"{score:.8f}", "selection_rank": rank+1, "selected": str(rank < amount).lower(), **{k: f"{v:.8f}" for k,v in detail.items()}})
            selected.extend(x[1] for x in scored[:amount])
    selected.sort(key=lambda x: (float(x["centroid_depth_km"]), x["event_id"]))
    rows = []
    for i, x in enumerate(selected, 1):
        score, detail = radiation(x, base_stations, cache)
        rows.append({"source_id": f"SRC{i:03d}", "event_id": x["event_id"], "catalog_record_index": x["ndk_record_index_1based"], "latitude_deg": "0.00000000", "longitude_deg": "0.00000000", "depth_km": f"{float(x['centroid_depth_km']):.4f}", "strike_deg": x["strike_deg"], "dip_deg": x["dip_deg"], "rake_deg": x["rake_deg"], "mechanism_class": x["mechanism_class"], "production_m0_dyne_cm": "1.00000000e+26", "catalog_m0_dyne_cm": x["m0_dyne_cm"], "depth_bin": next(f"{lo:g}-{hi:g}" for lo,hi,_ in QUOTAS if lo <= float(x["centroid_depth_km"]) < hi), "selection_seed": str(SOURCE_SEED), "radiation_score": f"{score:.8f}", **{k:f"{v:.8f}" for k,v in detail.items()}})
    summary = {"source_count": len(rows), "depth_bins": dict(Counter(x["depth_bin"] for x in rows)), "mechanisms": dict(Counter(x["mechanism_class"] for x in rows)), "method": "fixed depth×mechanism quota; deterministic depth-quantile candidate pool; P/Pdiff and S/Sdiff three-sector radiation proxy ranking", "diagnostic_note": "near_node_fraction <0.05 amplitude is a project screening diagnostic, not a waveform detection threshold"}
    return rows, audit, summary


def parameter_catalog() -> list[dict]:
    anchors = [("C1","core",240,15,-20,0,0),("C2","core",655,15,-20,0,0),("C3","core",655,50,-20,0,0),("C4","core",400,15,-25,0,0),("C5","core",400,15,-25,-10,0),("C6","core",240,15,-10,0,0),("C7","core",240,15,-30,0,0),("H1","heldout",240,50,-30,0,0),("H2","heldout",400,15,-25,-15,0),("X1","challenge",655,50,-30,0,0),("X2","challenge",240,15,-40,0,0)]
    rows, number = [], 1
    def add(family, source, old, tier, r,h,vs,vp,rho, endpoint, evidence, weight=""):
        nonlocal number
        rows.append({"instance_id":f"ULVZ{number:03d}","family_id":family,"parameter_source":source,"old_type":old,"old_tier":tier,"source_role":tier if tier else "project_sensitivity","radius_km":f"{r:.4f}","thickness_km":f"{h:.4f}","dVs_percent":f"{vs:.4f}","dVp_percent":f"{vp:.4f}","dRho_percent":f"{rho:.4f}","lateral_taper_km":"0.0000","top_taper_km":"0.0000","original_endpoint":str(endpoint).lower(),"within_family_interpolation":str(not endpoint).lower(),"interpolation_weight":weight,"evidence_source":evidence,"provenance_note":"project sensitivity design; production-compatible circular uniform-body interface"}); number += 1
    for old,tier,r,h,vs,vp,rho in anchors:
        for _ in range(3): add("F_legacy_anchor", "legacy_parameter_anchor", old, tier, r,h,vs,vp,rho, True, "A+ production type provenance")
    families = [("F_small_dvs",(240,15,-10,0,0),(240,15,-30,0,0),"results/ulvz_ml_parameter_value_redesign_upgrade_20260814T162404Z"),("F_p_control",(400,15,-25,0,0),(400,15,-25,-15,0),"results/ulvz_ml_parameter_value_redesign_20260814T153654Z"),("F_small_thickness_velocity",(240,10,-20,0,0),(240,20,-30,0,0),"batch_02::B02-E152; batch_02::B02-E104")]
    for family,a,b,evidence in families:
        for k in range(22):
            w=(k+.5)/22; vals=[a[i]*(1-w)+b[i]*w for i in range(5)]
            add(family,"family_interpolant","NONE","",*vals,False,evidence,f"{w:.8f}")
    survey = [("F_density_sensitivity",(240,15,-20,0,0),(240,15,-20,0,20),"S04_DRHO10/S05_DRHO20; density is sensitivity input"),("F_small_medium_tradeoff",(180,10,-30,0,0),(455,20,-20,0,0),"batch_02::B02-E104; project sensitivity assumption after location decoupling"),("F_mega_height",(655,15,-20,0,0),(655,50,-20,0,0),"batch_02::B02-E065; pilot::E004")]
    for family,a,b,evidence in survey:
        for k in range(17):
            w=(k+.5)/17; vals=[a[i]*(1-w)+b[i]*w for i in range(5)]
            add(family,"survey_family_sample","NONE","",*vals,False,evidence,f"{w:.8f}")
    assert len(rows)==150
    return rows


def position_catalog() -> list[dict]:
    with (OLD / "provenance" / "ulvz_positions.csv").open(newline="") as f: base=list(csv.DictReader(f))
    rows=[]
    for sector,rot in SECTORS:
        for item in base:
            lat,lon=rotate_source_axis(float(item["latitude_deg"]),float(item["longitude_deg"]),rot)
            rows.append({"position_id":f"{sector}_{item['position_id']}","sector":sector,"base_position_id":item["position_id"],"latitude_deg":f"{lat:.8f}","longitude_deg":f"{lon:.8f}","rotation_deg":f"{rot:.1f}","cmb_radius_km":str(CMB_KM),"provenance":"A+ canonical G01-G08 rotated about source radial axis"})
    return rows


def assign(sources: list[dict], parameters: list[dict], positions: list[dict]) -> tuple[list[dict], list[dict]]:
    rng=random.Random(ASSIGNMENT_SEED); by_source={x["source_id"]:x for x in sources}; by_sector={s:[x for x in positions if x["sector"]==s] for s,_ in SECTORS}
    # Source category totals (33/66/51) are each divisible by three, so every sector gets equal source counts.
    buckets=defaultdict(list)
    for p in parameters: buckets[p["parameter_source"]].append(p)
    assigned={sector:[] for sector,_ in SECTORS}
    for source, values in buckets.items():
        rng.shuffle(values)
        for i,sector in enumerate(assigned): assigned[sector].extend(values[i*len(values)//3:(i+1)*len(values)//3])
    rows=[]
    for sector,_ in SECTORS:
        rng.shuffle(assigned[sector]); available=by_sector[sector]*7; rng.shuffle(available)
        for index,(p,pos) in enumerate(zip(assigned[sector],available[:50])):
            source=sources[index]
            rows.append({"run_id":f"{source['source_id']}_TRIULVZ","source_id":source["source_id"],"sector":sector,"ulvz_instance_id":p["instance_id"],"body_index": {"A":1,"B":2,"C":3}[sector],"position_id":pos["position_id"],"base_position_id":pos["base_position_id"],"latitude_deg":pos["latitude_deg"],"longitude_deg":pos["longitude_deg"], **{k:p[k] for k in ("family_id","parameter_source","old_type","old_tier","source_role","radius_km","thickness_km","dVs_percent","dVp_percent","dRho_percent","lateral_taper_km","top_taper_km","evidence_source")}})
    # clearance with actual support radius; center locations are intentionally on disjoint three-sector lobes.
    audits=[]
    for source in sources:
        run=[x for x in rows if x["source_id"]==source["source_id"]]
        for i in range(3):
            for j in range(i+1,3):
                a,b=run[i],run[j]; angle=math.acos(max(-1,min(1,float(np.dot(sph_xyz(float(a['latitude_deg']),float(a['longitude_deg'])),sph_xyz(float(b['latitude_deg']),float(b['longitude_deg'])))))))
                distance=angle*CMB_KM; clearance=distance-float(a["radius_km"])-float(b["radius_km"])
                audits.append({"run_id":a["run_id"],"body_i":a["body_index"],"body_j":b["body_index"],"center_distance_km":f"{distance:.6f}","support_radius_i_km":a["radius_km"],"support_radius_j_km":b["radius_km"],"clearance_km":f"{clearance:.6f}","status":"PASS" if clearance>0 else "FAIL"})
    return rows,audits


def cmt(source: dict) -> str:
    m=tensor(float(source["strike_deg"]),float(source["dip_deg"]),float(source["rake_deg"]))*1e26
    return (f"PDE 2000  1  1  0  0  0.00   0.0000    0.0000  0.0 0.0 0.0 {source['source_id']}\n"
            f"event name:     {source['source_id']}\ntime shift:      0.0000\nhalf duration:   0.0000\nlatitude:        0.0000\nlongitude:       0.0000\ndepth:           {float(source['depth_km']):.4f}\n"
            f"Mrr: {m[2,2]: .8e}\nMtt: {m[0,0]: .8e}\nMpp: {m[1,1]: .8e}\nMrt: {-m[0,2]: .8e}\nMrp: {-m[1,2]: .8e}\nMtp: {-m[0,1]: .8e}\n")


def ulvz_file(items: list[dict]) -> str:
    out=["# Validated multi-ULVZ interface; zero taper is fixed for this design.","BACKGROUND_MODEL = PREM",f"N_ULVZ = {len(items)}"]
    fields=[("CENTER_LATITUDE_DEGREES","latitude_deg"),("CENTER_LONGITUDE_DEGREES","longitude_deg"),("LATERAL_RADIUS_KM","radius_km"),("THICKNESS_KM","thickness_km"),("LATERAL_TAPER_KM","lateral_taper_km"),("TOP_TAPER_KM","top_taper_km"),("DVS","dVs_percent"),("DVP","dVp_percent"),("DRHO","dRho_percent")]
    for item in items:
        for key,column in fields:
            value=float(item[column]); value=value/100 if key in {"DVS","DVP","DRHO"} else value
            out.append(f"ULVZ_{item['body_index']}_{key} = {value:.8f}")
    return "\n".join(out)+"\n"


def render_lsf(run_id: str, stage: str) -> tuple[str,str,str]:
    preamble=f"#BSUB -J PREM3S_{run_id}_{{kind}}\n#BSUB -q mpi\n#BSUB -n 384\n#BSUB -R \"span[ptile=64]\"\n#BSUB -o logs/{{kind}}-%J.out\n#BSUB -e logs/{{kind}}-%J.err\n"
    runtime="""set -euo pipefail
WORKPATH="${LS_SUBCWD:-$PWD}"; cd "$WORKPATH"
module purge; module load gcc/12.4.0; module load openmpi/4.1.5
OMPI_HOME=/share/apps/openmpi/4.1.5; GCC_HOME=/share/apps/gcc/12.4.0
export LD_LIBRARY_PATH="${GCC_HOME}/lib64:${OMPI_HOME}/lib:${LD_LIBRARY_PATH:-}"
HOSTFILE="$WORKPATH/hostfile.${LSB_JOBID}"; sort "${LSB_DJOB_HOSTFILE}" | uniq -c | awk '{print $2 " slots=" $1}' > "$HOSTFILE"; trap 'rm -f "$HOSTFILE"' EXIT
mpirun --prefix "$OMPI_HOME" -np "${LSB_DJOB_NUMPROC:-384}" --hostfile "$HOSTFILE" --map-by ppr:64:node --bind-to core --mca pml ucx --mca btl '^openib' -x LD_LIBRARY_PATH "./bin/{exe}"
"""
    mesh=preamble.format(kind="mesher")+runtime.replace("{exe}", "xmeshfem3D")
    solver=preamble.format(kind="solver")+runtime.replace("{exe}", "xspecfem3D")
    submit=f"#!/usr/bin/env bash\n# Stage {stage}; controller owns submission order.\nset -euo pipefail\nbsub < mesher_lsf.bash\n"
    return submit,mesh,solver


def plot(sources: list[dict], parameters: list[dict], instances: list[dict]) -> None:
    fig,ax=plt.subplots(1,2,figsize=(10,4)); ax[0].hist([float(x['depth_km']) for x in sources],bins=[0,70,150,300,500,700]); ax[0].set(xlabel="depth km",ylabel="sources")
    ax[1].scatter([float(x['radius_km']) for x in parameters],[float(x['thickness_km']) for x in parameters],c=[float(x['dVs_percent']) for x in parameters],cmap="viridis"); ax[1].set(xlabel="R km",ylabel="H km")
    fig.tight_layout(); fig.savefig(ROOT/"figures"/"source_depth_and_parameter_space.png",dpi=180); plt.close(fig)
    fig,ax=plt.subplots(figsize=(7,3)); counts=Counter(x['parameter_source'] for x in instances); ax.bar(counts.keys(),counts.values()); ax.set_ylabel("assigned instances"); fig.tight_layout(); fig.savefig(ROOT/"figures"/"assignment_sources.png",dpi=180); plt.close(fig)


def main() -> None:
    if ROOT.exists() and any(ROOT.iterdir()):
        # A previous interrupted invocation may have created only these empty
        # package-owned directories.  Never overwrite an unrelated package.
        allowed={"scripts","catalogs","config","production_inputs","rendered_lsf","preflight","figures","specfem_template","provenance"}
        generated_root_files={"production_run_manifest.csv", "production_status_template.csv", "README.md", "PRODUCTION_RUNBOOK_zh.md", "design_summary.json"}
        if any(p.name not in allowed and p.name not in generated_root_files for p in ROOT.iterdir()): raise RuntimeError(f"refusing to overwrite non-generator package: {ROOT}")
    for d in ("catalogs","config/contracts","production_inputs","rendered_lsf","preflight","figures","specfem_template/DATA","provenance","scripts"): (ROOT/d).mkdir(parents=True,exist_ok=True)
    stations,station_audit=station_geometry(); base=[x for x in stations if x['sector']=='A']; source_rows,selection,selection_summary=sources(base); parameters=parameter_catalog(); positions=position_catalog(); instances,clearance=assign(source_rows,parameters,positions)
    write_csv(ROOT/"catalogs"/"source_ensemble.csv",source_rows); write_csv(ROOT/"catalogs"/"source_selection_audit.csv",selection); write(ROOT/"catalogs"/"source_radiation_audit.json",json.dumps(selection_summary,indent=2)+"\n")
    write_csv(ROOT/"catalogs"/"station_geometry.csv",stations); write(ROOT/"catalogs"/"station_geometry_audit.json",json.dumps({"station_count":len(stations),"by_sector":dict(Counter(x['sector'] for x in stations)),"unique_coordinate_count":len({(x['latitude_deg'],x['longitude_deg']) for x in stations}),"rotation":"source-axis strict spherical rotation; positive azimuth +120/+240"},indent=2)+"\n")
    write_csv(ROOT/"catalogs"/"ulvz_position_catalog.csv",positions); write_csv(ROOT/"catalogs"/"ulvz_parameter_catalog.csv",parameters); write_csv(ROOT/"catalogs"/"ulvz_instance_manifest.csv",instances); write(ROOT/"catalogs"/"ulvz_assignment_audit.json",json.dumps({"seed":ASSIGNMENT_SEED,"instance_count":len(instances),"by_sector":dict(Counter(x['sector'] for x in instances)),"by_parameter_source":dict(Counter(x['parameter_source'] for x in instances)),"minimum_clearance_km":min(float(x['clearance_km']) for x in clearance),"all_clearance_pass":all(x['status']=='PASS' for x in clearance)},indent=2)+"\n"); write_csv(ROOT/"catalogs"/"ulvz_overlap_clearance_audit.csv",clearance)
    station_text="\n".join(f"{x['station_id']} {x['network']} {x['latitude_deg']} {x['longitude_deg']} {x['elevation_m']} {x['burial_m']}" for x in stations)+"\n"; write(ROOT/"catalogs"/"STATIONS",station_text)
    par=par_replace(BASE_PAR.read_text(),{"MODEL":"1D_transversely_isotropic_prem","OCEANS":".false.","TOPOGRAPHY":".false.","ATTENUATION":".true.","ABSORBING_CONDITIONS":".false.","RECORD_LENGTH_IN_MINUTES":"42.d0   # audited expected NSTEP=25400, expected npts=25400","LOCAL_PATH":"@@SCRATCH_DATABASE_PATH@@","LOCAL_TMP_PATH":"@@SCRATCH_DATABASE_PATH@@","OUTPUT_SEISMOS_ASCII_TEXT":".false.","OUTPUT_SEISMOS_SAC_BINARY":".false.","OUTPUT_SEISMOS_ASDF":".true."})
    write(ROOT/"specfem_template"/"DATA"/"Par_file",par); write(ROOT/"specfem_template"/"DATA"/"STATIONS",station_text); write(ROOT/"specfem_template"/"DATA"/"CMTSOLUTION",cmt(source_rows[0])); write(ROOT/"specfem_template"/"DATA"/"ulvz_s40rts.par",ulvz_file([]))
    write(ROOT/"specfem_template"/"SOURCE_PROVENANCE.md",f"# SPECFEM source baseline\n\nClone `{SOURCE_REPOSITORY}` and check out `{SOURCE_COMMIT}`. This package intentionally stores a source reference rather than an unverified local working tree. The required source supports `N_ULVZ=0/3`, overlap checks and `OUTPUT_FILES/ulvz_normalized.csv`.\n")
    write(ROOT/"specfem_template"/"README.md","# Canonical SPECFEM template\n\n`DATA/Par_file` is the common six-chunk PREM configuration. Every rendered run must inherit it except LOCAL_PATH/LOCAL_TMP_PATH, CMTSOLUTION and ULVZ body data. Build the referenced source on Whale during deployment validation.\n")
    write(ROOT/"specfem_template"/"build_runtime.toml","[source]\nrepository = 'git@github.com:ordeal97/ulvz_specfem.git'\ncommit = '72f0c39117df9395c12fa901a9ae99fa3e7bdfd9'\n[environment]\nmodules = ['gcc/12.4.0', 'openmpi/4.1.5']\nmpi_launcher = 'mpirun --map-by ppr:64:node --bind-to core --mca pml ucx --mca btl ^openib'\n[build]\nmesher_target = 'meshfem3D'\nsolver_target = 'specfem3D'\n")
    manifest=[]
    for order,source in enumerate(source_rows,1):
        for kind in ("B0","TRIULVZ"):
            run_id=f"{source['source_id']}_{kind}"; stage="stage1_baseline" if kind=="B0" else "stage2_multi"; bodies=[] if kind=="B0" else sorted([x for x in instances if x['source_id']==source['source_id']],key=lambda x:int(x['body_index']))
            data=ROOT/"production_inputs"/run_id/"DATA"; data.mkdir(parents=True,exist_ok=True); scratch=f"/scratch/yiy/ulvz/{run_id}/DATABASES_MPI/"
            write(data/"Par_file",par.replace("@@SCRATCH_DATABASE_PATH@@",scratch)); write(data/"STATIONS",station_text); write(data/"CMTSOLUTION",cmt(source)); write(data/"ulvz_s40rts.par",ulvz_file(bodies))
            lsf=ROOT/"rendered_lsf"/run_id; lsf.mkdir(parents=True,exist_ok=True); submit,mesh,solver=render_lsf(run_id,stage); write(lsf/"submit_lsf.bash",submit); write(lsf/"mesher_lsf.bash",mesh); write(lsf/"solver_lsf.bash",solver)
            manifest.append({"run_id":run_id,"source_id":source['source_id'],"stage":stage,"run_kind":"baseline" if kind=="B0" else "tri_ulvz","baseline_pair_id":f"{source['source_id']}_B0","n_ulvz":str(len(bodies)),"composition_summary":"" if not bodies else ";".join(f"{x['sector']}:{x['ulvz_instance_id']}:{x['parameter_source']}" for x in bodies),"station_count":"510","expected_trace_count":"1530","expected_npts":str(EXPECTED_NPTS),"scratch_database_path":scratch,"execution_order":str(order if kind=="B0" else 50+order),"run_relative_path":f"production_inputs/{run_id}","par_file_sha256":sha(data/"Par_file"),"cmtsolution_sha256":sha(data/"CMTSOLUTION"),"stations_sha256":sha(data/"STATIONS"),"ulvz_file_sha256":sha(data/"ulvz_s40rts.par")})
    write_csv(ROOT/"production_run_manifest.csv",manifest)
    record=[]; model=TauPyModel(model="prem"); arrivals_cache={}
    families=(("P/Pdiff",{"P","Pdiff"}),("S/Sdiff",{"S","Sdiff"}),("PP",{"PP"}),("SKS",{"SKS"}),("SS",{"SS"}))
    for source in source_rows:
        for st in stations:
            distance=round(float(st['distance_deg']),6)
            key0=(float(source['depth_km']),distance)
            if key0 not in arrivals_cache:
                # One TauP traversal per source-depth/distance returns every
                # requested phase; this keeps the full 50×510 audit practical.
                arrivals_cache[key0]=model.get_travel_times(key0[0],distance,phase_list=["P","Pdiff","S","Sdiff","PP","SKS","SS"])
            for family,phases in families:
                key=(float(source['depth_km']),distance,family)
                if key not in arrivals_cache:
                    a=[x for x in arrivals_cache[key0] if x.name in phases]
                    arrivals_cache[key]=(min(a,key=lambda v:v.time).name,min(a,key=lambda v:v.time).time) if a else None
                if arrivals_cache[key]:
                    name,time=arrivals_cache[key]; record.append({"source_id":source['source_id'],"station_id":st['station_id'],"sector":st['sector'],"source_depth_km":source['depth_km'],"distance_deg":st['distance_deg'],"phase_family":family,"actual_phase":name,"arrival_time_s":f"{time:.6f}"})
    write_csv(ROOT/"catalogs"/"record_length_arrivals.csv",record); latest=max(record,key=lambda x:float(x['arrival_time_s'])); write(ROOT/"catalogs"/"record_length_audit.json",json.dumps({"latest":latest,"safety_margin_s":120,"required_duration_s":float(latest['arrival_time_s'])+120,"record_length_minutes":RECORD_MINUTES,"dt_s":DT,"expected_nstep":EXPECTED_NSTEP,"expected_npts":EXPECTED_NPTS,"note":"NSTEP includes SPECFEM start-time/half-duration rounding allowance; deployment solver output must confirm"},indent=2)+"\n")
    contract="""[identity]\nname = \"PREM_three_sector_50source\"\n[design]\nrun_count = 100\nsource_count = 50\nbaseline_count = 50\nmulti_count = 50\nstation_count = 510\nactive_ulvz_instances = 150\n[inputs]\nbackground_model = \"PREM\"\nnchunks = 6\nnex_xi = 448\nnex_eta = 448\nnproc_xi = 8\nnproc_eta = 8\nmpi_ranks = 384\nrecord_length_minutes = 42\ndt_s = 0.1\nexpected_nstep = 25400\nexpected_npts = 25400\n[physics]\noceans = false\nellipticity = true\ntopography = false\ngravity = true\nrotation = true\nattenuation = true\nabsorbing_conditions = false\n[staging]\nstage1 = \"stage1_baseline\"\nstage2 = \"stage2_multi\"\nrequire_all_stage1_qc_pass = true\n"""
    write(ROOT/"config"/"contracts"/"prem_three_sector.toml",contract)
    config="""[paths]\nrun_root = \"worktrees\"\nscratch_root = \"/scratch/yiy/ulvz\"\nmanifest = \"production_run_manifest.csv\"\ninputs_dir = \"production_inputs\"\nruntime_root = \".production_runtime\"\n[lsf]\nmpi_queue = \"mpi\"\nmpi_ranks = 384\nptile = 64\nmax_active_runs = 2\n[staging]\nstage1 = \"stage1_baseline\"\nstage2 = \"stage2_multi\"\nrequire_all_stage1_qc_pass = true\n[source]\nrepository = \"git@github.com:ordeal97/ulvz_specfem.git\"\ncommit = \"72f0c39117df9395c12fa901a9ae99fa3e7bdfd9\"\n"""
    write(ROOT/"config"/"production.toml",config)
    write(ROOT/"production_status_template.csv","run_id,state,output_qc,reason\n"+"".join(f"{x['run_id']},NOT_SUBMITTED,,\n" for x in manifest))
    write(ROOT/"provenance"/"six_chunk_configuration_audit.md","# six-chunk configuration audit\n\n## validated_from_whale_chunk6\n\nHistorical Whale scripts declare `mpi`, 384 ranks, `span[ptile=64]`, six nodes via `ppr:64:node`, GCC 12.4/OpenMPI 4.1.5 and an LSF hostfile launcher. The uploaded directory contains no job log; historical success is user-supplied evidence.\n\n## validated_from_existing_6chunk_test\n\nThe existing PREM six-chunk fixture logged 384 ranks, NEX 448x448, NPROC 8x8 and DT=0.1.\n\n## common_frozen_settings\n\nNCHUNKS=6; NEX=448x448; NPROC=8x8; 384 ranks; ptile64; attenuation true; absorbing false.\n\n## remaining_unverified_settings\n\nThis package changes OCEANS to false and combines PREM/ASDF with the fixed multi-ULVZ source baseline and Whale OpenMPI build. Those are deployment-time validation items.\n")
    write(ROOT/"README.md","# PREM three-sector 50-source Whale production package\n\nStatic, portable 100-run input package. Run `python scripts/production_cli.py --config config/production.toml validate`, then `preflight`, inspect `preflight/PREFLIGHT_REPORT.md`, perform `deployment-check` on Whale, and only then `submit`. Submit refuses a stale or absent preflight PASS. This package does not contain a mesher/solver result.\n")
    write(ROOT/"PRODUCTION_RUNBOOK_zh.md","# 使用流程\n\n本包已完成静态设计与输入生成；未提交Whale。搬迁后先更新部署路径并重新运行 `validate`、`preflight`，人工审查母包与总表，运行 `deployment-check`，最后才允许 `submit`。所有50个B0的运行态QC通过前，controller不得提交TRIULVZ阶段。\n")
    write(ROOT/"design_summary.json",json.dumps({"n_sources":50,"n_station_sectors":3,"stations_per_sector":170,"n_stations":510,"runs_per_source":2,"n_runs":100,"ulvz_per_multi_run":3,"n_ulvz_instances":150,"nchunks":6,"max_active_runs":2,"source_seed":SOURCE_SEED,"assignment_seed":ASSIGNMENT_SEED},indent=2)+"\n")
    plot(source_rows,parameters,instances)
    print(ROOT)

if __name__ == "__main__": main()
