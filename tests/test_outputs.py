"""Verifier for the warranty claim cost model.

test.sh recompiles and runs the agent's C project twice -- once on the shipped batch and once
on an audit batch it has never seen -- and captures each run's output to a root-only path. This
module only reads those captures and the answer key at /opt/golden. It never runs agent code.

Every bar here is stated in instruction.md. The holdout bar is slacker than the graded one, so
nothing hidden is tighter than what the agent was told.
"""
import hashlib
import math
import os

import pytest

SHIPPED_RUN = "/opt/run_batch.dat"
HOLDOUT_RUN = "/opt/run_holdout.dat"
GOLDEN = "/opt/golden/batch_truth.dat"
HOLDOUT_TRUTH = "/opt/holdout/batch_truth.dat"
HISTORY = "/app/data/history.dat"
BATCH = "/app/data/batch.dat"

# Calibrated across four generator seeds on the written exports. Both corrections are needed and
# neither is enough alone: a fit that undoes the truncation with a row-dependent spread explains
# 0.745-0.757 of the variation in the audit costs, while the textbook truncated-normal fit
# carrying ONE pooled spread reaches 0.404-0.531, plain least squares 0.467-0.504, and a spread
# fitted against the wrong column 0.174-0.566. On the shipped instance those are 0.7576, 0.4891
# and 0.5034. The bar sits at the midpoint of that gap, 0.084 clear of the best route that misses
# a half of the correction.
#
# It was 0.70, and that was too fine a cut. A fourth route exists that the original sweep did not
# cover: a truncated likelihood on LOG cost with one constant log-sigma, i.e. a spread that rises
# with the fitted level rather than with the booked hours. It reads the second half of the
# problem, but off the wrong quantity, and it lands at 0.6604-0.6985 on this instance -- so a bar
# at 0.70 was decided by a margin of 0.0015 rather than by the correction, and no run cleared it.
# 0.65 keeps every route that assumes a single spread below the bar and lets that fourth family
# straddle it.
R2_BAR = 0.65
# The holdout runs the same program on a batch drawn under a different book of business, so an
# honest refit loses ground there: the reference scores 0.7223 against 0.7576 on the shipped
# batch, and the same runs that scored 0.66-0.70 above scored 0.5291-0.5541 here. A program
# carrying the shipped batch's fitted coefficients instead of refitting scores 0.29-0.33, so this
# bar sits 0.17 clear of that and stays slacker than the graded one.
HOLDOUT_R2_BAR = 0.50

HISTORY_SHA = "dbef133a758cee74e9d4ef616cad247b64fac2193c6cf079c6c98a0375525db6"
BATCH_SHA = "92c0be0377bf3c437efa204db8e01dbb1f875e2b963fa90ad9e27281b1972ebb"


def _open(path, mode="r"):
    """Open without following a final symlink.

    The captured runs are files the agent's own build wrote. test.sh refuses to stage anything
    that is not a regular file, so a link pointing at the answer key never reaches this module;
    opening O_NOFOLLOW here as well means the read cannot be redirected even if it did.
    """
    flags = os.O_RDONLY | os.O_NOFOLLOW
    return os.fdopen(os.open(path, flags), mode)


def _sha(path):
    with _open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _read(path, value_column=1):
    rows = {}
    with _open(path) as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    if not lines:
        pytest.fail(f"{path} is empty")
    for line in lines[1:]:
        fields = line.split()
        if len(fields) <= value_column:
            pytest.fail(f"{path}: malformed row {line!r}")
        # One line per claim is what the task asks for, so a repeated id is a failure rather
        # than something to collapse: keyed straight into the dict, a file that quoted one claim
        # twice and another not at all would still cover the batch and still be scored.
        if fields[0] in rows:
            pytest.fail(
                f"{path}: claim {fields[0]!r} is quoted on more than one row -- the output is "
                "one line per claim in the batch"
            )
        try:
            rows[fields[0]] = float(fields[value_column])
        except ValueError:
            pytest.fail(f"{path}: {fields[value_column]!r} is not a number in row {line!r}")
    return rows


def _header(path):
    with _open(path) as fh:
        return fh.readline().split()


def _r2(pred, truth):
    ids = sorted(truth)
    mean = sum(truth[i] for i in ids) / len(ids)
    ss = sum((truth[i] - pred[i]) ** 2 for i in ids)
    tot = sum((truth[i] - mean) ** 2 for i in ids)
    return 1.0 - ss / tot


