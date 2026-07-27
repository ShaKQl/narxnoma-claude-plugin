from narxnoma.matching.stats import robust_median


def test_empty():
    assert robust_median([]) == (None, [])


def test_small_sample_is_not_stripped():
    median, kept = robust_median([100, 200, 300])
    assert median == 200
    assert kept == [100, 200, 300]


def test_iqr_strips_an_outlier():
    prices = [1000, 1010, 1020, 1030, 50000]
    median, kept = robust_median(prices)
    assert 50000 not in kept
    assert median == 1015


def test_never_returns_empty_kept():
    median, kept = robust_median([5, 5, 5, 5])
    assert kept
    assert median == 5
