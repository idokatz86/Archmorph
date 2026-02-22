"""
Archmorph Load Testing Framework (Issue #149).

Locust-based load test scripts for validating SLA targets.
Run: locust -f tests/load_test.py --host https://api.archmorph.dev
"""

import json
import os
import random
import uuid

from locust import HttpUser, task, between, tag, events
from locust.runners import MasterRunner


# ─────────────────────────────────────────────────────────
# SLA targets
# ─────────────────────────────────────────────────────────
SLA_P95_MS = int(os.getenv("SLA_P95_MS", "2000"))
SLA_P99_MS = int(os.getenv("SLA_P99_MS", "5000"))
SLA_ERROR_RATE_PCT = float(os.getenv("SLA_ERROR_RATE_PCT", "1.0"))

API_KEY = os.getenv("ARCHMORPH_API_KEY", "test-api-key")

HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY,
}


# ─────────────────────────────────────────────────────────
# Sample payloads
# ─────────────────────────────────────────────────────────
SAMPLE_SERVICES = [
    "EC2", "S3", "Lambda", "RDS", "DynamoDB", "EKS",
    "CloudFront", "Route 53", "SQS", "SNS", "API Gateway",
    "ElastiCache", "ECS", "Fargate", "Kinesis", "Step Functions",
]

SAMPLE_PROVIDERS = ["aws", "gcp"]


def _make_analysis_payload():
    """Generate a realistic analysis payload."""
    num_services = random.randint(3, 12)
    services = random.sample(SAMPLE_SERVICES, min(num_services, len(SAMPLE_SERVICES)))
    return {
        "diagram_type": "architecture",
        "source_provider": random.choice(SAMPLE_PROVIDERS),
        "services": services,
    }


class ArchmorphHealthUser(HttpUser):
    """Lightweight user that only hits health endpoint."""
    weight = 3
    wait_time = between(1, 5)

    @tag("health", "smoke")
    @task
    def health_check(self):
        self.client.get("/api/health", headers=HEADERS)

    @tag("health")
    @task
    def version_check(self):
        self.client.get("/api/version", headers=HEADERS)


class ArchmorphBrowseUser(HttpUser):
    """Read-heavy user browsing existing analyses."""
    weight = 5
    wait_time = between(2, 8)

    def on_start(self):
        self.diagram_ids = []

    @tag("browse", "samples")
    @task(3)
    def list_samples(self):
        self.client.get("/api/samples", headers=HEADERS)

    @tag("browse", "mappings")
    @task(2)
    def get_mappings(self):
        self.client.get("/api/services/mappings", headers=HEADERS)

    @tag("browse")
    @task(2)
    def list_feature_flags(self):
        self.client.get("/api/feature-flags", headers=HEADERS)

    @tag("browse")
    @task(1)
    def get_roadmap(self):
        self.client.get("/api/roadmap", headers=HEADERS)


class ArchmorphAnalyzeUser(HttpUser):
    """User performing architecture analysis (write-heavy)."""
    weight = 2
    wait_time = between(5, 15)

    def on_start(self):
        self.diagram_id = None

    @tag("analyze", "core")
    @task(3)
    def suggest_mapping(self):
        service = random.choice(SAMPLE_SERVICES)
        self.client.post(
            "/api/suggest/mapping",
            json={
                "source_service": service,
                "source_provider": "aws",
            },
            headers=HEADERS,
        )

    @tag("analyze", "risk")
    @task(1)
    def risk_score(self):
        if self.diagram_id:
            self.client.get(
                f"/api/diagrams/{self.diagram_id}/risk-score",
                headers=HEADERS,
            )

    @tag("analyze", "compliance")
    @task(1)
    def compliance_check(self):
        if self.diagram_id:
            self.client.get(
                f"/api/diagrams/{self.diagram_id}/compliance",
                headers=HEADERS,
            )

    @tag("analyze", "dependency")
    @task(1)
    def dependency_graph(self):
        if self.diagram_id:
            self.client.get(
                f"/api/diagrams/{self.diagram_id}/dependency-graph",
                headers=HEADERS,
            )


class ArchmorphPowerUser(HttpUser):
    """Power user: analyzes, generates IaC, exports HLD."""
    weight = 1
    wait_time = between(10, 30)

    @tag("power", "batch")
    @task
    def batch_suggest(self):
        services = [{"name": s} for s in random.sample(SAMPLE_SERVICES, 5)]
        self.client.post(
            "/api/suggest/batch",
            json={"services": services, "source_provider": "aws"},
            headers=HEADERS,
        )

    @tag("power", "import")
    @task
    def import_infrastructure(self):
        # Minimal Terraform state for parsing
        content = json.dumps({
            "version": 4,
            "terraform_version": "1.5.0",
            "resources": [
                {
                    "type": "aws_instance",
                    "name": "web",
                    "provider": "provider[\"registry.terraform.io/hashicorp/aws\"]",
                    "instances": [{"attributes": {"id": "i-12345", "instance_type": "t3.medium"}}],
                },
                {
                    "type": "aws_s3_bucket",
                    "name": "data",
                    "provider": "provider[\"registry.terraform.io/hashicorp/aws\"]",
                    "instances": [{"attributes": {"id": "my-bucket", "bucket": "my-bucket"}}],
                },
            ],
        })
        self.client.post(
            "/api/import/infrastructure",
            json={"content": content, "format": "terraform_state"},
            headers=HEADERS,
        )


# ─────────────────────────────────────────────────────────
# SLA validation hook
# ─────────────────────────────────────────────────────────
@events.quitting.add_listener
def check_sla(environment, **kwargs):
    """Fail the test if SLA targets are not met."""
    stats = environment.stats
    total = stats.total

    if total.num_requests == 0:
        return

    error_rate = (total.num_failures / total.num_requests) * 100
    p95 = total.get_response_time_percentile(0.95) or 0
    p99 = total.get_response_time_percentile(0.99) or 0

    sla_pass = True
    results = []

    if p95 > SLA_P95_MS:
        results.append(f"FAIL: P95 latency {p95:.0f}ms > {SLA_P95_MS}ms target")
        sla_pass = False
    else:
        results.append(f"PASS: P95 latency {p95:.0f}ms <= {SLA_P95_MS}ms target")

    if p99 > SLA_P99_MS:
        results.append(f"FAIL: P99 latency {p99:.0f}ms > {SLA_P99_MS}ms target")
        sla_pass = False
    else:
        results.append(f"PASS: P99 latency {p99:.0f}ms <= {SLA_P99_MS}ms target")

    if error_rate > SLA_ERROR_RATE_PCT:
        results.append(f"FAIL: Error rate {error_rate:.2f}% > {SLA_ERROR_RATE_PCT}% target")
        sla_pass = False
    else:
        results.append(f"PASS: Error rate {error_rate:.2f}% <= {SLA_ERROR_RATE_PCT}% target")

    print("\n" + "=" * 60)
    print("SLA VALIDATION RESULTS")
    print("=" * 60)
    for r in results:
        print(f"  {r}")
    print(f"\nOverall: {'PASS' if sla_pass else 'FAIL'}")
    print(f"Total requests: {total.num_requests}")
    print(f"Total failures: {total.num_failures}")
    print(f"Avg response time: {total.avg_response_time:.0f}ms")
    print("=" * 60 + "\n")

    if not sla_pass:
        environment.process_exit_code = 1
