# PREFLIGHT REPORT

Status: **PASS**

- sources: 50; depth bins: {'0-70': 39, '70-150': 4, '150-300': 3, '300-500': 1, '500-700': 3}
- stations: 510 (A/B/C = 170 each)
- runs: 50 B0 + 50 TRIULVZ
- instances: 150; taper: all zero
- parameter sources: {'legacy_parameter_anchor': 33, 'family_interpolant': 66, 'survey_family_sample': 51}
- sectors: {'A': 50, 'B': 50, 'C': 50}
- radiation near-node diagnostic cells: P=7/150; S=0/150
- minimum three-body clearance: 3417.428 km
- common setting: six-chunk, NEX 448x448, NPROC 8x8, ranks 384, PREM/ASDF, DT 0.1 s, record 42 min, expected NSTEP/npts 25400

## Deployment-time validation

- Whale GCC/OpenMPI and ASDF/HDF5 build compatibility; executable build; LSF queue and host layout; scratch access; memory/storage; no production mesher/solver result is present.

## Result

PASS: static design equals manifest equals rendered DATA.
