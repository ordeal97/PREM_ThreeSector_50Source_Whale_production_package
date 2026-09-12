#!/usr/bin/env python3
"""Create isolated run trees from a verified build-template source snapshot."""
from __future__ import annotations
import argparse,json,shlex,shutil,tomllib
from pathlib import Path
from production_common import load_config,rows

IGNORE=shutil.ignore_patterns('.git','obj','bin','DATABASES_MPI','OUTPUT_FILES','logs','__pycache__')
RUNTIME_DIRS=('obj','bin','OUTPUT_FILES','logs')
def ensure_runtime_dirs(target):
 for name in RUNTIME_DIRS:(target/name).mkdir(parents=True,exist_ok=True)
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
 return '\n'.join(['module purge',f'if [[ -z "${{I_MPI_ROOT:-}}" ]] || ! command -v mpiifort >/dev/null 2>&1; then source "{cfg["environment"]["oneapi_setup"]}"; fi',*[f'module load {x}' for x in cfg['environment']['modules']]])
def lsf(cfg,row,run,module_commands=()):
 ranks=str(cfg['lsf']['mpi_ranks']);ptile=str(cfg['lsf']['ptile']);queue=cfg['lsf']['mpi_queue'];jobs=str(cfg['build']['make_jobs']);modules=environment_setup(cfg);workdir='${'+'LS_SUBCWD:-$PWD}';launcher=cfg['environment']['mpi_launcher']
 def job(kind,exe):
  return f'''#!/usr/bin/env bash
#BSUB -J PREM3S_{row['run_id']}_{kind}
#BSUB -q {queue}
#BSUB -n {ranks}
#BSUB -R "span[ptile={ptile}]"
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
# Per-run controller: compile mesher, submit/wait mesh, compile/submit solver.
set -euo pipefail
cd "{workdir}"; mkdir -p logs
{modules}
[[ -d "{row['scratch_database_path']}" && -w "{row['scratch_database_path']}" ]]
lock=.mesh_solver_control.lock; mkdir "$lock" || {{ echo "active control lock" >&2; exit 2; }}
trap 'rmdir "$lock" 2>/dev/null || true' EXIT
jobid() {{ awk -F '[<>]' '/Job </ {{print $2; exit}}'; }}
state() {{ bjobs -a "$1" 2>/dev/null | awk 'NR==2 {{print $3}}'; }}
wait_done() {{ unknown=0; while :; do x="$(state "$1")"; case "$x" in DONE) return;; EXIT) exit 3;; PEND|RUN|WAIT|PSUSP|USUSP|SSUSP) unknown=0;; *) unknown=$((unknown+1)); [[ "$unknown" -lt 12 ]] || exit 4;; esac; sleep {cfg['lsf']['per_run_wait_seconds']}; done; }}
make clean; make {cfg['build']['mesher_target']} -j{jobs}
MESHER_JOB_ID="$(bsub < mesher_lsf.bash | jobid)"; [[ "$MESHER_JOB_ID" =~ ^[0-9]+$ ]]
printf 'run_id={row['run_id']}\nmesher_job_id=%s\n' "$MESHER_JOB_ID" > run_job_ids.env
wait_done "$MESHER_JOB_ID"
make clean; make {cfg['build']['solver_target']} -j{jobs}
SOLVER_JOB_ID="$(bsub < solver_lsf.bash | jobid)"; [[ "$SOLVER_JOB_ID" =~ ^[0-9]+$ ]]
printf 'run_id={row['run_id']}\nmesher_job_id=%s\nsolver_job_id=%s\n' "$MESHER_JOB_ID" "$SOLVER_JOB_ID" > run_job_ids.env
''')
 for path in (run/'mesher_lsf.bash',run/'solver_lsf.bash',run/'submit_lsf.bash'):path.chmod(0o755)
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--source',type=Path);p.add_argument('--dry-run',action='store_true');a=p.parse_args();cfg=load_config(a.config)
 if a.source:source=a.source.resolve();modules=default_modules(cfg)
 else:source,_,modules=latest_build(cfg)
 if not (source/'configure').is_file():raise SystemExit('source tree lacks configure')
 created=[]
 for row in rows(cfg['paths']['manifest']):
  target=cfg['paths']['run_root']/row['run_id']
  if target.exists():
   if not (target/'DATA/Par_file').is_file():raise SystemExit('refusing non-worktree path '+str(target))
   ensure_runtime_dirs(target)
   continue
  created.append(row['run_id'])
  if a.dry_run:continue
  shutil.copytree(source,target,ignore=IGNORE);shutil.copytree(cfg['paths']['inputs_dir']/row['run_id']/'DATA',target/'DATA',dirs_exist_ok=True)
  ensure_runtime_dirs(target);lsf(cfg,row,target,modules or default_modules(cfg))
  (target/'run_identity.json').write_text(json.dumps({'run_id':row['run_id'],'source_commit':cfg['source']['commit'],'input_hashes':{k:row[k] for k in ('par_file_sha256','cmtsolution_sha256','stations_sha256','ulvz_file_sha256')}},indent=2)+'\n')
 print(json.dumps({'source':str(source),'created':created,'count':len(created),'dry_run':a.dry_run},indent=2))
if __name__=='__main__':main()
