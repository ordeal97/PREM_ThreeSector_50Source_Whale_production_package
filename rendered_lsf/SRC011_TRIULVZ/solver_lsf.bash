#!/usr/bin/env bash
#BSUB -J PREM3S_SRC011_TRIULVZ_solver
#BSUB -q mpi
#BSUB -n 384
#BSUB -R "span[ptile=64]"
#BSUB -L /bin/bash
#BSUB -o logs/solver-%J.out
#BSUB -e logs/solver-%J.err
set -euo pipefail
cd "${LS_SUBCWD:-$PWD}"
module purge
set +u
source "/share/apps/intel/oneapi_2023.1.0/setvars.sh"
set -u
module load hdf5/1.14.3_oneapi2023
command -v ifort >/dev/null 2>&1 || { echo "required command missing: ifort" >&2; exit 127; }
command -v mpiifort >/dev/null 2>&1 || { echo "required command missing: mpiifort" >&2; exit 127; }
command -v mpirun >/dev/null 2>&1 || { echo "required command missing: mpirun" >&2; exit 127; }
[[ -x bin/xspecfem3D ]]
mpirun -np "${LSB_DJOB_NUMPROC:-384}" ./bin/xspecfem3D
