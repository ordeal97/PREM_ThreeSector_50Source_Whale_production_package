#!/usr/bin/env bash
#BSUB -J PREM3S_SRC018_B0_mesher
#BSUB -q mpi
#BSUB -n 384
#BSUB -R "span[ptile=64]"
#BSUB -o logs/mesher-%J.out
#BSUB -e logs/mesher-%J.err
set -euo pipefail
cd "${LS_SUBCWD:-$PWD}"
module load gcc/12.4.0
module load openmpi/4.1.5
[[ -x bin/xmeshfem3D ]]
mpirun -np "${LSB_DJOB_NUMPROC:-384}" ./bin/xmeshfem3D
