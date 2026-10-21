import pytest

from tools.streaming_metrics import StreamingMetric


def test_resource_summary_keeps_startup_and_peak_beyond_recent_window():
    metric = StreamingMetric(capacity=12)
    for value in [90] * 120 + [10] * 1200:
        metric.add(value)
    summary = metric.summary()
    assert summary["samples"] == 1320
    assert summary["mean"] == pytest.approx((90 * 120 + 10 * 1200) / 1320, abs=0.001)
    assert summary["max"] == 90
    assert summary["percentile_samples"] == 12
    assert summary["p95_is_estimate"]
    assert summary["scope"] == "full_run"


def test_missing_metrics_do_not_become_zero_measurements():
    metric = StreamingMetric()
    for value in (None, float("nan"), float("inf")):
        metric.add(value)
    assert metric.summary() is None
    for value in (2, 4, 6):
        metric.add(value)
    assert metric.summary()["mean"] == 4
    assert metric.summary()["samples"] == 3
    assert not metric.summary()["p95_is_estimate"]
