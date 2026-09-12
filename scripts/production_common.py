"""Shared, conservative helpers for the Whale production runtime."""
from __future__ import annotations
import csv, hashlib, re, tomllib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TOKEN=re.compile(r'@@[A-Z0-9_]+@@')

def sha(path: Path) -> str:
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def rows(path: Path):
 with path.open(newline='',encoding='utf-8') as f:return list(csv.DictReader(f))

def load_config(path: Path):
 if path.resolve()!=ROOT/'config/production.toml': raise ValueError('only frozen config is accepted; copy package and re-preflight after edits')
 with path.open('rb') as f: cfg=tomllib.load(f)
 for key in ('run_root','scratch_root','manifest','inputs_dir','runtime_root','status_template'):
  if key not in cfg['paths']: raise ValueError('missing paths.'+key)
 for key in ('mpi_ranks','ptile','max_active_runs','controller_poll_seconds','per_run_wait_seconds'):
  if int(cfg['lsf'][key])<1: raise ValueError('invalid lsf.'+key)
 if int(cfg['lsf']['mpi_ranks'])%int(cfg['lsf']['ptile']): raise ValueError('mpi_ranks must divide ptile')
 for key in ('python_bin',):
  if not cfg['runtime'].get(key): raise ValueError('missing runtime.'+key)
 for key in ('oneapi_setup','mpi_launcher','modules'):
  if key not in cfg['environment']: raise ValueError('missing environment.'+key)
 if not isinstance(cfg['environment']['modules'],list) or not cfg['environment']['modules']: raise ValueError('environment.modules must be non-empty')
 for key in ('run_root','runtime_root','inputs_dir','manifest','status_template'):
  value=Path(cfg['paths'][key]);cfg['paths'][key]=value if value.is_absolute() else ROOT/value
 cfg['paths']['scratch_root']=Path(cfg['paths']['scratch_root'])
 cfg['_root']=ROOT;cfg['_path']=path.resolve();return cfg

def runtime(cfg):
 root=cfg['paths']['runtime_root'];return {'root':root,'status':root/'production_status.csv','qc':root/'qc','failed':root/'failed_runs.csv','diagnostics':root/'failed_diagnostics','lock':root/'controller.lock'}

def render(text, values):
 for key,value in values.items(): text=text.replace('@@'+key+'@@',str(value))
 unresolved=TOKEN.findall(text)
 if unresolved: raise ValueError('unresolved template tokens: '+', '.join(sorted(set(unresolved))))
 return text

def run_row(cfg, run_id):
 return next((x for x in rows(cfg['paths']['manifest']) if x['run_id']==run_id),None)

def worktree_errors(cfg,row):
 """Compare an existing runtime tree with the frozen portable package."""
 run=cfg['paths']['run_root']/row['run_id'];errors=[]
 if not run.is_dir():return ['worktree missing']
 for name in ('Par_file','CMTSOLUTION','STATIONS','ulvz_s40rts.par'):
  actual=run/'DATA'/name;expected=cfg['paths']['inputs_dir']/row['run_id']/'DATA'/name
  if not actual.is_file() or not expected.is_file() or sha(actual)!=sha(expected):errors.append('DATA/'+name+' differs from frozen input')
 for name in ('submit_lsf.bash','mesher_lsf.bash','solver_lsf.bash'):
  actual=run/name;expected=cfg['_root']/'rendered_lsf'/row['run_id']/name
  if not actual.is_file() or not expected.is_file() or sha(actual)!=sha(expected):errors.append(name+' differs from rendered LSF')
 identity=run/'run_identity.json'
 try:
  import json
  value=json.loads(identity.read_text())
  expected={key:row[key] for key in ('par_file_sha256','cmtsolution_sha256','stations_sha256','ulvz_file_sha256')}
  if value.get('run_id')!=row['run_id'] or value.get('source_commit')!=cfg['source']['commit'] or value.get('input_hashes')!=expected:errors.append('run_identity.json differs from frozen identity')
 except (OSError,ValueError):errors.append('run_identity.json missing or invalid')
 return errors
