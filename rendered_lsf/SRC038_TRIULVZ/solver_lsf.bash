#!/usr/bin/env bash
#BSUB -J PREM3S_SRC038_TRIULVZ_solver
#BSUB -q mpi
#BSUB -n 384
#BSUB -R "span[ptile=64]"
#BSUB -o logs/solver-%J.out
#BSUB -e logs/solver-%J.err
set -euo pipefail
cd "${LS_SUBCWD:-$PWD}"
module load gcc/12.4.0
module load openmpi/4.1.5
[[ -x bin/xspecfem3D ]]
mpirun -np "${LSB_DJOB_NUMPROC:-384}" ./bin/xspecfem3D
