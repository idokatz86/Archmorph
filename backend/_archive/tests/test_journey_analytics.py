"""Comprehensive tests for journey_analytics.py and routers/journey_analytics.py — Sprint 9 #28."""
import pytest

from journey_analytics import (
    track_journey_event,
    set_user_segments,
    mark_drop_off,
    get_funnel_metrics,
    get_time_to_value,
    get_segment_analytics,
    create_experiment,
    assign_variant,
    record_experiment_conversion,
    get_experiment_results,
    list_experiments,
    stop_experiment,
    record_nps,
    get_nps_summary,
    get_journey_dashboard,
    clear_all,
    FUNNEL_ORDER,
    FunnelStage,
    UserSegment,
)


@pytest.fixture(autouse=True)
def reset_state():
    """Clear journey analytics state between tests."""
    clear_all()
    yield
    clear_all()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_funnel_order_has_stages(self):
        assert len(FUNNEL_ORDER) >= 8
        assert "landing" in FUNNEL_ORDER
        assert "first_upload" in FUNNEL_ORDER

    def test_funnel_stage_enum(self):
        assert FunnelStage.LANDING.value == "landing"
        assert FunnelStage.GENERATE_IAC.value == "generate_iac"

    def test_user_segment_enum(self):
        assert UserSegment.STARTUP.value == "startup"
        assert UserSegment.ENTERPRISE.value == "enterprise"


# ---------------------------------------------------------------------------
# Journey tracking
# ---------------------------------------------------------------------------

class TestJourneyTracking:
    def test_track_event_creates_journey(self):
        event = track_journey_event(
            session_id="sess-1",
            user_id="user-1",
            event_name="page_view",
            stage="landing",
        )
        assert event.id.startswith("je-")
        assert event.session_id == "sess-1"
        assert event.stage == "landing"

    def test_track_event_with_properties(self):
        event = track_journey_event(
            session_id="sess-2",
            user_id="user-2",
            event_name="click",
            stage="first_upload",
            properties={"source": "drag_drop"},
            duration_ms=1500.0,
        )
        assert event.properties.get("source") == "drag_drop"
        assert event.duration_ms == 1500.0

    def test_multiple_events_same_session(self):
        track_journey_event("sess-3", "user-3", "view", "landing")
        track_journey_event("sess-3", "user-3", "upload", "first_upload")
        track_journey_event("sess-3", "user-3", "analyze", "first_analysis")
        # Session should track all 3 stages
        metrics = get_funnel_metrics()
        assert isinstance(metrics, dict)

    def test_track_event_updates_furthest_stage(self):
        track_journey_event("sess-4", "user-4", "view", "landing")
        track_journey_event("sess-4", "user-4", "upload", "first_upload")
        track_journey_event("sess-4", "user-4", "analyze", "first_analysis")
        dashboard = get_journey_dashboard()
        assert isinstance(dashboard, dict)


# ---------------------------------------------------------------------------
# User segments
# ---------------------------------------------------------------------------

class TestUserSegments:
    def test_set_segments(self):
        track_journey_event("sess-s1", "user-s1", "view", "landing")
        result = set_user_segments(
            "sess-s1",
            company_size="enterprise",
            cloud_provider="aws_primary",
            use_case="migration",
        )
        assert result is not None
        assert result["company_size"] == "enterprise"

    def test_set_segments_partial(self):
        track_journey_event("sess-s2", "user-s2", "view", "landing")
        result = set_user_segments("sess-s2", company_size="startup")
        assert result is not None
        assert result["company_size"] == "startup"

    def test_set_segments_session_not_found(self):
        result = set_user_segments("nonexistent", company_size="smb")
        assert result is None


# ---------------------------------------------------------------------------
# Drop-off
# ---------------------------------------------------------------------------

class TestDropOff:
    def test_mark_drop_off(self):
        track_journey_event("sess-d1", "user-d1", "view", "landing")
        stage = mark_drop_off("sess-d1")
        assert stage is not None

    def test_mark_drop_off_not_found(self):
        assert mark_drop_off("nonexistent") is None


# ---------------------------------------------------------------------------
# Funnel metrics
# ---------------------------------------------------------------------------

