#!/usr/bin/env bash
#BSUB -J PREM3S_SRC027_B0_mesher
#BSUB -q mpi
#BSUB -n 384
#BSUB -R "span[ptile=64]"
#BSUB -o logs/mesher-%J.out
#BSUB -e logs/mesher-%J.err
set -euo pipefail
cd "${LS_SUBCWD:-$PWD}"
module purge
if [[ -z "${I_MPI_ROOT:-}" ]] || ! command -v mpiifort >/dev/null 2>&1; then source "/share/apps/intel/oneapi_2023.1.0/setvars.sh"; fi
module load hdf5/1.14.3_oneapi2023
[[ -x bin/xmeshfem3D ]]
mpirun -np "${LSB_DJOB_NUMPROC:-384}" ./bin/xmeshfem3D
