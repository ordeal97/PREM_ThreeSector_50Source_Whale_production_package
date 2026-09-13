#!/usr/bin/env python3
"""Create isolated run trees from a verified build-template source snapshot."""
from __future__ import annotations
import argparse,json,shlex,shutil,tomllib
from datetime import datetime,timezone
from pathlib import Path
from production_common import environment_setup as shared_environment_setup,load_config,rows,runtime

IGNORE=shutil.ignore_patterns('.git','obj','bin','DATABASES_MPI','OUTPUT_FILES','logs','__pycache__')
RUNTIME_DIRS=('obj','bin','OUTPUT_FILES','logs')
def ensure_runtime_dirs(target):
 for name in RUNTIME_DIRS:(target/name).mkdir(parents=True,exist_ok=True)
def may_replace_inactive(status):
 state=status.get('state','')
 return state=='NOT_SUBMITTED' or (state in {'EXIT','QC_FAIL'} and status.get('scratch_cleaned')=='true')
def latest_build(cfg):
 builds=cfg['paths']['runtime_root']/'builds';candidates=[]
 for manifest in builds.glob('*/build_manifest.json') if builds.is_dir() else ():
  try:
   item=json.loads(manifest.read_text());source=Path(item.get('mesher','')).parents[1]
   if item.get('status')=='BUILT_MESHER_ONLY' and item.get('verified_commit')==cfg['source']['commit'] and (source/'configure').is_file():candidates.append((manifest.stat().st_mtime,source,manifest,item.get('module_commands',[])))
  except (OSError,json.JSONDecodeError):pass
 if not candidates:raise RuntimeError('no compatible build-template evidence; run build-template first')
 _,source,manifest,modules=sorted(candidates)[-1];return source,manifest,modules
def default_modules(cfg):
 return [['module','load',x] for x in cfg['environment']['modules']]
def environment_setup(cfg):
 return shared_environment_setup(cfg['environment'])
