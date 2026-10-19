"""Monte Carlo on commodity prices.

Log prices revert towards the price deck:

    ln P_t = ln Deck_t + x_t,    x_t = phi * x_{t-1} + sigma * e_t,   e_t ~ N(0, 1)

so prices stay positive and right-skewed, shocks die out at rate `phi`, and the
expected price converges to the deck (the drift term removes the lognormal bias).
sigma comes from the realised price history (`calibrate.price_volatility`) unless set.
Prices of different products can be correlated through `corr`.
"""

from __future__ import annotations

import numpy as np


def mean_reverting_paths(
    deck: dict[str, np.ndarray],
    sigma: dict[str, float],
    phi: float = 0.7,
    n: int = 10_000,
    corr: np.ndarray | None = None,
    seed: int = 7,
    x0: dict[str, float] | None = None,
) -> dict[str, np.ndarray]:
    names = list(deck)
    T = len(next(iter(deck.values())))
    rng = np.random.default_rng(seed)
    k = len(names)
    corr = np.eye(k) if corr is None else np.asarray(corr)
    chol = np.linalg.cholesky(corr)
    shocks = rng.standard_normal((n, T, k)) @ chol.T
    x = np.zeros((n, k)) + np.array([(x0 or {}).get(nm, 0.0) for nm in names])
    out = {nm: np.empty((n, T)) for nm in names}
    sig = np.array([sigma[nm] for nm in names])
    var = np.zeros(k)
    for t in range(T):
        x = phi * x + sig * shocks[:, t, :]
        var = phi**2 * var + sig**2  # variance of x_t, so E[exp(x_t - var/2)] = 1
        for j, nm in enumerate(names):
            out[nm][:, t] = deck[nm][t] * np.exp(x[:, j] - 0.5 * var[j])
    return out


def summary(values: np.ndarray, price: float) -> dict[str, float]:
    q = np.percentile(values, [5, 25, 50, 75, 95])
    return {
        "mean": float(values.mean()),
        "p5": q[0],
        "p25": q[1],
        "median": q[2],
        "p75": q[3],
        "p95": q[4],
        "prob_above_price": float((values > price).mean()),
    }
