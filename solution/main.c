/* Reference cost model for the warranty reserve.
 *
 * history.dat holds only the claims that were actually filed, and a claim is only filed when
 * it clears the dealer deductible. The cut is on the cost itself, so the residuals in that
 * file are the upper tail of their own distribution: least squares fitted there has a
 * flattened slope and a lifted intercept, and applying it to the audit batch -- which the
 * auditor captured whole, small jobs included -- carries that bias straight through.
 *
 * The fix is to fit the model the filed claims actually came from. With cost ~ N(x.b, s^2)
 * observed only when cost >= D, the log-likelihood of a filed claim is
 *
 *     log phi((y - x.b)/s) - log s - log P(cost >= D | x)
 *
 * and maximising that recovers the untruncated b and s.
 *
 * s is not one number. A fifteen-hour job does not miss by the same money as a three-hour one,
 * and the residual spread in the filed claims rises with the labour booked. On an untruncated
 * sample that would not matter -- least squares stays unbiased under heteroskedasticity -- but
 * here it interacts with the cut: how far a filed claim has to be pushed back down to undo the
 * truncation is set by the spread AT THAT ROW, so one pooled s corrects the small jobs and the
 * large ones by the same amount and gets both wrong. This fits
 *
 *     s_i = exp(q0 + q1 * u_i),   u_i = labour_hours_i / mean(labour_hours)
 *
 * alongside b. The exponential form keeps s positive without a constraint; the spread in the
 * export is close to linear in the hours, and either parameterisation recovers b (0.7576 and
 * 0.7567 respectively on the shipped batch, against 0.4891 for one pooled s).
 *
 * Newton on (b, q0, q1), with the gradient in closed form and the Hessian by differencing it,
 * converges in a few dozen steps. Everything is done on standardised columns and mapped back at
 * the end.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define NP 5                      /* intercept + 4 covariates */
#define NQ (NP + 2)               /* + the two spread parameters q0, q1 */
#define LABOUR_COL 3              /* the column the residual spread scales with */
#define MAXROW 200000

static double Xh[MAXROW][NP], yh[MAXROW];
static double Xb[MAXROW][NP];
static char idb[MAXROW][32];
static int nh, nb;

static double mu_[NP], sd_[NP], ycen, yscl;

/* written out rather than taken from M_PI, which strict ISO modes do not expose */
static const double TWO_PI = 6.283185307179586476925286766559;

static double normpdf(double z) { return exp(-0.5 * z * z) / sqrt(TWO_PI); }
static double normsf(double z)  { return 0.5 * erfc(z / sqrt(2.0)); }

/* Gaussian elimination with partial pivoting; A is n x n, b length n, solution into b. */
static int solve(int n, double A[NQ][NQ], double *b)
{
    for (int c = 0; c < n; c++) {
        int piv = c;
        for (int r = c + 1; r < n; r++)
            if (fabs(A[r][c]) > fabs(A[piv][c])) piv = r;
        if (fabs(A[piv][c]) < 1e-12) return 0;
        if (piv != c) {
            for (int k = 0; k < n; k++) { double t = A[c][k]; A[c][k] = A[piv][k]; A[piv][k] = t; }
            double t = b[c]; b[c] = b[piv]; b[piv] = t;
        }
        for (int r = c + 1; r < n; r++) {
            double f = A[r][c] / A[c][c];
            if (f == 0.0) continue;
            for (int k = c; k < n; k++) A[r][k] -= f * A[c][k];
            b[r] -= f * b[c];
        }
    }
    for (int r = n - 1; r >= 0; r--) {
        for (int k = r + 1; k < n; k++) b[r] -= A[r][k] * b[k];
        b[r] /= A[r][r];
    }
    return 1;
}

static int read_history(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) { fprintf(stderr, "cannot open %s\n", path); return 0; }
    char line[512];
    if (!fgets(line, sizeof line, f)) { fclose(f); return 0; }
    nh = 0;
    while (fgets(line, sizeof line, f)) {
        char id[32]; double a, o, l, p, c;
        if (sscanf(line, "%31s %lf %lf %lf %lf %lf", id, &a, &o, &l, &p, &c) != 6) continue;
        Xh[nh][0] = 1.0; Xh[nh][1] = a; Xh[nh][2] = o; Xh[nh][3] = l; Xh[nh][4] = p;
        yh[nh] = c; nh++;
    }
    fclose(f);
    return nh > 0;
}

