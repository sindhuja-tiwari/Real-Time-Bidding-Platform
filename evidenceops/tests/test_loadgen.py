from evidenceops.loadgen import RequestOutcome, bucketed, success_rate, window


def outcome(seq, sent_at, status=201, auction="COMPLETED", error=None, latency=100.0):
    return RequestOutcome(seq, f"r{seq}", "p", sent_at, latency, status, auction, None, None, error)


def test_success_requires_201_and_completed():
    assert outcome(0, 0).success
    assert not outcome(0, 0, auction="NO_BID").success
    assert not outcome(0, 0, status=500, auction=None).success
    assert not outcome(0, 0, status=None, auction=None, error="client_timeout").success


def test_success_rate_and_window():
    items = [outcome(0, 0.0), outcome(1, 5.0, auction="NO_BID"), outcome(2, 10.0)]
    assert success_rate(items) == 2 / 3
    assert success_rate([]) is None
    assert [o.seq for o in window(items, 5.0, 10.0)] == [1]


def test_bucketed_groups_failures_by_reason():
    items = [
        outcome(0, 100.0),
        outcome(1, 101.0, auction="NO_BID"),
        outcome(2, 112.0, status=None, auction=None, error="client_timeout", latency=2000.0),
    ]
    rows = bucketed(items, start=100.0, bucket_s=10.0)
    assert [r["offset_s"] for r in rows] == [0.0, 10.0]
    assert rows[0]["success_rate"] == 0.5 and rows[0]["failures"] == {"no_bid": 1}
    assert rows[1]["failures"] == {"client_timeout": 1}
