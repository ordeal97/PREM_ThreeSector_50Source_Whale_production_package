#!/usr/bin/env python3
"""Portable package CLI. Only submit delegates to Whale's bsub."""
from __future__ import annotations
import argparse,json,shlex,shutil,subprocess,sys
from datetime import datetime, timezone
from pathlib import Path
from preflight import ROOT,digest,tree_digest,run_preflight
from production_common import environment_setup,load_config,rows,runtime,worktree_errors
def hashes():return {'manifest_hash':digest(ROOT/'production_run_manifest.csv'),'config_hash':digest(ROOT/'config/production.toml'),'contract_hash':digest(ROOT/'config/contracts/prem_three_sector.toml'),'specfem_template_hash':tree_digest(ROOT/'specfem_template'),'rendered_input_hash':tree_digest(ROOT/'production_inputs'),'rendered_lsf_hash':tree_digest(ROOT/'rendered_lsf'),'runtime_script_hash':tree_digest(ROOT/'scripts')}
def gate():
 p=ROOT/'preflight/preflight_summary.json'
 if not p.is_file():raise RuntimeError('preflight summary missing')
 s=json.loads(p.read_text());changed=[k for k,v in hashes().items() if s.get(k)!=v]
 if s.get('status')!='PASS' or changed:raise RuntimeError('submit refused: preflight invalid/stale '+','.join(changed))
def materialized_gate(cfg):
 errors=[]
 for row in rows(cfg['paths']['manifest']):
  for message in worktree_errors(cfg,row):errors.append(row['run_id']+': '+message)
 if errors:raise RuntimeError('submit refused: worktree verification failed; '+'; '.join(errors))