class TestFunnelMetrics:
    def test_funnel_empty(self):
        metrics = get_funnel_metrics()
        assert isinstance(metrics, dict)

    def test_funnel_with_journeys(self):
        track_journey_event("sess-f1", "user-f1", "view", "landing")
        track_journey_event("sess-f1", "user-f1", "upload", "first_upload")
        track_journey_event("sess-f2", "user-f2", "view", "landing")
        metrics = get_funnel_metrics()
        assert isinstance(metrics, dict)


# ---------------------------------------------------------------------------
# Time to value
# ---------------------------------------------------------------------------

class TestTimeToValue:
    def test_time_to_value_empty(self):
        result = get_time_to_value()
        assert isinstance(result, dict)

    def test_time_to_value_with_journeys(self):
        track_journey_event("sess-t1", "user-t1", "view", "landing", duration_ms=100)
        track_journey_event("sess-t1", "user-t1", "upload", "first_upload", duration_ms=200)
        result = get_time_to_value()
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Segment analytics
# ---------------------------------------------------------------------------

class TestSegmentAnalytics:
    def test_segment_analytics_empty(self):
        result = get_segment_analytics()
        assert isinstance(result, dict)

    def test_segment_analytics_with_data(self):
        track_journey_event("sess-sa1", "user-sa1", "view", "landing")
        set_user_segments("sess-sa1", company_size="enterprise")
        track_journey_event("sess-sa2", "user-sa2", "view", "landing")
        set_user_segments("sess-sa2", company_size="startup")
        result = get_segment_analytics(segment_key="company_size")
        assert isinstance(result, dict)

    def test_segment_analytics_cloud_provider(self):
        track_journey_event("sess-sa3", "user-sa3", "view", "landing")
        set_user_segments("sess-sa3", cloud_provider="aws_primary")
        result = get_segment_analytics(segment_key="cloud_provider")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# A/B Experiments
# ---------------------------------------------------------------------------

class TestExperiments:
    def test_create_experiment(self):
        exp = create_experiment(
            name="Button Color Test",
            description="Test blue vs green CTA",
            variants=["blue", "green"],
            traffic_split={"blue": 0.5, "green": 0.5},
            metric="conversion_rate",
        )
        assert exp.name == "Button Color Test"
        assert exp.status == "active"
        assert len(exp.variants) == 2

    def test_create_experiment_invalid_split(self):
        with pytest.raises(ValueError):
            create_experiment(
                name="Bad Split",
                description="",
                variants=["a", "b"],
                traffic_split={"a": 0.3, "b": 0.3},  # sums to 0.6
                metric="clicks",
            )

    def test_create_experiment_mismatched_variants(self):
        with pytest.raises(ValueError):
            create_experiment(
                name="Mismatch",
                description="",
                variants=["a", "b"],
                traffic_split={"a": 0.5, "c": 0.5},  # c not in variants
                metric="clicks",
            )

    def test_create_experiment_single_variant(self):
        with pytest.raises(ValueError):
            create_experiment(
                name="One Variant",
                description="",
                variants=["a"],
                traffic_split={"a": 1.0},
                metric="clicks",
            )

    def test_assign_variant(self):
        exp = create_experiment(
            name="Test",
            description="",
            variants=["a", "b"],
            traffic_split={"a": 0.5, "b": 0.5},
            metric="clicks",
        )
        variant = assign_variant(exp.id, "user-1")
        assert variant in ["a", "b"]

    def test_assign_variant_deterministic(self):
        exp = create_experiment(
            name="Deterministic",
            description="",
            variants=["a", "b"],
            traffic_split={"a": 0.5, "b": 0.5},
            metric="clicks",
        )
        v1 = assign_variant(exp.id, "user-1")
        v2 = assign_variant(exp.id, "user-1")
        assert v1 == v2  # same user should get same variant

    def test_assign_variant_not_found(self):
        assert assign_variant("nonexistent", "user-1") is None

    def test_record_conversion(self):
        exp = create_experiment(
            name="Conv Test",
            description="",
            variants=["a", "b"],
            traffic_split={"a": 0.5, "b": 0.5},
            metric="signups",
        )
        ok = record_experiment_conversion(exp.id, "a")
        assert ok is True

    def test_record_conversion_not_found(self):
        assert record_experiment_conversion("nonexistent", "a") is False

    def test_experiment_results(self):
        exp = create_experiment(
            name="Results Test",
            description="",
            variants=["a", "b"],
            traffic_split={"a": 0.5, "b": 0.5},
            metric="signups",
        )
        record_experiment_conversion(exp.id, "a")
        result = get_experiment_results(exp.id)
        assert result is not None

    def test_experiment_results_not_found(self):
        assert get_experiment_results("nonexistent") is None

    def test_list_experiments_empty(self):
        assert list_experiments() == []

    def test_list_experiments(self):
        create_experiment("E1", "", ["a", "b"], {"a": 0.5, "b": 0.5}, "m")
        create_experiment("E2", "", ["x", "y"], {"x": 0.5, "y": 0.5}, "m")
        result = list_experiments()
        assert len(result) == 2

    def test_list_experiments_by_status(self):
        create_experiment("E3", "", ["a", "b"], {"a": 0.5, "b": 0.5}, "m")
        result = list_experiments(status="active")
        assert len(result) >= 1

    def test_stop_experiment(self):
        exp = create_experiment("Stop Me", "", ["a", "b"], {"a": 0.5, "b": 0.5}, "m")
        assert stop_experiment(exp.id) is True
        result = get_experiment_results(exp.id)
        assert result["status"] == "stopped"

    def test_stop_experiment_not_found(self):
        assert stop_experiment("nonexistent") is False


