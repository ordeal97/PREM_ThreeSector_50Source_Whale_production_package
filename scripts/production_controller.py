#!/usr/bin/env python3
"""The single submitting controller; stage transition is state-driven, never list-driven."""
from __future__ import annotations
import argparse,csv,fcntl,re,shutil,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
from production_common import load_config,rows,runtime

ACTIVE={'CONTROL_PEND','CONTROL_RUN','MESHER','SOLVER','QC'}
def now():return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def tool(cfg,*args):return subprocess.run([sys.executable,str(cfg['_root']/'scripts/status_csv.py'),'--status',str(runtime(cfg)['status']),*args],text=True,capture_output=True,check=False)
def state(cfg):
 with runtime(cfg)['status'].open(newline='') as f:return {x['run_id']:x for x in csv.DictReader(f)}
def update(cfg,rid,*items):
 r=tool(cfg,'update','--run-id',rid,*items)
 if r.returncode:raise RuntimeError(r.stderr or r.stdout)
def scheduler(job):
 r=subprocess.run(['bjobs','-a',job],text=True,capture_output=True)
 if len(r.stdout.splitlines())>1:
  p=r.stdout.splitlines()[1].split()
  if len(p)>2:return p[2]
 h=subprocess.run(['bhist','-l',job],text=True,capture_output=True).stdout.lower()
 return 'DONE' if 'completed <done>' in h else 'EXIT' if 'completed <exit>' in h else 'UNKNOWN'
def stage2_ready(manifest,status,cfg):
 return all(status.get(x['run_id'],{}).get('state')=='DONE' and status.get(x['run_id'],{}).get('output_qc')=='PASS' for x in manifest if x['stage']==cfg['staging']['stage1'])
def submit(cfg,row):
 run=cfg['paths']['run_root']/row['run_id'];scratch=Path(row['scratch_database_path'])
 if not (run/'submit_lsf.bash').is_file():raise RuntimeError('missing materialized worktree '+row['run_id'])
 root=cfg['paths']['scratch_root'].resolve(strict=False)
 if scratch.resolve(strict=False)!=root/row['run_id']/'DATABASES_MPI':raise RuntimeError('manifest scratch escapes configured root')
 scratch.mkdir(parents=True,exist_ok=True)
 r=subprocess.run(['bash','-lc','bsub < submit_lsf.bash'],cwd=run,text=True,capture_output=True);m=re.search(r'Job <(\d+)>',r.stdout)
 if r.returncode or not m:update(cfg,row['run_id'],'state=EXIT','reason=bsub_submission_failed');return
 update(cfg,row['run_id'],'state=CONTROL_PEND','control_job_id='+m.group(1),'submit_time='+now())
def monitor(cfg,row,status):
 rid=row['run_id'];run=cfg['paths']['run_root']/rid;metadata=run/'run_job_ids.env'
 if metadata.is_file():
  values=dict(x.split('=',1) for x in metadata.read_text().splitlines() if '=' in x)
  for key in ('mesher_job_id','solver_job_id'):
   if values.get(key):update(cfg,rid,key+'='+values[key],'state='+('SOLVER' if key.startswith('solver') else 'MESHER'))
 status=state(cfg)[rid]
 if status.get('solver_job_id'):
  x=scheduler(status['solver_job_id'])
  if x=='DONE':
   update(cfg,rid,'state=QC');q=subprocess.run([sys.executable,str(cfg['_root']/'scripts/runtime_qc.py'),'--run-id',rid,'--run-dir',str(run)],text=True,capture_output=True)
   if q.returncode:update(cfg,rid,'state=QC_FAIL','output_qc=FAIL','reason=output_qc_failed')
   elif cfg['qc']['cleanup_after_output_qc_pass']:
    update(cfg,rid,'state=DONE','output_qc=PASS','finish_time='+now())
    clean=subprocess.run([sys.executable,str(cfg['_root']/'scripts/cleanup_scratch.py'),'--config',str(cfg['_path']),'--run-id',rid,'--execute'],text=True,capture_output=True)
    update(cfg,rid,'scratch_cleaned='+('true' if not clean.returncode else 'false'),'reason='+('' if not clean.returncode else 'scratch_cleanup_failed'))
   else:update(cfg,rid,'state=DONE','output_qc=PASS','finish_time='+now(),'scratch_cleaned=false')
  elif x=='EXIT':update(cfg,rid,'state=EXIT','reason=solver_exit')
 elif status.get('control_job_id'):
  x=scheduler(status['control_job_id'])
  if x=='RUN':update(cfg,rid,'state=CONTROL_RUN')
  elif x=='EXIT':update(cfg,rid,'state=EXIT','reason=control_exit')
  elif x=='DONE':update(cfg,rid,'state=EXIT','reason=control_done_without_solver')
def loop(cfg,manifest,once):
 for command in ('bsub','bjobs','bhist'):
  if not shutil.which(command):raise RuntimeError(command+' unavailable')
 while True:
  before=state(cfg)
  for row in manifest:
   if before[row['run_id']]['state'] in ACTIVE:monitor(cfg,row,before)
  current=state(cfg);active=sum(x['state'] in ACTIVE for x in current.values());open_stage2=stage2_ready(manifest,current,cfg)
  for row in manifest:
   if active>=cfg['lsf']['max_active_runs']:break
   if current[row['run_id']]['state']!='NOT_SUBMITTED' or (row['stage']==cfg['staging']['stage2'] and not open_stage2):continue
   submit(cfg,row);active+=1
  if once:return
  current=state(cfg)
  if not any(x['state'] in ACTIVE or x['state']=='NOT_SUBMITTED' for x in current.values()):return
  time.sleep(cfg['lsf']['controller_poll_seconds'])
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--action',choices=('run','resume','status'),required=True);p.add_argument('--retry');p.add_argument('--once',action='store_true');a=p.parse_args();cfg=load_config(a.config);rt=runtime(cfg);rt['root'].mkdir(parents=True,exist_ok=True)
 if not rt['status'].exists():tool(cfg,'init','--template',str(cfg['paths']['status_template']))
 if a.action=='status':print(rt['status'].read_text(),end='');return
 if a.retry:
  x=state(cfg).get(a.retry)
  if not x or x['state'] not in {'EXIT','QC_FAIL'}:raise SystemExit('--retry requires EXIT or QC_FAIL')
  stamp=now().replace(':','').replace('-','')
  run=cfg['paths']['run_root']/a.retry;archive=cfg['paths']['runtime_root']/'failed_attempts'/f'{a.retry}.{stamp}'
  scratch=cfg['paths']['scratch_root']/a.retry;scratch_archive=cfg['paths']['scratch_root']/f'{a.retry}.attempt{int(x.get("attempt") or 0)}.{stamp}'
  if run.exists():
   archive.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(run),str(archive))
  if scratch.exists():shutil.move(str(scratch),str(scratch_archive))
  materialize=subprocess.run([sys.executable,str(cfg['_root']/'scripts/materialize_worktrees.py'),'--config',str(cfg['_path'])],text=True,capture_output=True)
  if materialize.returncode:raise SystemExit('retry archive succeeded but worktree materialization failed: '+materialize.stderr)
  update(cfg,a.retry,'state=NOT_SUBMITTED','output_qc=','reason=explicit_retry','attempt='+str(int(x.get('attempt') or 0)+1))
 with rt['lock'].open('a+') as f:
  try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise SystemExit('another controller holds lock')
  loop(cfg,rows(cfg['paths']['manifest']),a.once)
if __name__=='__main__':main()
