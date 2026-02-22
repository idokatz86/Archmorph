"""
Tests for auto-recreation of sample diagram sessions.

When the in-memory SESSION_STORE loses a sample diagram's session
(container restart, TTL expiry, eviction), the get_or_recreate_session
helper must transparently rebuild it so downstream endpoints
(apply-answers, export, HLD, IaC, cost-estimate, …) keep working.
"""

import unittest

from routers.shared import SESSION_STORE
from routers.samples import (
    SAMPLE_DIAGRAMS,
    build_sample_analysis,
    get_or_recreate_session,
)


class TestBuildSampleAnalysis(unittest.TestCase):
    """Unit tests for the extracted build_sample_analysis helper."""

    def test_known_sample_returns_analysis(self):
        analysis = build_sample_analysis("aws-iaas", "sample-aws-iaas-abc123")
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis["diagram_id"], "sample-aws-iaas-abc123")
        self.assertEqual(analysis["source_provider"], "aws")
        self.assertTrue(analysis["is_sample"])
        self.assertGreater(analysis["services_detected"], 0)
        self.assertGreater(len(analysis["mappings"]), 0)

    def test_unknown_sample_returns_none(self):
        self.assertIsNone(build_sample_analysis("nonexistent", "sample-nonexistent-000000"))

    def test_deterministic(self):
        """Same inputs produce identical output (essential for recreate)."""
        a = build_sample_analysis("aws-iaas", "sample-aws-iaas-abc123")
        b = build_sample_analysis("aws-iaas", "sample-aws-iaas-abc123")
        self.assertEqual(a, b)

    def test_all_known_samples(self):
        """Every SAMPLE_DIAGRAMS entry should produce a valid analysis."""
        for sample in SAMPLE_DIAGRAMS:
            sid = sample["id"]
            analysis = build_sample_analysis(sid, f"sample-{sid}-aaaaaa")
            self.assertIsNotNone(analysis, f"build_sample_analysis returned None for {sid}")
            self.assertEqual(analysis["source_provider"], sample["provider"])
            self.assertTrue(analysis["is_sample"])

    def test_confidence_summary_present(self):
        analysis = build_sample_analysis("aws-iaas", "sample-aws-iaas-aaa111")
        cs = analysis["confidence_summary"]
        self.assertIn("high", cs)
        self.assertIn("medium", cs)
        self.assertIn("low", cs)
        self.assertIn("average", cs)
        self.assertEqual(cs["high"] + cs["medium"] + cs["low"], analysis["services_detected"])


class TestGetOrRecreateSession(unittest.TestCase):
    """Tests for the get_or_recreate_session transparent helper."""

    def setUp(self):
        # Clear any leftover sample sessions
        for k in SESSION_STORE.keys("sample-*"):
            SESSION_STORE.delete(k)

    def test_existing_session_returned(self):
        SESSION_STORE.set("sample-aws-iaas-abc123", {"diagram_id": "sample-aws-iaas-abc123", "existing": True})
        result = get_or_recreate_session("sample-aws-iaas-abc123")
        self.assertIsNotNone(result)
        self.assertTrue(result["existing"])  # returned the existing one, not a rebuild

    def test_missing_sample_session_recreated(self):
        """A sample session that is NOT in the store should be auto-rebuilt."""
        diagram_id = "sample-aws-iaas-f00d42"
        self.assertIsNone(SESSION_STORE.get(diagram_id))

        result = get_or_recreate_session(diagram_id)
        self.assertIsNotNone(result)
        self.assertEqual(result["diagram_id"], diagram_id)
        self.assertTrue(result["is_sample"])
        # It should now also be stored back
        self.assertIsNotNone(SESSION_STORE.get(diagram_id))

    def test_missing_non_sample_returns_none(self):
        """A regular (non-sample) diagram_id should NOT be recreated."""
        self.assertIsNone(get_or_recreate_session("abcde-12345"))

    def test_unknown_sample_id_returns_none(self):
        """A sample-prefixed ID with an unknown sample name returns None."""
        self.assertIsNone(get_or_recreate_session("sample-doesnotexist-aabbcc"))

    def test_malformed_sample_id_returns_none(self):
        """IDs that look like samples but don't match the pattern return None."""
        self.assertIsNone(get_or_recreate_session("sample-"))
        self.assertIsNone(get_or_recreate_session("sample-aws-iaas"))  # no hex suffix
        self.assertIsNone(get_or_recreate_session("sample-aws-iaas-ZZZZZZ"))  # non-hex

    def test_gcp_sample_recreated(self):
        diagram_id = "sample-gcp-iaas-d34d00"
        result = get_or_recreate_session(diagram_id)
        self.assertIsNotNone(result)
        self.assertEqual(result["source_provider"], "gcp")

    def tearDown(self):
        for k in SESSION_STORE.keys("sample-*"):
            SESSION_STORE.delete(k)


class TestSampleApplyAnswersEndpoint(unittest.TestCase):
    """Integration test: apply-answers on a sample diagram after session loss."""

    @classmethod
    def setUpClass(cls):
        from main import app
        from fastapi.testclient import TestClient
        cls.client = TestClient(app, raise_server_exceptions=False)

    def test_apply_answers_after_session_expired(self):
        """The endpoint should auto-recreate the sample session and succeed."""
        diagram_id = "sample-aws-iaas-beef42"
        # Make sure session is NOT in store
        SESSION_STORE.delete(diagram_id)

        resp = self.client.post(
            f"/api/diagrams/{diagram_id}/apply-answers",
            json={"environment": "production"},
        )
        # Should succeed (200) because the session is auto-recreated
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["diagram_id"], diagram_id)
        self.assertTrue(data.get("is_sample"))

    def test_apply_answers_non_sample_still_404(self):
        """Non-sample diagrams that are missing should still return 404."""
        resp = self.client.post(
            "/api/diagrams/nonexistent-12345/apply-answers",
            json={"environment": "production"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_export_diagram_after_session_expired(self):
        """export-diagram on an expired sample should also auto-recreate."""
        diagram_id = "sample-aws-iaas-c0ffee"
        SESSION_STORE.delete(diagram_id)

        resp = self.client.post(
            f"/api/diagrams/{diagram_id}/export-diagram?format=excalidraw",
        )
        self.assertEqual(resp.status_code, 200)

    def test_questions_after_session_expired(self):
        """questions endpoint on an expired sample should auto-recreate."""
        diagram_id = "sample-aws-iaas-d0d0d0"
        SESSION_STORE.delete(diagram_id)

        resp = self.client.post(f"/api/diagrams/{diagram_id}/questions")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("questions", data)

    def test_cost_estimate_after_session_expired(self):
        """cost-estimate on an expired sample should auto-recreate."""
        diagram_id = "sample-aws-iaas-fee1ee"
        SESSION_STORE.delete(diagram_id)

        resp = self.client.get(f"/api/diagrams/{diagram_id}/cost-estimate")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
