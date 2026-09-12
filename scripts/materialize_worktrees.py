#!/usr/bin/env python3
"""Create isolated run trees from a verified build-template source snapshot."""
from __future__ import annotations
import argparse,json,shutil
from pathlib import Path
from production_common import load_config,rows

IGNORE=shutil.ignore_patterns('.git','obj','bin','DATABASES_MPI','OUTPUT_FILES','logs','__pycache__')
def latest_source(cfg):
 builds=cfg['paths']['runtime_root']/'builds'
 candidates=[]
 for manifest in builds.glob('*/build_manifest.json') if builds.is_dir() else ():
  try:
   x=json.loads(manifest.read_text())
   if x.get('status')=='BUILT_MESHER_ONLY' and x.get('verified_commit')==cfg['source']['commit']:
    p=Path(x.get('mesher','')).parents[1]
    if (p/'configure').is_file():candidates.append((manifest.stat().st_mtime,p,manifest))
  except (OSError,json.JSONDecodeError):pass
 if not candidates:raise RuntimeError('no compatible build-template evidence; run build-template first')
 return sorted(candidates)[-1][1]
def lsf(cfg,row,run):
 ranks=str(cfg['lsf']['mpi_ranks']);ptile=str(cfg['lsf']['ptile']);queue=cfg['lsf']['mpi_queue'];jobs=str(cfg['build']['make_jobs'])
 def job(kind,exe):
  return f'''#!/usr/bin/env bash
#BSUB -J PREM3S_{row['run_id']}_{kind}
#BSUB -q {queue}
#BSUB -n {ranks}
#BSUB -R "span[ptile={ptile}]"
#BSUB -o logs/{kind}-%J.out
#BSUB -e logs/{kind}-%J.err
set -euo pipefail
cd "${{LS_SUBCWD:-$PWD}}"
[[ -x bin/{exe} ]]
mpirun -np "${{LSB_DJOB_NUMPROC:-{ranks}}}" ./bin/{exe}
'''
 (run/'mesher_lsf.bash').write_text(job('mesher','xmeshfem3D'))
 (run/'solver_lsf.bash').write_text(job('solver','xspecfem3D'))
 (run/'submit_lsf.bash').write_text(f'''#!/usr/bin/env bash
# Per-run controller. It is the only script which submits mesher/solver jobs.
set -euo pipefail
cd "${{LS_SUBCWD:-$PWD}}"; mkdir -p logs
[[ -d "{row['scratch_database_path']}" && -w "{row['scratch_database_path']}" ]]
lock=.mesh_solver_control.lock; mkdir "$lock" || {{ echo "active control lock" >&2; exit 2; }}
trap 'rmdir "$lock" 2>/dev/null || true' EXIT
jobid() {{ sed -n 's/.*Job <\\([0-9][0-9]*\\)>.*/\\1/p' | head -1; }}
state() {{ bjobs -a "$1" 2>/dev/null | awk 'NR==2 {{print $3}}'; }}
wait_done() {{ while :; do x="$(state "$1")"; case "$x" in DONE) return;; EXIT) exit 3;; *) sleep {cfg['lsf']['per_run_wait_seconds']};; esac; done; }}
make clean; make {cfg['build']['mesher_target']} -j{jobs}
MESHER_JOB_ID="$(bsub < mesher_lsf.bash | jobid)"; [[ "$MESHER_JOB_ID" =~ ^[0-9]+$ ]]
printf 'run_id={row['run_id']}\\nmesher_job_id=%s\\n' "$MESHER_JOB_ID" > run_job_ids.env
wait_done "$MESHER_JOB_ID"
make clean; make {cfg['build']['solver_target']} -j{jobs}
SOLVER_JOB_ID="$(bsub < solver_lsf.bash | jobid)"; [[ "$SOLVER_JOB_ID" =~ ^[0-9]+$ ]]
printf 'run_id={row['run_id']}\\nmesher_job_id=%s\\nsolver_job_id=%s\\n' "$MESHER_JOB_ID" "$SOLVER_JOB_ID" > run_job_ids.env
''')
 for p in (run/'mesher_lsf.bash',run/'solver_lsf.bash',run/'submit_lsf.bash'):p.chmod(0o755)
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--source',type=Path);p.add_argument('--dry-run',action='store_true');a=p.parse_args();cfg=load_config(a.config)
 source=a.source.resolve() if a.source else latest_source(cfg)
 if not (source/'configure').is_file():raise SystemExit('source tree lacks configure')
 created=[]
 for row in rows(cfg['paths']['manifest']):
  dst=cfg['paths']['run_root']/row['run_id']
  if dst.exists():
   if not (dst/'DATA/Par_file').is_file():raise SystemExit('refusing non-worktree path '+str(dst))
   continue
  created.append(row['run_id'])
  if a.dry_run:continue
  shutil.copytree(source,dst,ignore=IGNORE)
  shutil.copytree(cfg['paths']['inputs_dir']/row['run_id']/'DATA',dst/'DATA',dirs_exist_ok=True)
  (dst/'logs').mkdir(exist_ok=True)
  lsf(cfg,row,dst)
  (dst/'run_identity.json').write_text(json.dumps({'run_id':row['run_id'],'source_commit':cfg['source']['commit'],'input_hashes':{k:row[k] for k in ('par_file_sha256','cmtsolution_sha256','stations_sha256','ulvz_file_sha256')}},indent=2)+'\n')
 print(json.dumps({'source':str(source),'created':created,'count':len(created),'dry_run':a.dry_run},indent=2))
if __name__=='__main__':main()