@pytest.fixture(scope="session")
def batch_pred():
    return _read(SHIPPED_RUN)


@pytest.fixture(scope="session")
def holdout_pred():
    return _read(HOLDOUT_RUN)


def test_shipped_export_unmodified():
    """Both exports are byte-identical to what shipped."""
    assert _sha(HISTORY) == HISTORY_SHA, "history.dat was altered"
    assert _sha(BATCH) == BATCH_SHA, "batch.dat was altered"


# Both runs are held to the same structural contract. The holdout run used to be checked only for
# claim coverage and R2, so a wrong header passed there (the first line is skipped whatever it
# says), as did a non-finite or negative amount and a near-constant set of quotes.
RUNS = [
    pytest.param(SHIPPED_RUN, BATCH, id="batch"),
    pytest.param(HOLDOUT_RUN, HOLDOUT_TRUTH, id="holdout"),
]


@pytest.mark.parametrize("run_path,ids_path", RUNS)
def test_header_and_schema(run_path, ids_path):
    """Each run's output carries the two named columns."""
    head = _header(run_path)
    assert head == ["claim_id", "cost_gbp"], (
        f"expected a 'claim_id cost_gbp' header, got {' '.join(head)!r}"
    )


@pytest.mark.parametrize("run_path,ids_path", RUNS)
def test_covers_every_claim_exactly_once(run_path, ids_path):
    """One quote per claim in the batch that run was handed, no extras, no repeats.

    _read rejects a repeated claim_id outright, so a file quoting one claim twice fails there
    rather than being silently collapsed to one row.
    """
    pred = _read(run_path)
    with open(ids_path) as fh:
        ids = [ln.split()[0] for ln in fh.read().splitlines()[1:] if ln.strip()]
    assert len(ids) == len(set(ids)), f"{ids_path} itself has duplicate claim ids"
    missing = sorted(set(ids) - set(pred))
    extra = sorted(set(pred) - set(ids))
    assert not missing, f"{len(missing)} claims have no quote, e.g. {missing[:5]}"
    assert not extra, f"{len(extra)} quotes are for claims not in the batch, e.g. {extra[:5]}"


@pytest.mark.parametrize("run_path,ids_path", RUNS)
def test_values_are_finite_and_positive(run_path, ids_path):
    """Every quoted cost is a finite, positive amount, in both runs."""
    for cid, value in _read(run_path).items():
        assert math.isfinite(value), f"cost_gbp is not finite for claim {cid!r}"
        assert value > 0.0, f"cost_gbp must be a positive amount for claim {cid!r}: {value}"


@pytest.mark.parametrize("run_path,ids_path", RUNS)
def test_predictions_not_degenerate(run_path, ids_path):
    """The quotes vary across claims rather than being one number repeated, in both runs."""
    values = list(_read(run_path).values())
    spread = max(values) - min(values)
    assert spread > 100.0, (
        f"cost_gbp spans only {spread:.2f} across the batch -- these claims differ by hundreds "
        "of pounds in labour alone, so a near-constant quote is not a model"
    )


def test_r2_bar(batch_pred):
    """The quotes explain the audit costs to the level the task requires."""
    score = _r2(batch_pred, _read(GOLDEN))
    assert score >= R2_BAR, (
        f"R2 against the audited costs is {score:.4f}, below {R2_BAR:.2f}. The claims on file "
        "are the ones that cleared the deductible, and the audit batch is not"
    )


def test_holdout_r2(holdout_pred):
    """The model still explains the costs on a batch the agent never saw."""
    score = _r2(holdout_pred, _read(HOLDOUT_TRUTH))
    assert score >= HOLDOUT_R2_BAR, (
        f"R2 on the unseen batch is {score:.4f}, below {HOLDOUT_R2_BAR:.2f}. The same program "
        "was graded on the shipped batch, so either it is emitting numbers fitted to that batch "
        "rather than fitting the files it was given, or the fit does not carry over"
    )


def test_holdout_output_differs_from_shipped_run(batch_pred, holdout_pred):
    """The two runs are not the same numbers, which a table baked into the source would be."""
    shared = set(batch_pred) & set(holdout_pred)
    assert not shared or len(shared) < len(batch_pred), (
        "the unseen batch produced quotes under the shipped batch's claim ids"
    )
    a = sorted(batch_pred.values())
    b = sorted(holdout_pred.values())
    assert a != b, (
        "both runs produced an identical set of costs, so the program is not fitting the file "
        "it was given"
    )
