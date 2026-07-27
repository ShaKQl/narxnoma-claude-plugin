"""Turning many seller prices into one number."""
import statistics

_MIN_SAMPLES_FOR_IQR = 4
_IQR_FENCE = 1.5


def robust_median(prices: list[int]) -> tuple[float | None, list[int]]:
    """Median after IQR outlier stripping (only strips when >= 4 samples).

    Marketplaces carry both mis-listed accessories priced like phones and
    phones priced like accessories.
    """
    ordered = sorted(prices)
    if not ordered:
        return None, []
    if len(ordered) < _MIN_SAMPLES_FOR_IQR:
        return statistics.median(ordered), ordered
    q1, _, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    iqr = q3 - q1
    lo, hi = q1 - _IQR_FENCE * iqr, q3 + _IQR_FENCE * iqr
    kept = [p for p in ordered if lo <= p <= hi] or ordered
    return statistics.median(kept), kept
