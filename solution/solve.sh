#!/usr/bin/env bash
set -euo pipefail

# Reference cost model for the warranty reserve.
#
# A claim only reaches us once it clears the dealer deductible, so history.dat is cut on the
# cost itself rather than on any of the columns beside it. That is what makes least squares
# there misleading: the residuals that survive the cut are the top of their own distribution,
# so the fitted slope flattens and the intercept lifts, and the audit batch -- captured whole,
# small jobs and all -- is scored against a line fitted to the wrong population.
#
# Fitting the truncated likelihood instead recovers the coefficients the claims were generated
# from. On this export that is the difference between explaining 0.79 of the variation in the
# audit costs and explaining 0.54.
#
# The model itself is solution/main.c, next to this script.
install -m 644 "$(dirname "$0")/main.c" /app/model/src/main.c

bash /app/model/build.sh
