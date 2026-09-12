#!/usr/bin/env python3
"""Write pairwise normalized moment-tensor similarity for the frozen sources."""
from __future__ import annotations
import csv, math
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
def tensor(s,d,r):
 st,di,ra=map(math.radians,(s,d,r));sd,cd=math.sin(di),math.cos(di);sr,cr=math.sin(ra),math.cos(ra);ss,cs=math.sin(st),math.cos(st)
 return np.array([[-(sd*cr*math.sin(2*st)+math.sin(2*di)*sr*ss**2),sd*cr*math.cos(2*st)+.5*math.sin(2*di)*sr*math.sin(2*st),-(cd*cr*math.cos(2*st)+math.cos(2*di)*sr*ss)], [sd*cr*math.cos(2*st)+.5*math.sin(2*di)*sr*math.sin(2*st),sd*cr*math.sin(2*st)-math.sin(2*di)*sr*cs**2,cd*cr*math.sin(2*st)-math.cos(2*di)*sr*ss],[-(cd*cr*math.cos(2*st)+math.cos(2*di)*sr*ss),cd*cr*math.sin(2*st)-math.cos(2*di)*sr*ss,math.sin(2*di)*sr]])
with (ROOT/'catalogs/source_ensemble.csv').open(newline='') as f:sources=list(csv.DictReader(f))
rows=[]
for i,a in enumerate(sources):
 ma=tensor(*map(float,(a['strike_deg'],a['dip_deg'],a['rake_deg'])));ma/=np.linalg.norm(ma)
 for b in sources[i+1:]:
  mb=tensor(*map(float,(b['strike_deg'],b['dip_deg'],b['rake_deg'])));mb/=np.linalg.norm(mb)
  # Absolute correlation identifies sign-reversed/equivalent radiation patterns.
  rows.append({'source_i':a['source_id'],'source_j':b['source_id'],'absolute_tensor_correlation':f'{abs(float(np.sum(ma*mb))):.8f}','mechanism_distance':f'{1-abs(float(np.sum(ma*mb))):.8f}'})
with (ROOT/'catalogs/source_mechanism_similarity.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
print('minimum_mechanism_distance',min(float(x['mechanism_distance']) for x in rows))
