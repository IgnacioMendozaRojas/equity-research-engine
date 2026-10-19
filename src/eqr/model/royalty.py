"""Price-linked royalties and government take.

Chile's Corfo lease for the Salar de Atacama (2018 agreement) charges a progressive
rate on the lithium carbonate sale price. Each rate applies to the slice of the
price inside its bracket, like income-tax brackets:

    US$/t        rate
    0 - 4,000    6.8%
    4,000-5,000  8.0%
    5,000-6,000  10%
    6,000-7,000  17%
    7,000-10,000 25%
    > 10,000     40%

At US$12,000/t the payment is US$2,172/t (18.1% average) and each extra dollar of
price keeps only 60 cents before income tax, which is why lithium margins do not
scale one-for-one with price.
"""

from __future__ import annotations

import numpy as np

CORFO_LITHIUM_CARBONATE = [
    (0.0, 0.068),
    (4_000.0, 0.08),
    (5_000.0, 0.10),
    (6_000.0, 0.17),
    (7_000.0, 0.25),
    (10_000.0, 0.40),
]
CORFO_POTASSIUM_CHLORIDE = [
    (0.0, 0.03),
    (300.0, 0.07),
    (400.0, 0.10),
    (500.0, 0.15),
    (600.0, 0.20),
]


def bracket_payment(price: np.ndarray | float, brackets: list[tuple[float, float]]) -> np.ndarray:
    """Payment per unit for a progressive (marginal) schedule. Vectorised over price."""
    p = np.asarray(price, dtype=float)
    lows = np.array([b[0] for b in brackets])
    rates = np.array([b[1] for b in brackets])
    highs = np.append(lows[1:], np.inf)
    slice_ = np.clip(p[..., None] - lows, 0.0, highs - lows)
    return (slice_ * rates).sum(axis=-1)


def average_rate(price: np.ndarray | float, brackets: list[tuple[float, float]]) -> np.ndarray:
    p = np.asarray(price, dtype=float)
    return np.divide(bracket_payment(p, brackets), p, out=np.zeros_like(p), where=p > 0)
