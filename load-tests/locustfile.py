"""Load test for the auction critical path (Section 22 of the spec).

Run:
    locust -f load-tests/locustfile.py --host=http://localhost:8000

Or headless for a fixed scenario, e.g. 500 req/s for 60s with 500 users:
    locust -f load-tests/locustfile.py --host=http://localhost:8000 \
        --users 500 --spawn-rate 100 --run-time 60s --headless \
        --csv=load-tests/results/500rps

IMPORTANT: you must seed the database first (see README) so there is at
least one ad_slot_id and active campaigns for the simulated DSPs to bid on --
otherwise every auction will be a fast NO_BID rather than exercising the
full concurrent-bidding path.

Do not fabricate results: run this against your own docker-compose stack and
copy the actual P50/P95/P99/error-rate numbers into docs/performance.md.
"""
import os
import random
import uuid

from locust import HttpUser, between, task

AD_SLOT_ID = os.getenv("LOAD_TEST_AD_SLOT_ID", str(uuid.uuid4()))
COUNTRIES = ["US", "IN", "GB", "DE", "BR"]
DEVICES = ["mobile", "desktop", "tablet"]


class PublisherUser(HttpUser):
    """Simulates a publisher's ad server sending auction requests."""

    wait_time = between(0.01, 0.05)

    @task
    def run_auction(self):
        request_id = f"loadtest_{uuid.uuid4().hex}"
        payload = {
            "request_id": request_id,
            "user": {
                "id": f"user_{random.randint(1, 100000)}",
                "country": random.choice(COUNTRIES),
                "device": random.choice(DEVICES),
            },
            "ad_slot": {"id": AD_SLOT_ID, "width": 300, "height": 250},
        }
        with self.client.post(
            "/api/v1/auctions",
            json=payload,
            headers={"X-Client-Role": "PUBLISHER", "X-Client-Id": "loadtest-publisher"},
            catch_response=True,
        ) as response:
            if response.status_code not in (200, 201):
                response.failure(f"Unexpected status {response.status_code}: {response.text[:200]}")
            else:
                response.success()

    @task(1)
    def check_health(self):
        self.client.get("/health")
