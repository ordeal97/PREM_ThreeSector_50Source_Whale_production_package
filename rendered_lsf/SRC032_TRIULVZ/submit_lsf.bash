#!/usr/bin/env bash
# Stage stage2_multi; controller owns submission order.
set -euo pipefail
bsub < mesher_lsf.bash
