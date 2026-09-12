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
 root=cfg['paths']['runtime_root'];return {'root':root,'status':root/'production_status.csv','qc':root/'qc','lock':root/'controller.lock'}

def render(text, values):
 for key,value in values.items(): text=text.replace('@@'+key+'@@',str(value))
 unresolved=TOKEN.findall(text)
 if unresolved: raise ValueError('unresolved template tokens: '+', '.join(sorted(set(unresolved))))
 return text

def run_row(cfg, run_id):
 return next((x for x in rows(cfg['paths']['manifest']) if x['run_id']==run_id),None)
