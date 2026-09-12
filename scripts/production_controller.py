#!/usr/bin/env python3
"""The single submitting controller; stage transition is state-driven, never list-driven."""
from __future__ import annotations
import argparse,csv,fcntl,json,os,re,shutil,subprocess,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
from production_common import load_config,rows,runtime

ACTIVE={'CONTROL_PEND','CONTROL_RUN','MESHER','SOLVER','QC','CLEANUP_PENDING'}
FAILURES={'EXIT','QC_FAIL'}
JOB_KEYS=('control_job_id','mesher_job_id','solver_job_id')
FAILED_FIELDS=('run_id','stage','failure_stage','reason','control_job_id','mesher_job_id','solver_job_id','attempt','failure_time','lsf_final_states','scratch_size_bytes','cleanup_time','scratch_cleaned','cleanup_error')
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
def scratch_target(cfg,row):
 root=cfg['paths']['scratch_root'].resolve(strict=False);target=root/row['run_id'];declared=Path(row['scratch_database_path']).resolve(strict=False)
 if target.parent.resolve(strict=False)!=root or declared!=target/'DATABASES_MPI':raise RuntimeError('manifest scratch escapes configured root')
 return root,target
def scratch_size(path):
 total=0
 if path.exists() and not path.is_symlink():
  for base,_,files in os.walk(path):
   for name in files:
    p=Path(base)/name
    if not p.is_symlink():
     try:total+=p.stat().st_size
     except OSError:pass
 return total
def job_ids(run,status):
 result={key:status.get(key,'') for key in JOB_KEYS};meta=run/'run_job_ids.env'
 if meta.is_file():
  for raw in meta.read_text(errors='replace').splitlines():
   key,sep,value=raw.partition('=')
   if sep and key in result and value:result[key]=value
 return result
def job_states(run,status):return {key:scheduler(value) for key,value in job_ids(run,status).items() if value}
def all_terminal(states):return all(value in {'DONE','EXIT'} for value in states.values())
def write_failed(cfg,row,status,states,size):
 path=runtime(cfg)['failed'];path.parent.mkdir(parents=True,exist_ok=True);existing=[]
 if path.is_file():
  with path.open(newline='') as f:existing=list(csv.DictReader(f))
 item={key:'' for key in FAILED_FIELDS};item.update({'run_id':row['run_id'],'stage':row['stage'],'failure_stage':status.get('failure_stage',''),'reason':status.get('reason',''),'attempt':status.get('attempt','0'),'failure_time':status.get('failure_time',''),'lsf_final_states':json.dumps(states,sort_keys=True),'scratch_size_bytes':str(size),'cleanup_time':status.get('cleanup_time',''),'scratch_cleaned':status.get('scratch_cleaned',''),'cleanup_error':status.get('cleanup_error','')})
 item.update(job_ids(cfg['paths']['run_root']/row['run_id'],status));key=(item['run_id'],item['attempt']);existing=[x for x in existing if (x.get('run_id'),x.get('attempt'))!=key];existing.append(item)
 fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=path.name+'.',text=True)
 with os.fdopen(fd,'w',newline='') as f:w=csv.DictWriter(f,fieldnames=FAILED_FIELDS);w.writeheader();w.writerows(existing)
 os.replace(tmp,path)
def preserve_diagnostics(cfg,row,status):
 run=cfg['paths']['run_root']/row['run_id'];dest=runtime(cfg)['diagnostics']/f"{row['run_id']}.attempt{status.get('attempt') or '0'}";dest.mkdir(parents=True,exist_ok=True)
 for name in ('run_job_ids.env',):
  p=run/name
  if p.is_file():shutil.copy2(p,dest/name)
 p=run/'logs'
 if p.is_dir():shutil.copytree(p,dest/'logs',dirs_exist_ok=True)
 output=run/'OUTPUT_FILES'
 if output.is_dir():
  out=dest/'OUTPUT_FILES';out.mkdir(parents=True,exist_ok=True)
  for p in output.iterdir():
   if p.is_file() and (p.suffix.lower() in {'.txt','.csv','.json','.md'} or 'ulvz' in p.name.lower()):shutil.copy2(p,out/p.name)
 qc=runtime(cfg)['qc']/f"{row['run_id']}.attempt{status.get('attempt') or '0'}.json"
 if qc.is_file():shutil.copy2(qc,dest/qc.name)
def remove_scratch(cfg,row):
 _,target=scratch_target(cfg,row)
 if target.is_symlink():raise RuntimeError('refusing symlink scratch target')
 if target.exists():shutil.rmtree(target)