def control_lsf(cfg,action,retry=None):
 target=runtime(cfg)['root']/'rendered_lsf'/f'production_{action}.lsf';target.parent.mkdir(parents=True,exist_ok=True);(runtime(cfg)['root']/'logs').mkdir(parents=True,exist_ok=True)
 retry_arg='' if not retry else ' --retry '+retry
 target.write_text(f'''#!/usr/bin/env bash
#BSUB -J {cfg['lsf']['control_job_prefix']}_PREM3S_{action}
#BSUB -q {cfg['lsf']['control_queue']}
#BSUB -n {cfg['lsf']['control_ranks']}
#BSUB -R "span[hosts={cfg['lsf']['control_hosts']}]"
#BSUB -L /bin/bash
#BSUB -o {runtime(cfg)['root']}/logs/{action}-%J.out
#BSUB -e {runtime(cfg)['root']}/logs/{action}-%J.err
set -euo pipefail
exec {cfg['runtime']['python_bin']} {ROOT}/scripts/production_controller.py --config {cfg['_path']} --action {action}{retry_arg}
''');return target
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',type=Path,default=ROOT/'config/production.toml');s=p.add_subparsers(dest='cmd',required=True)
 for name in ('validate','preflight','dry-run','deployment-check','mock-submission','render','materialize','status','resume','submit','cleanup','asdf-smoke','linkage-audit'):s.add_parser(name)
 b=s.add_parser('build-template');b.add_argument('--reference-build',type=Path,required=True);b.add_argument('--source-tree',type=Path,help='离线本地 ulvz_specfem 源码树');b.add_argument('--inspect-only',action='store_true');b.add_argument('--jobs',type=int,default=1)
 s.choices['asdf-smoke'].add_argument('--source-dir',type=Path,required=True)
 s.choices['linkage-audit'].add_argument('--binary',type=Path,required=True)
 s.choices['linkage-audit'].add_argument('--require-asdf',action='store_true')
 s.choices['linkage-audit'].add_argument('--output',type=Path)
 s.choices['materialize'].add_argument('--rebuild-inactive',action='store_true')
 for name in ('resume','cleanup'):s.choices[name].add_argument('--run-id')
 s.choices['cleanup'].add_argument('--execute',action='store_true')
 a=p.parse_args();cfg=load_config(a.config)
 if a.cmd in {'validate','preflight'}:
  summary,errors=run_preflight(write_outputs=a.cmd=='preflight');print(a.cmd.upper(),summary['status']);raise SystemExit(bool(errors))
 if a.cmd=='build-template':
  from build_template import run_build;run_build(ROOT,a.reference_build,a.inspect_only,a.jobs,a.source_tree);return
 if a.cmd=='dry-run':
  _,errors=run_preflight(False);print(json.dumps({'status':'FAIL' if errors else 'PASS','runs':100,'max_active_runs':cfg['lsf']['max_active_runs'],'stage_barrier':'all 50 B0 DONE + QC PASS','bsub_called':False,'mesher_called':False,'solver_called':False},indent=2));raise SystemExit(bool(errors))
 if a.cmd=='deployment-check':
  subprocess.run([sys.executable,str(ROOT/'scripts/deployment_check.py'),'--config',str(a.config)],check=True);return
 if a.cmd=='asdf-smoke':
  target=runtime(cfg)['root']/'asdf_smoke';target.mkdir(parents=True,exist_ok=True)
  run_dir=target/('attempt-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
  command=' '.join(shlex.quote(str(x)) for x in (cfg['runtime']['python_bin'],ROOT/'scripts/asdf_smoke.py','--source-dir',a.source_dir.resolve(),'--output-dir',run_dir,'--config-hash',digest(ROOT/'config/production.toml')))
  setup='set -euo pipefail\n'+environment_setup(cfg['environment'])+'\nexec '+command
  result=subprocess.run(['bash','-lc',setup],check=False)
  summary=json.loads((run_dir/'summary.json').read_text())
  (target/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
  if result.returncode:raise RuntimeError('ASDF/HDF5 smoke failed; see '+str(run_dir/'summary.json'))
  return
 if a.cmd=='linkage-audit':
  from linkage_audit import inspect,raw_log_path
  report=inspect(a.binary,a.require_asdf,cfg,raw_log_path(a.output) if a.output else None);encoded=json.dumps(report,indent=2)+'\n'
  if a.output:
   a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(encoded)
  print(encoded,end='');raise SystemExit(report['status']!='PASS')
 if a.cmd=='render':
  subprocess.run([sys.executable,str(ROOT/'scripts/render_lsf.py'),'--config',str(a.config)],check=True);return
 if a.cmd=='materialize':
  gate();command=[sys.executable,str(ROOT/'scripts/materialize_worktrees.py'),'--config',str(a.config)]
  if a.rebuild_inactive:command.append('--rebuild-inactive')
  subprocess.run(command,check=True);return
 if a.cmd=='status':
  subprocess.run([sys.executable,str(ROOT/'scripts/production_controller.py'),'--config',str(a.config),'--action','status'],check=True);return
 if a.cmd=='cleanup':
  if not a.run_id:raise SystemExit('cleanup requires --run-id')
  command=[sys.executable,str(ROOT/'scripts/cleanup_scratch.py'),'--config',str(a.config),'--run-id',a.run_id]
  if a.execute:command.append('--execute')
  subprocess.run(command,check=True);return
 if a.cmd=='resume':
  gate()
  if not shutil.which('bsub'):raise RuntimeError('resume refused: bsub unavailable')
  target=control_lsf(cfg,'resume',a.run_id);subprocess.run(['bsub'],input=target.read_text(),text=True,check=True);return
 if a.cmd=='mock-submission':
  gate();subprocess.run([sys.executable,str(ROOT/'scripts/mock_submission.py')],check=True);return
 gate()
 if not shutil.which('bsub'):raise RuntimeError('submit refused: bsub unavailable')
 if not (runtime(cfg)['root']/'production_status.csv').exists():raise RuntimeError('submit refused: materialize and deployment-check first')
 materialized_gate(cfg)
 target=control_lsf(cfg,'run');subprocess.run(['bsub'],input=target.read_text(),text=True,check=True)
if __name__=='__main__':main()