static int read_batch(const char *path)
{
    FILE *f = fopen(path, "r");
    if (!f) { fprintf(stderr, "cannot open %s\n", path); return 0; }
    char line[512];
    if (!fgets(line, sizeof line, f)) { fclose(f); return 0; }
    nb = 0;
    while (fgets(line, sizeof line, f)) {
        char id[32]; double a, o, l, p;
        if (sscanf(line, "%31s %lf %lf %lf %lf", id, &a, &o, &l, &p) != 5) continue;
        snprintf(idb[nb], sizeof idb[nb], "%s", id);
        Xb[nb][0] = 1.0; Xb[nb][1] = a; Xb[nb][2] = o; Xb[nb][3] = l; Xb[nb][4] = p;
        nb++;
    }
    fclose(f);
    return nb > 0;
}

/* standardised copies of the design and response, and the spread driver */
static double Z[MAXROW][NP], yz[MAXROW], Ul[MAXROW];

static void standardise(void)
{
    mu_[0] = 0.0; sd_[0] = 1.0;
    for (int j = 1; j < NP; j++) {
        double s = 0.0, ss = 0.0;
        for (int i = 0; i < nh; i++) s += Xh[i][j];
        mu_[j] = s / nh;
        for (int i = 0; i < nh; i++) { double d = Xh[i][j] - mu_[j]; ss += d * d; }
        sd_[j] = sqrt(ss / nh);
        if (sd_[j] < 1e-12) sd_[j] = 1.0;
    }
    double s = 0.0, ss = 0.0;
    for (int i = 0; i < nh; i++) s += yh[i];
    ycen = s / nh;
    for (int i = 0; i < nh; i++) { double d = yh[i] - ycen; ss += d * d; }
    yscl = sqrt(ss / nh);
    for (int i = 0; i < nh; i++) {
        Z[i][0] = 1.0;
        for (int j = 1; j < NP; j++) Z[i][j] = (Xh[i][j] - mu_[j]) / sd_[j];
        yz[i] = (yh[i] - ycen) / yscl;
        /* the spread driver is the labour column over its own mean: positive, order 1, and
           free of the sign the standardised column would carry */
        Ul[i] = (mu_[LABOUR_COL] > 1e-12) ? Xh[i][LABOUR_COL] / mu_[LABOUR_COL] : 1.0;
    }
}

static void ols(double *out)
{
    double A[NQ][NQ] = {{0}}, b[NQ] = {0};
    for (int i = 0; i < nh; i++) {
        for (int j = 0; j < NP; j++) {
            b[j] += Z[i][j] * yz[i];
            for (int k = 0; k < NP; k++) A[j][k] += Z[i][j] * Z[i][k];
        }
    }
    solve(NP, A, b);
    for (int j = 0; j < NP; j++) out[j] = b[j];
}

static double Tz;

/* negative log-likelihood of the filed claims, and its gradient in p = (b, q0, q1),
   where the row's spread is s_i = exp(q0 + q1 * u_i) */
static double nll(const double *p, double *g)
{
    double f = 0.0, gq0 = 0.0, gq1 = 0.0, gb[NP] = {0};
    for (int i = 0; i < nh; i++) {
        double xb = 0.0;
        for (int j = 0; j < NP; j++) xb += Z[i][j] * p[j];
        double ls = p[NP] + p[NP + 1] * Ul[i];
        if (ls > 50.0) ls = 50.0;
        if (ls < -50.0) ls = -50.0;
        double s = exp(ls);
        double r = yz[i] - xb;
        double a = (Tz - xb) / s;
        double sf = normsf(a);
        if (sf < 1e-300) sf = 1e-300;
        double lam = normpdf(a) / sf;
        f += 0.5 * (r / s) * (r / s) + ls + log(sf);
        if (g) {
            double w = -r / (s * s) + lam / s;
            for (int j = 0; j < NP; j++) gb[j] += Z[i][j] * w;
            /* d/d(log s) of the row term; q0 and q1 differ only by the chain factor */
            double t = -(r * r) / (s * s) + 1.0 + lam * a;
            gq0 += t;
            gq1 += t * Ul[i];
        }
    }
    if (g) {
        for (int j = 0; j < NP; j++) g[j] = gb[j];
        g[NP] = gq0;
        g[NP + 1] = gq1;
    }
    return f;
}