def fail(cfg,row,stage,reason):
 status=state(cfg)[row['run_id']];when=status.get('failure_time') or now();failed_state='QC_FAIL' if stage=='QC' else 'EXIT'
 update(cfg,row['run_id'],'state='+failed_state,'output_qc='+('FAIL' if stage=='QC' else status.get('output_qc','')),'reason='+reason,'failure_stage='+stage,'failure_time='+when)
 process_failure(cfg,row)
def process_failure(cfg,row):
 status=state(cfg)[row['run_id']];run=cfg['paths']['run_root']/row['run_id'];states=job_states(run,status);_,target=scratch_target(cfg,row);size=scratch_size(target)
 write_failed(cfg,row,status,states,size)
 if not all_terminal(states):return False
 try:preserve_diagnostics(cfg,row,status)
 except Exception as exc:
  update(cfg,row['run_id'],'scratch_cleaned=false','cleanup_error=diagnostic_preservation_failed:'+str(exc));write_failed(cfg,row,state(cfg)[row['run_id']],states,size);return False
 try:remove_scratch(cfg,row)
 except Exception as exc:
  update(cfg,row['run_id'],'scratch_cleaned=false','cleanup_error=scratch_cleanup_failed:'+str(exc));write_failed(cfg,row,state(cfg)[row['run_id']],states,size);return False
 update(cfg,row['run_id'],'scratch_cleaned=true','cleanup_time='+now(),'cleanup_error=');write_failed(cfg,row,state(cfg)[row['run_id']],states,size);return True
def process_success_cleanup(cfg,row):
 status=state(cfg)[row['run_id']];states=job_states(cfg['paths']['run_root']/row['run_id'],status)
 if not all_terminal(states):return False
 try:remove_scratch(cfg,row)
 except Exception as exc:
  update(cfg,row['run_id'],'state=DONE','scratch_cleaned=false','cleanup_error=scratch_cleanup_failed:'+str(exc));return False
 update(cfg,row['run_id'],'state=DONE','scratch_cleaned=true','cleanup_time='+now(),'cleanup_error=');return True
def submission_blocked(status):return any(x.get('scratch_cleaned')=='false' for x in status.values())
def counts_as_active(status,states):return status.get('state') in ACTIVE or (status.get('state') in FAILURES and not all_terminal(states))
def submit(cfg,row):
 run=cfg['paths']['run_root']/row['run_id'];_,scratch=scratch_target(cfg,row)
 if not (run/'submit_lsf.bash').is_file():raise RuntimeError('missing materialized worktree '+row['run_id'])
 scratch.mkdir(parents=True,exist_ok=True)
 r=subprocess.run(['bash','-lc','bsub < submit_lsf.bash'],cwd=run,text=True,capture_output=True);m=re.search(r'Job <(\d+)>',r.stdout)
 if r.returncode or not m:fail(cfg,row,'SUBMIT','bsub_submission_failed');return
 update(cfg,row['run_id'],'state=CONTROL_PEND','control_job_id='+m.group(1),'submit_time='+now())
def monitor(cfg,row):
 rid=row['run_id'];run=cfg['paths']['run_root']/rid;status=state(cfg)[rid]
 if status['state'] in FAILURES:process_failure(cfg,row);return
 if status['state']=='CLEANUP_PENDING':process_success_cleanup(cfg,row);return
 ids=job_ids(run,status)
 for key,value in ids.items():
  if value and value!=status.get(key,''):update(cfg,rid,key+'='+value,'state='+('SOLVER' if key.startswith('solver') else 'MESHER'))
 status=state(cfg)[rid];states=job_states(run,status);control=states.get('control_job_id');mesher=states.get('mesher_job_id');solver=states.get('solver_job_id')
 if control=='EXIT':fail(cfg,row,'CONTROL','control_exit');return
 if solver=='EXIT':fail(cfg,row,'SOLVER','solver_exit');return
 if mesher=='EXIT' and not solver:fail(cfg,row,'MESHER','mesher_exit');return
 if solver=='DONE':
  update(cfg,rid,'state=QC');q=subprocess.run([sys.executable,str(cfg['_root']/'scripts/runtime_qc.py'),'--run-id',rid,'--run-dir',str(run)],text=True,capture_output=True);qc=runtime(cfg)['qc'];qc.mkdir(parents=True,exist_ok=True);(qc/f"{rid}.attempt{status.get('attempt') or '0'}.json").write_text(json.dumps({'returncode':q.returncode,'stdout':q.stdout,'stderr':q.stderr})+'\n')
  if q.returncode:fail(cfg,row,'QC','output_qc_failed')
  elif cfg['qc']['cleanup_after_output_qc_pass']:
   update(cfg,rid,'state=CLEANUP_PENDING','output_qc=PASS','finish_time='+now());process_success_cleanup(cfg,row)
  else:update(cfg,rid,'state=DONE','output_qc=PASS','finish_time='+now(),'scratch_cleaned=false')
 elif control=='RUN':update(cfg,rid,'state=CONTROL_RUN')
 elif control=='DONE' and not solver:fail(cfg,row,'CONTROL','control_done_without_solver')