def lsf(cfg,row,run,module_commands=()):
 ranks=str(cfg['lsf']['mpi_ranks']);ptile=str(cfg['lsf']['ptile']);queue=cfg['lsf']['mpi_queue'];jobs=str(cfg['build']['make_jobs']);modules=environment_setup(cfg);workdir='${'+'LS_SUBCWD:-$PWD}';launcher=cfg['environment']['mpi_launcher']
 python=shlex.quote(cfg.get('runtime',{}).get('python_bin','python3'))
 def job(kind,exe):
  return f'''#!/usr/bin/env bash
#BSUB -J PREM3S_{row['run_id']}_{kind}
#BSUB -q {queue}
#BSUB -n {ranks}
#BSUB -R "span[ptile={ptile}]"
#BSUB -L /bin/bash
#BSUB -o logs/{kind}-%J.out
#BSUB -e logs/{kind}-%J.err
set -euo pipefail
cd "{workdir}"
{modules}
[[ -x bin/{exe} ]]
{launcher} -np "${{LSB_DJOB_NUMPROC:-{ranks}}}" ./bin/{exe}
'''
 (run/'mesher_lsf.bash').write_text(job('mesher','xmeshfem3D'))
 (run/'solver_lsf.bash').write_text(job('solver','xspecfem3D'))
 (run/'submit_lsf.bash').write_text(f'''#!/usr/bin/env bash
#BSUB -J PREM3S_{row['run_id']}_control
#BSUB -q {cfg['lsf']['control_queue']}
#BSUB -n {cfg['lsf']['control_ranks']}
#BSUB -R "span[hosts={cfg['lsf']['control_hosts']}]"
#BSUB -L /bin/bash
#BSUB -o logs/control-%J.out
#BSUB -e logs/control-%J.err
# Per-run controller: compile mesher, submit/wait mesh, compile/submit solver.
set -euo pipefail
WORKPATH="{workdir}"; cd "$WORKPATH"; mkdir -p logs
PACKAGE_ROOT="$(cd "$WORKPATH/../.." && pwd)"
SMOKE_TOOL="$PACKAGE_ROOT/scripts/asdf_smoke.py"
LINKAGE_TOOL="$PACKAGE_ROOT/scripts/linkage_audit.py"
[[ -f "$SMOKE_TOOL" && -f "$LINKAGE_TOOL" ]] || {{ echo "package smoke/linkage tools missing" >&2; exit 1; }}
{modules}
[[ -d "{row['scratch_database_path']}" && -w "{row['scratch_database_path']}" ]]
lock=.mesh_solver_control.lock; mkdir "$lock" || {{ echo "active control lock" >&2; exit 2; }}
trap 'rmdir "$lock" 2>/dev/null || true' EXIT
MESHER_JOB_ID=""; SOLVER_JOB_ID=""; MESHER_SUBMISSION_STATE=""; SOLVER_SUBMISSION_STATE=""
write_metadata() {{ local tmp=run_job_ids.env.tmp.$$; {{ printf 'run_id={row['run_id']}\\ncontrol_job_id=%s\\nmesher_job_id=%s\\nsolver_job_id=%s\\nmesher_submission_state=%s\\nsolver_submission_state=%s\\n' "${{LSB_JOBID:-}}" "$MESHER_JOB_ID" "$SOLVER_JOB_ID" "$MESHER_SUBMISSION_STATE" "$SOLVER_SUBMISSION_STATE"; }} > "$tmp"; mv "$tmp" run_job_ids.env; }}
fail() {{ write_metadata; echo "ERROR: $*" >&2; exit 1; }}
jobid() {{ awk -F '[<>]' '/Job </ {{print $2; exit}}'; }}
state() {{ local value history; value="$(bjobs -a "$1" 2>/dev/null | awk 'NR==2 {{print $3}}' || true)"; if [[ -n "$value" ]]; then printf '%s\\n' "$value"; return; fi; history="$(bhist -l "$1" 2>/dev/null || true)"; if grep -Eqi 'Completed <done>|Done successfully' <<< "$history"; then echo DONE; elif grep -Eqi 'Completed <exit>|Exited' <<< "$history"; then echo EXIT; else echo UNKNOWN; fi; }}
wait_done() {{ local unknown=0 x; while :; do x="$(state "$1")"; case "$x" in DONE) return;; EXIT) fail "$2 exited: $1";; PEND|RUN|WAIT|PSUSP|USUSP|SSUSP|UNKWN|ZOMBI) unknown=0;; *) unknown=$((unknown+1)); [[ "$unknown" -lt 12 ]] || fail "cannot determine $2 state: $1";; esac; sleep {cfg['lsf']['per_run_wait_seconds']}; done; }}
submit_child() {{ local kind="$1" script="$2" output; if [[ "$kind" == mesher ]]; then MESHER_SUBMISSION_STATE=PENDING; else SOLVER_SUBMISSION_STATE=PENDING; fi; write_metadata; if ! output="$(bsub < "$script" 2>&1)"; then printf '%s\\n' "$output" >> logs/control-submit.log; fail "$kind submission failed"; fi; printf '%s\\n' "$output" >> logs/control-submit.log; output="$(printf '%s\\n' "$output" | jobid)"; [[ "$output" =~ ^[0-9]+$ ]] || fail "cannot parse $kind job id"; if [[ "$kind" == mesher ]]; then MESHER_JOB_ID="$output"; MESHER_SUBMISSION_STATE=CONFIRMED; else SOLVER_JOB_ID="$output"; SOLVER_SUBMISSION_STATE=CONFIRMED; fi; write_metadata; }}
command -v bsub >/dev/null 2>&1 && command -v bjobs >/dev/null 2>&1 && command -v bhist >/dev/null 2>&1 || fail "LSF commands unavailable"
write_metadata
make clean; make {cfg['build']['mesher_target']} -j{jobs}
{python} "$SMOKE_TOOL" --source-dir "$WORKPATH" --output-dir "$WORKPATH/.asdf_smoke/mesher" || fail "ASDF/HDF5 smoke failed after meshfem build"
{python} "$LINKAGE_TOOL" --binary "$WORKPATH/bin/xmeshfem3D" --output "$WORKPATH/logs/mesher-linkage.json" || fail "mesher linkage audit failed"
submit_child mesher mesher_lsf.bash
wait_done "$MESHER_JOB_ID" mesher
make clean; make {cfg['build']['solver_target']} -j{jobs}
{python} "$LINKAGE_TOOL" --binary "$WORKPATH/bin/xspecfem3D" --require-asdf --output "$WORKPATH/logs/solver-linkage.json" || fail "solver ASDF linkage audit failed"
submit_child solver solver_lsf.bash
''')
 for path in (run/'mesher_lsf.bash',run/'solver_lsf.bash',run/'submit_lsf.bash'):path.chmod(0o755)
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--source',type=Path);p.add_argument('--dry-run',action='store_true');p.add_argument('--refresh-lsf',action='store_true');p.add_argument('--rebuild-inactive',action='store_true');p.add_argument('--run-id',action='append');a=p.parse_args();cfg=load_config(a.config)
 if a.refresh_lsf and a.rebuild_inactive:raise SystemExit('--refresh-lsf and --rebuild-inactive are mutually exclusive')
 source=None;modules=default_modules(cfg)
 if not a.refresh_lsf:
  if a.source:source=a.source.resolve()
  else:source,_,modules=latest_build(cfg)
  if not (source/'configure').is_file():raise SystemExit('source tree lacks configure')
 created=[]
 status={}
 status_path=runtime(cfg)['status']
 if status_path.is_file():status={x['run_id']:x for x in rows(status_path)}
 selected=set(a.run_id or ())
 for row in rows(cfg['paths']['manifest']):
  if selected and row['run_id'] not in selected:continue
  target=cfg['paths']['run_root']/row['run_id']
  if a.refresh_lsf and not target.exists():raise SystemExit('cannot refresh missing worktree '+row['run_id'])
  if target.exists():
    if not (target/'DATA/Par_file').is_file():raise SystemExit('refusing non-worktree path '+str(target))
    ensure_runtime_dirs(target)
    if a.refresh_lsf:
     if status.get(row['run_id'],{}).get('state') in {'CONTROL_PEND','CONTROL_RUN','MESHER','SOLVER','QC','CLEANUP_PENDING'}:raise SystemExit('refusing LSF refresh while run is active: '+row['run_id'])
     if not a.dry_run:lsf(cfg,row,target,modules or default_modules(cfg))
     continue
    if not a.rebuild_inactive:continue
    prior=status.get(row['run_id'],{})
    if not may_replace_inactive(prior):raise SystemExit('rebuild-inactive requires NOT_SUBMITTED or terminal failed run with cleaned scratch: '+row['run_id'])
    if not a.dry_run:
     archive=cfg['paths']['runtime_root']/'superseded_worktrees'/(row['run_id']+'.'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
     archive.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(target),str(archive))
  created.append(row['run_id'])
  if a.dry_run:continue
  shutil.copytree(source,target,ignore=IGNORE);shutil.copytree(cfg['paths']['inputs_dir']/row['run_id']/'DATA',target/'DATA',dirs_exist_ok=True)
  ensure_runtime_dirs(target);lsf(cfg,row,target,modules or default_modules(cfg))
  (target/'run_identity.json').write_text(json.dumps({'run_id':row['run_id'],'source_commit':cfg['source']['commit'],'input_hashes':{k:row[k] for k in ('par_file_sha256','cmtsolution_sha256','stations_sha256','ulvz_file_sha256')}},indent=2)+'\n')
 if selected and selected-{x['run_id'] for x in rows(cfg['paths']['manifest'])}:raise SystemExit('unknown run_id in --run-id')
 print(json.dumps({'source':str(source) if source else None,'created':created,'count':len(created),'dry_run':a.dry_run,'refresh_lsf':a.refresh_lsf,'rebuild_inactive':a.rebuild_inactive},indent=2))
if __name__=='__main__':main()