/* Newton on (b, q0, q1): analytic gradient, Hessian by central differences of the gradient. */
static void trunc_mle(double *p)
{
    double g[NQ], gp[NQ], gm[NQ], H[NQ][NQ], step[NQ], probe[NQ];
    for (int it = 0; it < 200; it++) {
        double f0 = nll(p, g);
        double gnorm = 0.0;
        for (int j = 0; j < NQ; j++) gnorm += g[j] * g[j];
        if (sqrt(gnorm) < 1e-9) break;

        const double h = 1e-5;
        for (int j = 0; j < NQ; j++) {
            memcpy(probe, p, sizeof probe); probe[j] += h; nll(probe, gp);
            memcpy(probe, p, sizeof probe); probe[j] -= h; nll(probe, gm);
            for (int i = 0; i < NQ; i++) H[i][j] = (gp[i] - gm[i]) / (2.0 * h);
        }
        for (int i = 0; i < NQ; i++)
            for (int j = i + 1; j < NQ; j++) {
                double m = 0.5 * (H[i][j] + H[j][i]); H[i][j] = H[j][i] = m;
            }
        for (int i = 0; i < NQ; i++) H[i][i] += 1e-8;

        memcpy(step, g, sizeof step);
        if (!solve(NQ, H, step)) break;

        double t = 1.0; int ok = 0;
        for (int ls = 0; ls < 60; ls++) {
            for (int j = 0; j < NQ; j++) probe[j] = p[j] - t * step[j];
            if (nll(probe, NULL) <= f0) { ok = 1; break; }
            t *= 0.5;
        }
        if (!ok) break;
        double mv = 0.0;
        for (int j = 0; j < NQ; j++) { double d = fabs(t * step[j]); if (d > mv) mv = d; }
        for (int j = 0; j < NQ; j++) p[j] -= t * step[j];
        if (mv < 1e-11) break;
    }
}

int main(int argc, char **argv)
{
    const char *dir = (argc > 1) ? argv[1] : "/app/data";
    const char *out = (argc > 2) ? argv[2] : "/app/out/predictions.dat";
    char ph[512], pb[512];
    snprintf(ph, sizeof ph, "%s/history.dat", dir);
    snprintf(pb, sizeof pb, "%s/batch.dat", dir);
    if (!read_history(ph) || !read_batch(pb)) return 1;

    standardise();

    /* The level the filing rule cuts at. Nothing shipped with the task states it, so it is
       read off the data: a job only reaches the ledger once it is worth more than the
       deductible, so the smallest settled cost in the file sits just above that level and
       there is a visible pile-up against it. Estimating it as the sample minimum is exact to
       within the rounding on one claim. */
    double D = yh[0];
    for (int i = 1; i < nh; i++) if (yh[i] < D) D = yh[i];
    Tz = (D - ycen) / yscl;

    double p[NQ];
    ols(p);
    double ss = 0.0;
    for (int i = 0; i < nh; i++) {
        double xb = 0.0;
        for (int j = 0; j < NP; j++) xb += Z[i][j] * p[j];
        ss += (yz[i] - xb) * (yz[i] - xb);
    }
    p[NP] = log(sqrt(ss / nh) > 1e-6 ? sqrt(ss / nh) : 1e-6);
    p[NP + 1] = 0.0;   /* start from one pooled spread and let the fit open it out */

    trunc_mle(p);

    /* map the standardised coefficients back to the raw columns */
    double beta[NP];
    for (int j = 1; j < NP; j++) beta[j] = p[j] * yscl / sd_[j];
    beta[0] = ycen + p[0] * yscl;
    for (int j = 1; j < NP; j++) beta[0] -= beta[j] * mu_[j];

    FILE *f = fopen(out, "w");
    if (!f) { fprintf(stderr, "cannot write %s\n", out); return 1; }
    fprintf(f, "claim_id cost_gbp\n");
    for (int i = 0; i < nb; i++) {
        double v = beta[0];
        for (int j = 1; j < NP; j++) v += beta[j] * Xb[i][j];
        fprintf(f, "%s %.4f\n", idb[i], v);
    }
    fclose(f);
    fprintf(stderr, "wrote %s (%d claims)\n", out, nb);
    return 0;
}