def stage1_failed(manifest,status,cfg):return any(status.get(x['run_id'],{}).get('state') in FAILURES for x in manifest if x['stage']==cfg['staging']['stage1'])
def retry_ready(status,states,scratch):return status.get('state') in FAILURES and all_terminal(states) and status.get('scratch_cleaned')=='true' and not scratch.exists()
def loop(cfg,manifest,once):
 for command in ('bsub','bjobs','bhist'):
  if not shutil.which(command):raise RuntimeError(command+' unavailable')
 while True:
  before=state(cfg)
  for row in manifest:
   if before[row['run_id']]['state'] in ACTIVE|FAILURES:monitor(cfg,row)
  current=state(cfg);active=0
  for row in manifest:
   status=current[row['run_id']]
   active+=counts_as_active(status,job_states(cfg['paths']['run_root']/row['run_id'],status) if status['state'] in FAILURES else {})
  open_stage2=stage2_ready(manifest,current,cfg)
  if not submission_blocked(current):
   for row in manifest:
    if active>=cfg['lsf']['max_active_runs']:break
    if current[row['run_id']]['state']!='NOT_SUBMITTED' or (row['stage']==cfg['staging']['stage2'] and not open_stage2):continue
    submit(cfg,row);active+=1
  if once:return
  current=state(cfg)
  if submission_blocked(current) and not any(x['state'] in ACTIVE for x in current.values()):return
  if stage1_failed(manifest,current,cfg) and not any(x['state'] in ACTIVE for x in current.values()):return
  if not any(x['state'] in ACTIVE or x['state']=='NOT_SUBMITTED' for x in current.values()):return
  time.sleep(cfg['lsf']['controller_poll_seconds'])
def retry(cfg,rid):
 status=state(cfg).get(rid)
 if not status:raise SystemExit('--retry requires EXIT or QC_FAIL')
 row=next(x for x in rows(cfg['paths']['manifest']) if x['run_id']==rid);states=job_states(cfg['paths']['run_root']/rid,status);_,scratch=scratch_target(cfg,row)
 if not retry_ready(status,states,scratch):raise SystemExit('retry requires terminal jobs and cleaned old scratch')
 stamp=now().replace(':','').replace('-','');run=cfg['paths']['run_root']/rid;archive=cfg['paths']['runtime_root']/'failed_attempts'/f'{rid}.{stamp}'
 if run.exists():archive.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(run),str(archive))
 materialize=subprocess.run([sys.executable,str(cfg['_root']/'scripts/materialize_worktrees.py'),'--config',str(cfg['_path'])],text=True,capture_output=True)
 if materialize.returncode:raise SystemExit('retry worktree materialization failed: '+materialize.stderr)
 update(cfg,rid,'state=NOT_SUBMITTED','output_qc=','reason=explicit_retry','attempt='+str(int(status.get('attempt') or 0)+1),'control_job_id=','mesher_job_id=','solver_job_id=','submit_time=','finish_time=','failure_stage=','failure_time=','scratch_cleaned=','cleanup_time=','cleanup_error=')
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--action',choices=('run','resume','status'),required=True);p.add_argument('--retry');p.add_argument('--once',action='store_true');a=p.parse_args();cfg=load_config(a.config);rt=runtime(cfg);rt['root'].mkdir(parents=True,exist_ok=True)
 if not rt['status'].exists():tool(cfg,'init','--template',str(cfg['paths']['status_template']))
 if a.action=='status':print(rt['status'].read_text(),end='');return
 with rt['lock'].open('a+') as f:
  try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise SystemExit('another controller holds lock')
  if a.retry:retry(cfg,a.retry)
  loop(cfg,rows(cfg['paths']['manifest']),a.once)
if __name__=='__main__':main()
