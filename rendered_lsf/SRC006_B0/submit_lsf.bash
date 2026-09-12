#!/usr/bin/env bash
# Per-run controller: compile mesher, submit/wait mesh, compile/submit solver.
set -euo pipefail
cd "${LS_SUBCWD:-$PWD}"; mkdir -p logs
module load gcc/12.4.0
module load openmpi/4.1.5
[[ -d "/scratch/yiy/ulvz/SRC006_B0/DATABASES_MPI/" && -w "/scratch/yiy/ulvz/SRC006_B0/DATABASES_MPI/" ]]
lock=.mesh_solver_control.lock; mkdir "$lock" || { echo "active control lock" >&2; exit 2; }
trap 'rmdir "$lock" 2>/dev/null || true' EXIT
jobid() { awk -F '[<>]' '/Job </ {print $2; exit}'; }
state() { bjobs -a "$1" 2>/dev/null | awk 'NR==2 {print $3}'; }
wait_done() { unknown=0; while :; do x="$(state "$1")"; case "$x" in DONE) return;; EXIT) exit 3;; PEND|RUN|WAIT|PSUSP|USUSP|SSUSP) unknown=0;; *) unknown=$((unknown+1)); [[ "$unknown" -lt 12 ]] || exit 4;; esac; sleep 240; done; }
make clean; make meshfem3D -j1
MESHER_JOB_ID="$(bsub < mesher_lsf.bash | jobid)"; [[ "$MESHER_JOB_ID" =~ ^[0-9]+$ ]]
printf 'run_id=SRC006_B0
mesher_job_id=%s
' "$MESHER_JOB_ID" > run_job_ids.env
wait_done "$MESHER_JOB_ID"
make clean; make specfem3D -j1
SOLVER_JOB_ID="$(bsub < solver_lsf.bash | jobid)"; [[ "$SOLVER_JOB_ID" =~ ^[0-9]+$ ]]
printf 'run_id=SRC006_B0
mesher_job_id=%s
solver_job_id=%s
' "$MESHER_JOB_ID" "$SOLVER_JOB_ID" > run_job_ids.env
