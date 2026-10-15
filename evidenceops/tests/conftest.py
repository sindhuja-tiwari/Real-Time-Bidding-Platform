import json

import pytest

from evidenceops.telemetry import parse_ts


@pytest.fixture
def run_dir(tmp_path):
    obs = tmp_path / "observed"
    (obs / "db").mkdir(parents=True)
    (obs / "logs").mkdir()
    (obs / "traces").mkdir()
    (obs / "incident.json").write_text(
        json.dumps(
            {
                "incident_id": "inc-test",
                "report": "r",
                "telemetry_window": ["2026-10-15T13:00:00.000+00:00", "2026-10-15T13:01:00.000+00:00"],
                "alert": {"metric": "auction_success_rate", "definition": "d", "timeline": []},
            }
        )
    )
    (obs / "deployments.jsonl").write_text("")
    (obs / "db" / "dsps.csv").write_text("id,name,endpoint,timeout_ms,status\n1,DSP-A,x,100,ACTIVE\n")
    (obs / "db" / "bids.csv").write_text(
        "id,auction_id,dsp_name,campaign_id,amount,response_time_ms,status,created_at\n"
        "1,a,DSP-A,c,2.5,25,WON,2026-10-15 13:00:10.5+00\n"
        "2,b,DSP-A,,0,15,TIMEOUT,2026-10-15 13:00:40.123456789+00\n"
        "3,c,DSP-A,,0,15,TIMEOUT,2026-10-15 13:00:41+00\n"
    )
    (obs / "logs" / "backend.log").write_text(
        'backend-1  | 2026-10-15T13:00:40.000000001Z {"event": "auction_global_timeout", "level": "warning"}\n'
        "backend-1  | 2026-10-15T13:00:41.000000001Z sqlalchemy.exc.TimeoutError: QueuePool limit of size 2 overflow 0 reached\n"
        'backend-1  | 2026-10-15T13:00:42.000000001Z INFO:     172.18.0.1:5 - "POST /api/v1/auctions HTTP/1.1" 500 Internal Server Error\n'
    )
    span = {
        "traceId": "t1", "spanId": "s1", "name": "db.pool.acquire",
        "startTimeUnixNano": str(int(parse_ts("2026-10-15T13:00:45Z") * 1e9)),
        "endTimeUnixNano": str(int((parse_ts("2026-10-15T13:00:45Z") + 1.5) * 1e9)),
        "attributes": [{"key": "db.pool.size", "value": {"intValue": "2"}}],
    }
    (obs / "traces" / "spans.otlp.jsonl").write_text(
        json.dumps({"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}) + "\n"
    )
    return tmp_path