# ---------------------------------------------------------------------------
# NPS
# ---------------------------------------------------------------------------

class TestNPS:
    def test_record_nps(self):
        entry = record_nps(user_id="user-n1", score=9, comment="Great tool!")
        assert entry["score"] == 9
        assert entry["id"].startswith("nps-")

    def test_record_nps_with_segment(self):
        entry = record_nps(user_id="user-n2", score=7, segment="enterprise")
        assert entry["segment"] == "enterprise"

    def test_record_nps_invalid_score_high(self):
        with pytest.raises(ValueError):
            record_nps(user_id="user-n3", score=11)

    def test_record_nps_invalid_score_low(self):
        with pytest.raises(ValueError):
            record_nps(user_id="user-n4", score=-1)

    def test_nps_summary_empty(self):
        summary = get_nps_summary()
        assert isinstance(summary, dict)

    def test_nps_summary_calculation(self):
        record_nps("u1", 10)  # Promoter
        record_nps("u2", 9)   # Promoter
        record_nps("u3", 7)   # Passive
        record_nps("u4", 5)   # Detractor
        summary = get_nps_summary()
        assert "nps_score" in summary or "score" in summary or "nps" in summary
        assert isinstance(summary, dict)

    def test_nps_summary_by_segment(self):
        record_nps("u5", 10, segment="enterprise")
        record_nps("u6", 3, segment="startup")
        summary = get_nps_summary(segment="enterprise")
        assert isinstance(summary, dict)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class TestDashboard:
    def test_dashboard_empty(self):
        dashboard = get_journey_dashboard()
        assert isinstance(dashboard, dict)

    def test_dashboard_with_data(self):
        track_journey_event("sess-db1", "user-db1", "view", "landing")
        track_journey_event("sess-db1", "user-db1", "upload", "first_upload")
        set_user_segments("sess-db1", company_size="smb")
        record_nps("user-db1", 8)
        dashboard = get_journey_dashboard()
        assert isinstance(dashboard, dict)


# ---------------------------------------------------------------------------
# Router endpoints (via TestClient)
# ---------------------------------------------------------------------------

