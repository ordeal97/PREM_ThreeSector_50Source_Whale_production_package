#BSUB -J PREM3S_SRC039_B0_mesher
#BSUB -q mpi
#BSUB -n 384
#BSUB -R "span[ptile=64]"
#BSUB -o logs/mesher-%J.out
#BSUB -e logs/mesher-%J.err
set -euo pipefail
WORKPATH="${LS_SUBCWD:-$PWD}"; cd "$WORKPATH"
module purge; module load gcc/12.4.0; module load openmpi/4.1.5
OMPI_HOME=/share/apps/openmpi/4.1.5; GCC_HOME=/share/apps/gcc/12.4.0
export LD_LIBRARY_PATH="${GCC_HOME}/lib64:${OMPI_HOME}/lib:${LD_LIBRARY_PATH:-}"
HOSTFILE="$WORKPATH/hostfile.${LSB_JOBID}"; sort "${LSB_DJOB_HOSTFILE}" | uniq -c | awk '{print $2 " slots=" $1}' > "$HOSTFILE"; trap 'rm -f "$HOSTFILE"' EXIT
mpirun --prefix "$OMPI_HOME" -np "${LSB_DJOB_NUMPROC:-384}" --hostfile "$HOSTFILE" --map-by ppr:64:node --bind-to core --mca pml ucx --mca btl '^openib' -x LD_LIBRARY_PATH "./bin/xmeshfem3D"
