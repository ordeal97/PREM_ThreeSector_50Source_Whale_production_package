#!/usr/bin/env bash
# Stage stage1_baseline; controller owns submission order.
set -euo pipefail
bsub < mesher_lsf.bash
