#!/usr/bin/env bash
# Build and run the claim cost model. Writes /app/out/predictions.dat.
#   bash /app/model/build.sh
set -euo pipefail
cd /app/model
mkdir -p /app/out
gcc -O2 -std=gnu11 -o model src/main.c -lm
exec ./model
