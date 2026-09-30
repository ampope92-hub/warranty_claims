"""Holdout batch: a different book of business, on a different seed.

The verifier swaps this in for /app/data and runs the agent's program a second time. A model
that fits at run time handles it; one that carries numbers worked out once does not.

The cost drivers differ from the shipped batch as well as the seed, and that is what closes the
subtler cheat. A program that stores the fitted COEFFICIENTS rather than the quotes recomputes
plausible numbers on whatever file it is handed, so it survives a holdout drawn under the same
coefficients: measured on the previous same-regime holdout the stored fit scored 0.7815 against
a 0.60 holdout bar, alongside an honest refit's 0.7821. Under this book it scores 0.3211 while an
honest refit scores 0.7223, so only a program that reads history.dat at run time clears the bar,
which now stands at 0.50.
The deductible and the spread law are unchanged, so that run exercises the same correction.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_data import build

# Same five columns, a different mix of what drives the cost: an older book where prior claims
# and mileage carry most of the money and the labour rate is lower.
HOLDOUT_BETA = [90.0, 3.0, 62.0, 58.0, 150.0]

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "../tests/holdout")
    out.mkdir(parents=True, exist_ok=True)
    n_h, n_b, frac = build(11, out, prefix="H", beta=HOLDOUT_BETA)
    print(f"holdout seed 11 -> {out}  history {n_h} rows ({100*frac:.1f}% filed), batch {n_b} rows")
