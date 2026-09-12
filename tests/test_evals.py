"""The eval harness judges every other change, so its own arithmetic matters.

A model answers the same question differently twice. Repeat runs exist to tell
a real regression apart from that spread -- but averaging must not be allowed
to hide a run where a guard actually leaked.
"""

from exposure_auditor.evals.runner import aggregate, check

THRESHOLDS = {
    "guards": {"errors": {"max": 0}, "namesake_leaks": {"max": 0}, "findings_outside_corpus": {"max": 0}},
    "live": {"recall": {"min": 0.8}, "likely_precision": {"min": 0.9}},
}


def _summary(**over):
    base = {
        "cases": 7, "errors": 0, "recall": 1.0, "likely_precision": 1.0, "namesake_leaks": 0,
        "findings_outside_corpus": 0, "p95_latency_s": 90.0,
    }
    return base | over


def test_quality_metrics_are_averaged_and_their_range_kept():
    mean, spread = aggregate([_summary(recall=1.0), _summary(recall=0.8), _summary(recall=0.9)])

    assert mean["recall"] == 0.9
    assert spread["recall"] == (0.8, 1.0)


def test_a_leak_in_one_run_is_not_averaged_away():
    # Two clean runs and one leak is a leaking agent, not a 0.33 leak.
    mean, spread = aggregate([_summary(), _summary(namesake_leaks=2), _summary()])

    assert mean["namesake_leaks"] == 2
    assert spread["namesake_leaks"] == (0, 2)
    assert check(mean, THRESHOLDS, "live") == [
        "namesake_leaks = 2 is above the guards maximum 0",
    ]


def test_an_error_in_one_run_fails_the_gate():
    mean, _ = aggregate([_summary(), _summary(errors=1)])

    assert mean["errors"] == 1
    assert any("errors" in f for f in check(mean, THRESHOLDS, "live"))


def test_a_single_run_aggregates_to_itself():
    mean, spread = aggregate([_summary(recall=0.85)])

    assert mean["recall"] == 0.85
    assert spread["recall"] == (0.85, 0.85)
    assert check(mean, THRESHOLDS, "live") == []


def test_a_mean_that_clears_the_bar_passes_even_with_a_weak_run():
    # Recall varies; the bar is the average, and the range is printed so a
    # reader can see how wide it was.
    mean, spread = aggregate([_summary(recall=0.75), _summary(recall=0.95)])

    assert mean["recall"] == 0.85
    assert spread["recall"] == (0.75, 0.95)
    assert check(mean, THRESHOLDS, "live") == []
