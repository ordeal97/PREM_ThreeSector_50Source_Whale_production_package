#!/usr/bin/env bash
#BSUB -J PREM3S_SRC043_B0_control
#BSUB -q serial
#BSUB -n 1
#BSUB -R "span[hosts=1]"
#BSUB -L /bin/bash
#BSUB -o logs/control-%J.out
#BSUB -e logs/control-%J.err
# Per-run controller: compile mesher, submit/wait mesh, compile/submit solver.
set -euo pipefail
cd "${LS_SUBCWD:-$PWD}"; mkdir -p logs
module purge
set +u
source "/share/apps/intel/oneapi_2023.1.0/setvars.sh"
set -u
module load hdf5/1.14.3_oneapi2023
command -v ifort >/dev/null 2>&1 || { echo "required command missing: ifort" >&2; exit 127; }
command -v mpiifort >/dev/null 2>&1 || { echo "required command missing: mpiifort" >&2; exit 127; }
command -v mpirun >/dev/null 2>&1 || { echo "required command missing: mpirun" >&2; exit 127; }
[[ -d "/scratch/yiy/ulvz/SRC043_B0/DATABASES_MPI/" && -w "/scratch/yiy/ulvz/SRC043_B0/DATABASES_MPI/" ]]
lock=.mesh_solver_control.lock; mkdir "$lock" || { echo "active control lock" >&2; exit 2; }
trap 'rmdir "$lock" 2>/dev/null || true' EXIT
MESHER_JOB_ID=""; SOLVER_JOB_ID=""; MESHER_SUBMISSION_STATE=""; SOLVER_SUBMISSION_STATE=""
write_metadata() { local tmp=run_job_ids.env.tmp.$$; { printf 'run_id=SRC043_B0\ncontrol_job_id=%s\nmesher_job_id=%s\nsolver_job_id=%s\nmesher_submission_state=%s\nsolver_submission_state=%s\n' "${LSB_JOBID:-}" "$MESHER_JOB_ID" "$SOLVER_JOB_ID" "$MESHER_SUBMISSION_STATE" "$SOLVER_SUBMISSION_STATE"; } > "$tmp"; mv "$tmp" run_job_ids.env; }
fail() { write_metadata; echo "ERROR: $*" >&2; exit 1; }
jobid() { awk -F '[<>]' '/Job </ {print $2; exit}'; }
state() { local value history; value="$(bjobs -a "$1" 2>/dev/null | awk 'NR==2 {print $3}' || true)"; if [[ -n "$value" ]]; then printf '%s\n' "$value"; return; fi; history="$(bhist -l "$1" 2>/dev/null || true)"; if grep -Eqi 'Completed <done>|Done successfully' <<< "$history"; then echo DONE; elif grep -Eqi 'Completed <exit>|Exited' <<< "$history"; then echo EXIT; else echo UNKNOWN; fi; }
wait_done() { local unknown=0 x; while :; do x="$(state "$1")"; case "$x" in DONE) return;; EXIT) fail "$2 exited: $1";; PEND|RUN|WAIT|PSUSP|USUSP|SSUSP|UNKWN|ZOMBI) unknown=0;; *) unknown=$((unknown+1)); [[ "$unknown" -lt 12 ]] || fail "cannot determine $2 state: $1";; esac; sleep 240; done; }
submit_child() { local kind="$1" script="$2" output; if [[ "$kind" == mesher ]]; then MESHER_SUBMISSION_STATE=PENDING; else SOLVER_SUBMISSION_STATE=PENDING; fi; write_metadata; if ! output="$(bsub < "$script" 2>&1)"; then printf '%s\n' "$output" >> logs/control-submit.log; fail "$kind submission failed"; fi; printf '%s\n' "$output" >> logs/control-submit.log; output="$(printf '%s\n' "$output" | jobid)"; [[ "$output" =~ ^[0-9]+$ ]] || fail "cannot parse $kind job id"; if [[ "$kind" == mesher ]]; then MESHER_JOB_ID="$output"; MESHER_SUBMISSION_STATE=CONFIRMED; else SOLVER_JOB_ID="$output"; SOLVER_SUBMISSION_STATE=CONFIRMED; fi; write_metadata; }
command -v bsub >/dev/null 2>&1 && command -v bjobs >/dev/null 2>&1 && command -v bhist >/dev/null 2>&1 || fail "LSF commands unavailable"
write_metadata
make clean; make meshfem3D -j1
submit_child mesher mesher_lsf.bash
wait_done "$MESHER_JOB_ID" mesher
make clean; make specfem3D -j1
submit_child solver solver_lsf.bash
