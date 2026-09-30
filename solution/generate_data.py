"""Warranty claim generator.

The crux is selection on the outcome. A dealer absorbs any warranty job that comes in under
the deductible, so those claims are never filed with the manufacturer and never appear in
history.dat. That truncates the ERROR of the cost model, not one of its covariates, which is
what makes least squares on the retained rows biased: the retained residuals are the upper
tail of their own distribution, so the slope flattens and the intercept lifts.

Selection on a covariate would be harmless -- the conditional mean is unchanged -- and that is
the distinction the task turns on.

The audit batch is captured differently: an independent auditor recorded every job at three
dealers regardless of value, so it is an untruncated sample of the same population. A model
fitted to the filed claims and applied to the audit batch has to undo the truncation.

The second half of the crux is that the spread is not constant. A three-hour job and a
fifteen-hour job do not miss by the same money, so the residual sd rises with the labour booked
to the job. On an untruncated sample that would cost nothing -- least squares stays unbiased
under heteroskedasticity -- but here the two interact: how far a filed claim has to be pushed
back down to undo the truncation depends on the sd AT THAT ROW, so a truncated likelihood
carrying one pooled sd corrects the small jobs and the large ones by the same amount and gets
both wrong. That is why the textbook truncated-normal fit, done perfectly, still misses the bar
(0.4891 on this instance against 0.65), while the same fit with a row-dependent sd reaches
0.7576. Neither correction is enough on its own.
"""
from pathlib import Path

import numpy as np

# intercept, age_months, odometer_10k_km, labour_hours, prior_claims
#
# The holdout batch is drawn under a DIFFERENT set (see generate_holdout.py). A holdout that
# shares these coefficients is cleared by a program that never opens history.dat and carries the
# shipped fit in its source instead, which leaves "it needs to fit whatever is sitting in
# /app/data" unenforced.
BETA = np.array([120.0, 6.4, 41.0, 96.0, 55.0])
# Residual sd, in pounds, as a function of the labour booked to the job: bigger jobs miss by
# more. Averaged over the pool this is about 153, so the overall noise level is what a single
# pooled sd of 150 would give -- what changes is that it is not the same at every row.
SD_BASE, SD_PER_HOUR = 45.0, 30.0
DEDUCTIBLE = 1050.0
N_POOL = 40000
N_HISTORY = 4200
BATCH = slice(30000, 32000)


def draw(seed, beta=BETA):
    rng = np.random.default_rng(seed)
    age = rng.uniform(1, 84, N_POOL)
    odo = rng.gamma(3.0, 1.4, N_POOL)
    labour = rng.gamma(2.2, 1.5, N_POOL) + 0.3
    prior = rng.poisson(1.1, N_POOL).astype(float)
    X = np.column_stack([np.ones(N_POOL), age, odo, labour, prior])
    sd = SD_BASE + SD_PER_HOUR * labour
    return X, X @ np.asarray(beta, float) + rng.normal(0.0, 1.0, N_POOL) * sd


def write(path, ids, X, cost=None):
    head = "claim_id age_months odometer_10k_km labour_hours prior_claims"
    lines = [head + (" cost_gbp" if cost is not None else "")]
    for i in range(len(ids)):
        row = f"{ids[i]} {X[i,1]:.3f} {X[i,2]:.4f} {X[i,3]:.3f} {int(X[i,4])}"
        if cost is not None:
            row += f" {cost[i]:.2f}"
        lines.append(row)
    Path(path).write_text("\n".join(lines) + "\n")


def build(seed, outdir, prefix="W", beta=BETA):
    X, y = draw(seed, beta)
    keep = y >= DEDUCTIBLE
    Xh, yh = X[keep][:N_HISTORY], y[keep][:N_HISTORY]
    Xb, yb = X[BATCH], y[BATCH]
    out = Path(outdir)
    write(out / "history.dat", [f"{prefix}{i:06d}" for i in range(len(yh))], Xh, yh)
    ids = [f"{prefix}A{i:05d}" for i in range(len(yb))]
    write(out / "batch.dat", ids, Xb)
    Path(out / "batch_truth.dat").write_text(
        "claim_id cost_gbp\n" + "".join(f"{i} {c:.2f}\n" for i, c in zip(ids, yb)))
    return len(yh), len(yb), keep.mean()


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "."
    n_h, n_b, frac = build(0, d)
    print(f"history {n_h} rows (deductible {DEDUCTIBLE:.0f}, {100*frac:.1f}% of claims filed), "
          f"batch {n_b} rows")
