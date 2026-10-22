# Warranty Claim Costing (Truncated Regression in C)

A vehicle manufacturer reimburses dealers for warranty work and needs a cost estimate for every job in an audit batch before setting a reserve. The agent gets `history.dat` (settled claims with what was paid), `batch.dat` (the audit batch, same covariates without the cost) and a data dictionary, and must fill in a C project (`/app/model/src/main.c` plus `build.sh`) using nothing beyond libc and libm, offline. A clean `bash /app/model/build.sh` must compile the model, fit it from whatever is in `/app/data`, and write `/app/out/predictions.dat` with one `claim_id cost_gbp` line per audit claim.

## What makes it hard

- **Selection on the outcome, not a covariate.** Every settled claim cleared a dealer deductible of about GBP 1050; cheaper jobs are carried by the dealer and never filed. Nothing states this - the data dictionary only says franchise terms decide which jobs reach the ledger - so it has to be found in the data: settled costs stop dead at 1050, with 60 of 4200 rows within five pounds of it. Because the cut is on the modelled quantity, least squares returns a flattened slope and lifted intercept, and the unfiltered audit batch is scored against a line fitted to a different population.
- **The spread is not constant, and that interacts with the truncation.** Residual sd rises with booked labour hours. How far each claim must be pushed back down depends on the spread at that row, so the textbook truncated-normal regression with one pooled sigma, implemented perfectly, scores R2 0.4891 on the shipped batch - worse than plain least squares (0.5034). The same likelihood with a row-dependent sigma scores 0.7576.
- **The agent's own validation points the wrong way.** On a held-out split of `history.dat` (the only validation available), least squares ranks first (0.4880-0.5779) and the correct fit scores 0.2811-0.4490. On the audit batch the ranking inverts.
- **The bar sits between measured routes.** Across four generator seeds: correct row-spread fit 0.7446-0.7576; pooled-spread truncated fit 0.4042-0.5305; least squares 0.4668-0.5037. A truncated log-cost model with constant log-sigma reaches 0.6604-0.6985, which is why the bar is 0.65 rather than 0.70. The exact spread law does not matter (exponential, linear, or mean-driven all clear it); assuming a single spread does.

The likelihood, normal CDF via `erfc`, Newton optimiser and linear solve all have to be written by hand, but the implementation is not the hard part.

## How it's graded

The verifier runs in a separate, offline container. It collects the agent's sources, build script and exports, recompiles with gcc as an unprivileged user, and runs the program. Nine checks in `tests/test_outputs.py`:

- Both shipped exports unaltered (sha256); correct header; exactly one quote per claim; finite positive amounts; spread of quotes above GBP 100.
- R2 against the true audited costs of at least 0.65.
- **Holdout re-run:** `/app/data` is swapped for an unseen batch drawn under a different set of cost drivers (same deductible), and the program is rebuilt and run again. It must cover every claim, reach R2 above 0.50, and not reproduce the first run's numbers. The changed cost drivers mean stored coefficients score only 0.29-0.33 there, while an honest refit scores about 0.75.

Anti-cheat: agent code runs via `setpriv` as an unprivileged user (no supplementary groups, no-new-privs), with Python interpreters closed to it during the build; process groups are killed before grading; output is staged only if it is a regular file and read with `O_NOFOLLOW`; audited costs are root-only in the verifier image and `/tests` is closed (run scored 0 if reachable); pytest runs with `-P`.

## Repository layout

- `instruction.md` - the task prompt given to the agent.
- `task.toml` - metadata, difficulty/solution/verification write-ups, timeouts and network policy.
- `environment/` - agent image: `Dockerfile`, the C stub and `build.sh` in `model/`, and the exports plus data dictionary in `data/`.
- `solution/` - reference `main.c` (heteroskedastic truncated-normal MLE by Newton with analytic gradients), `solve.sh`, and the generators `generate_data.py` (rebuilds the shipped exports byte for byte) and `generate_holdout.py`.
- `tests/` - verifier image, `test.sh`, `test_outputs.py`, the true audited costs (`golden/`) and the holdout batch (`holdout/`).

## Running it

Requires Docker and Harbor (`uv tool install harbor` or `pip install harbor`). From the repo root:

```
harbor run -p . -a oracle
```

runs the reference solution through the verifier (should score reward 1). To try an agent instead:

```
harbor run -p . -a <agent> -m <model>
```

for example `-a claude-code`.

---

Task design, data generators, reference solution and verifier by Audrey Pope.
