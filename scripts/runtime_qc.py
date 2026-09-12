#!/usr/bin/env python3
"""Runtime provenance and waveform QC for the frozen 0/3-body design."""
from __future__ import annotations
import argparse,csv,hashlib,json,math,re
from pathlib import Path
from production_common import ROOT,rows
def num(v):
 value=float(v)
 if not math.isfinite(value):raise ValueError('non-finite numeric value')
 return value
def station_ids(path):
 return {f'{parts[1]}.{parts[0]}' for raw in path.read_text().splitlines() if (parts:=raw.split())}
def payload(path,expected_stations):
 import h5py,numpy as np
 result={'errors':[],'hashes':{}}
 with h5py.File(path,'r') as f:
  found=[]
  def visit(name,obj):
   if isinstance(obj,h5py.Dataset) and re.search(r'\.BX[ENZ]__(?:[^/]+)$',name):found.append((name,obj))
  f.visititems(visit);by_station={}
  for name,_ in found:by_station.setdefault(name.split('/')[1],set()).add(re.search(r'\.BX([ENZ])__',name).group(1))
  result['trace_count']=len(found);result['stations']=len(by_station);result['station_ids']=set(by_station);result['components']=sorted({re.search(r'\.BX([ENZ])__',x[0]).group(1) for x in found})
  rates=set();npts=set()
  for name,data in found:
   if data.ndim!=1:result['errors'].append(name+' not 1-D');continue
   v=data[...];npts.add(len(v));rates.add(float(data.attrs.get('sampling_rate',float('nan'))))
   if not np.isfinite(v).all():result['errors'].append(name+' contains NaN/Inf')
   result['hashes'][name]=hashlib.sha256(v.tobytes()).hexdigest()
  result['npts']=sorted(npts);result['rates']=sorted(rates)
 if result['trace_count']!=1530:result['errors'].append('trace count != 1530')
 if result['stations']!=510:result['errors'].append('station count != 510')
 if result['components']!=['E','N','Z']:result['errors'].append('components != E,N,Z')
 if result['station_ids']!=expected_stations:result['errors'].append('ASDF station identity differs from STATIONS')
 if any(value!={'E','N','Z'} for value in by_station.values()):result['errors'].append('not every station has exactly E,N,Z')
 if result['npts']!=[25400]:result['errors'].append('npts != 25400')
 if result['rates']!=[10.0]:result['errors'].append('sampling rate != 10 Hz')
 return result
def main():
 p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--baseline-run-dir',type=Path);a=p.parse_args();errors=[]
 manifest=next((x for x in rows(ROOT/'production_run_manifest.csv') if x['run_id']==a.run_id),None)
 if not manifest:raise SystemExit('unknown run id')
 want=sorted([x for x in rows(ROOT/'catalogs/ulvz_instance_manifest.csv') if x['run_id']==a.run_id],key=lambda x:int(x['body_index']))
 norm=a.run_dir/'OUTPUT_FILES/ulvz_normalized.csv';expected_stations=station_ids(a.run_dir/'DATA/STATIONS')
 if not norm.is_file():errors.append('ulvz_normalized.csv missing')
 else:
  got=rows(norm);expected=int(manifest['n_ulvz'])
  if expected==0:
   if len(got)!=1 or got[0].get('background')!='PREM' or str(got[0].get('n_ulvz','')) not in {'0','0.0'} or got[0].get('body_index',''):errors.append('baseline normalized output is not one explicit PREM N_ULVZ=0 record')
  else:
   try:
    valid=len(got)==3 and all(x.get('background')=='PREM' and int(x.get('n_ulvz','-1'))==3 for x in got) and {x.get('body_index') for x in got}=={'1','2','3'}
    ordered=sorted(got,key=lambda x:int(x['body_index'])) if valid else []
   except ValueError:valid=False;ordered=[]
   if not valid:errors.append('normalized output does not contain exactly 3 PREM bodies')
   for g,w in zip(ordered,want):
    for actual,col,scale in [('body_index','body_index',1),('center_latitude_degrees','latitude_deg',1),('center_longitude_degrees','longitude_deg',1),('lateral_radius_km','radius_km',1),('thickness_km','thickness_km',1),('lateral_taper_km','lateral_taper_km',1),('top_taper_km','top_taper_km',1),('dvs','dVs_percent',100),('dvp','dVp_percent',100),('drho','dRho_percent',100)]:
     try:
      if abs(num(g[actual])-num(w[col])/scale)>1e-7:errors.append('body '+w['body_index']+' '+actual+' mismatch')
     except (KeyError,ValueError):errors.append('body '+w['body_index']+' missing/invalid '+actual)
 h=a.run_dir/'OUTPUT_FILES/synthetic.h5'
 if not h.is_file():errors.append('synthetic.h5 missing')
 else:
  try:r=payload(h,expected_stations);errors.extend(r['errors'])
  except Exception as e:r={'hashes':{}};errors.append('ASDF read failure: '+str(e))
 if int(manifest['n_ulvz'])==3:
  b=a.baseline_run_dir or (a.run_dir.parent/manifest['baseline_pair_id']);baseline=b/'OUTPUT_FILES/synthetic.h5'
  if not baseline.is_file():errors.append('matched baseline synthetic.h5 missing')
  else:
   try:
    base=payload(baseline,expected_stations);errors.extend('baseline: '+x for x in base['errors'])
    if base['hashes']==r.get('hashes',{}):errors.append('TRIULVZ payload is bitwise-identical to baseline')
   except Exception as e:errors.append('baseline ASDF read failure: '+str(e))
 report={'run_id':a.run_id,'ok':not errors,'errors':errors};print(json.dumps(report,indent=2));raise SystemExit(bool(errors))
if __name__=='__main__':main()