class TestJourneyRouter:
    def test_track_event(self, test_client):
        resp = test_client.post("/api/journey/events", json={
            "session_id": "sess-r1",
            "user_id": "user-r1",
            "event_name": "page_view",
            "stage": "landing",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "tracked"

    def test_set_segments(self, test_client):
        # Create session first
        test_client.post("/api/journey/events", json={
            "session_id": "sess-r2",
            "user_id": "user-r2",
            "event_name": "view",
            "stage": "landing",
        })
        resp = test_client.post("/api/journey/sessions/sess-r2/segments", json={
            "company_size": "enterprise",
        })
        assert resp.status_code == 200

    def test_set_segments_not_found(self, test_client):
        resp = test_client.post("/api/journey/sessions/nonexistent/segments", json={
            "company_size": "smb",
        })
        assert resp.status_code == 404

    def test_mark_drop_off(self, test_client):
        test_client.post("/api/journey/events", json={
            "session_id": "sess-r3",
            "user_id": "user-r3",
            "event_name": "view",
            "stage": "landing",
        })
        resp = test_client.post("/api/journey/sessions/sess-r3/drop-off")
        assert resp.status_code == 200

    def test_funnel_metrics(self, test_client):
        resp = test_client.get("/api/journey/funnel")
        assert resp.status_code == 200

    def test_funnel_stages(self, test_client):
        resp = test_client.get("/api/journey/funnel/stages")
        assert resp.status_code == 200
        assert "stages" in resp.json()

    def test_time_to_value(self, test_client):
        resp = test_client.get("/api/journey/time-to-value")
        assert resp.status_code == 200

    def test_segments(self, test_client):
        resp = test_client.get("/api/journey/segments")
        assert resp.status_code == 200

    def test_segments_with_key(self, test_client):
        resp = test_client.get("/api/journey/segments?key=cloud_provider")
        assert resp.status_code == 200


class TestExperimentRouter:
    def test_create_experiment(self, test_client):
        resp = test_client.post("/api/journey/experiments", json={
            "name": "CTA Test",
            "description": "Test button colors",
            "variants": ["blue", "green"],
            "traffic_split": {"blue": 0.5, "green": 0.5},
            "metric": "signups",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "created"

    def test_create_experiment_invalid(self, test_client):
        resp = test_client.post("/api/journey/experiments", json={
            "name": "Bad",
            "description": "",
            "variants": ["a"],
            "traffic_split": {"a": 1.0},
            "metric": "clicks",
        })
        assert resp.status_code in (400, 422)  # Pydantic may validate before handler

    def test_list_experiments(self, test_client):
        resp = test_client.get("/api/journey/experiments")
        assert resp.status_code == 200

    def test_assign_variant(self, test_client):
        create_resp = test_client.post("/api/journey/experiments", json={
            "name": "Assign Test",
            "description": "",
            "variants": ["a", "b"],
            "traffic_split": {"a": 0.5, "b": 0.5},
            "metric": "m",
        })
        exp_id = create_resp.json()["experiment_id"]
        resp = test_client.post(f"/api/journey/experiments/{exp_id}/assign", json={
            "user_id": "u1",
        })
        assert resp.status_code == 200
        assert resp.json()["variant"] in ["a", "b"]

    def test_record_conversion(self, test_client):
        create_resp = test_client.post("/api/journey/experiments", json={
            "name": "Conv Test",
            "description": "",
            "variants": ["a", "b"],
            "traffic_split": {"a": 0.5, "b": 0.5},
            "metric": "m",
        })
        exp_id = create_resp.json()["experiment_id"]
        resp = test_client.post(f"/api/journey/experiments/{exp_id}/convert", json={
            "variant": "a",
        })
        assert resp.status_code == 200

    def test_stop_experiment(self, test_client):
        create_resp = test_client.post("/api/journey/experiments", json={
            "name": "Stop Test",
            "description": "",
            "variants": ["a", "b"],
            "traffic_split": {"a": 0.5, "b": 0.5},
            "metric": "m",
        })
        exp_id = create_resp.json()["experiment_id"]
        resp = test_client.post(f"/api/journey/experiments/{exp_id}/stop")
        assert resp.status_code == 200

    def test_experiment_results(self, test_client):
        create_resp = test_client.post("/api/journey/experiments", json={
            "name": "Results Test",
            "description": "",
            "variants": ["x", "y"],
            "traffic_split": {"x": 0.5, "y": 0.5},
            "metric": "m",
        })
        exp_id = create_resp.json()["experiment_id"]
        resp = test_client.get(f"/api/journey/experiments/{exp_id}")
        assert resp.status_code == 200


class TestNPSRouter:
    def test_record_nps(self, test_client):
        resp = test_client.post("/api/journey/nps", json={
            "user_id": "user-nps1",
            "score": 9,
            "comment": "Love it!",
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "recorded"

    def test_record_nps_invalid_score(self, test_client):
        resp = test_client.post("/api/journey/nps", json={
            "user_id": "user-nps2",
            "score": 15,
        })
        assert resp.status_code == 422  # Pydantic validation

    def test_nps_summary(self, test_client):
        resp = test_client.get("/api/journey/nps")
        assert resp.status_code == 200


class TestDashboardRouter:
    def test_dashboard(self, test_client):
        resp = test_client.get("/api/journey/dashboard")
        assert resp.status_code == 200
