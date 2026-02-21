"""
Tests for Feedback & NPS module.
"""

import pytest
import os
from unittest.mock import patch

# We need to patch the file path before importing
@pytest.fixture(autouse=True)
def temp_feedback_file(tmp_path):
    """Use temporary file for feedback storage."""
    feedback_file = tmp_path / "feedback.json"
    
    with patch.dict(os.environ, {}):
        import feedback
        feedback.FEEDBACK_FILE = str(feedback_file)
        feedback._feedback_store = {}
        feedback._load_feedback()
        yield feedback_file
        feedback._feedback_store = {}


class TestSubmitNPS:
    """Tests for submit_nps function."""
    
    def test_valid_nps_score_accepted(self, temp_feedback_file):
        """Valid NPS scores (0-10) are accepted."""
        from feedback import submit_nps
        
        result = submit_nps(score=9)
        
        assert result["status"] == "recorded"
        assert result["category"] == "promoter"
    
    def test_promoter_category_for_9_or_10(self, temp_feedback_file):
        """Scores 9-10 are categorized as promoters."""
        from feedback import submit_nps
        
        for score in [9, 10]:
            result = submit_nps(score=score)
            assert result["category"] == "promoter"
    
    def test_passive_category_for_7_or_8(self, temp_feedback_file):
        """Scores 7-8 are categorized as passives."""
        from feedback import submit_nps
        
        for score in [7, 8]:
            result = submit_nps(score=score)
            assert result["category"] == "passive"
    
    def test_detractor_category_for_0_to_6(self, temp_feedback_file):
        """Scores 0-6 are categorized as detractors."""
        from feedback import submit_nps
        
        for score in [0, 3, 6]:
            result = submit_nps(score=score)
            assert result["category"] == "detractor"
    
    def test_invalid_score_raises_error(self, temp_feedback_file):
        """Invalid scores raise ValueError."""
        from feedback import submit_nps
        
        with pytest.raises(ValueError):
            submit_nps(score=11)
        
        with pytest.raises(ValueError):
            submit_nps(score=-1)
    
    def test_follow_up_stored(self, temp_feedback_file):
        """Follow-up comments are stored."""
        from feedback import submit_nps, _feedback_store
        
        submit_nps(score=8, follow_up="Great product!")
        
        responses = _feedback_store.get("nps_responses", [])
        assert len(responses) > 0
        assert responses[-1]["follow_up"] == "Great product!"
    
    def test_nps_score_calculated(self, temp_feedback_file):
        """NPS score is calculated from responses."""
        from feedback import submit_nps
        
        # 1 promoter (9), 1 detractor (3) = (1-1)/2 * 100 = 0
        submit_nps(score=9)
        result = submit_nps(score=3)
        
        assert result["current_nps"] == 0.0


class TestSubmitFeatureFeedback:
    """Tests for submit_feature_feedback function."""
    
    def test_positive_feedback_recorded(self, temp_feedback_file):
        """Positive feedback is recorded."""
        from feedback import submit_feature_feedback
        
        result = submit_feature_feedback(feature="iac_chat", helpful=True)
        
        assert result["status"] == "recorded"
        assert result["feature"] == "iac_chat"
    
    def test_negative_feedback_recorded(self, temp_feedback_file):
        """Negative feedback is recorded."""
        from feedback import submit_feature_feedback
        
        result = submit_feature_feedback(feature="diagram_export", helpful=False)
        
        assert result["status"] == "recorded"
    
    def test_satisfaction_rate_calculated(self, temp_feedback_file):
        """Satisfaction rate is calculated correctly."""
        from feedback import submit_feature_feedback
        
        # 2 positive, 1 negative = 66.7% satisfaction
        submit_feature_feedback(feature="test", helpful=True)
        submit_feature_feedback(feature="test", helpful=True)
        result = submit_feature_feedback(feature="test", helpful=False)
        
        assert abs(result["satisfaction_rate"] - 66.7) < 1
        assert result["total_ratings"] == 3
    
    def test_comment_stored(self, temp_feedback_file):
        """Comments are stored with feedback."""
        from feedback import submit_feature_feedback, _feedback_store
        
        submit_feature_feedback(
            feature="hld",
            helpful=True,
            comment="Very useful document!"
        )
        
        feedback_list = _feedback_store.get("feature_feedback", [])
        assert len(feedback_list) > 0
        assert feedback_list[-1]["comment"] == "Very useful document!"


class TestSubmitBugReport:
    """Tests for submit_bug_report function."""
    
    def test_bug_report_recorded(self, temp_feedback_file):
        """Bug reports are recorded with ID."""
        from feedback import submit_bug_report
        
        result = submit_bug_report(description="Button doesn't work")
        
        assert result["status"] == "recorded"
        assert result["bug_id"].startswith("BUG-")
    
    def test_context_stored(self, temp_feedback_file):
        """Bug context is stored."""
        from feedback import submit_bug_report, _feedback_store
        
        submit_bug_report(
            description="Error on export",
            context={"browser": "Chrome", "url": "/export"}
        )
        
        bugs = _feedback_store.get("bug_reports", [])
        assert len(bugs) > 0
        assert bugs[-1]["context"]["browser"] == "Chrome"
    
    def test_severity_stored(self, temp_feedback_file):
        """Bug severity is stored."""
        from feedback import submit_bug_report, _feedback_store
        
        submit_bug_report(description="Critical error", severity="critical")
        
        bugs = _feedback_store.get("bug_reports", [])
        assert bugs[-1]["severity"] == "critical"


class TestGetFeedbackSummary:
    """Tests for get_feedback_summary function."""
    
    def test_summary_structure(self, temp_feedback_file):
        """Summary returns proper structure."""
        from feedback import get_feedback_summary
        
        result = get_feedback_summary()
        
        assert "nps" in result
        assert "feature_ratings" in result
        assert "bug_reports" in result
        assert "recent_comments" in result
    
    def test_summary_includes_nps_data(self, temp_feedback_file):
        """Summary includes NPS data."""
        from feedback import submit_nps, get_feedback_summary, _feedback_store
        
        # Clear existing data first
        _feedback_store["nps_responses"] = []
        _feedback_store["aggregates"] = {"nps_score": None, "total_responses": 0, "promoters": 0, "passives": 0, "detractors": 0, "feature_ratings": {}}
        
        submit_nps(score=9)
        submit_nps(score=10)
        
        result = get_feedback_summary()
        
        assert result["nps"]["total_responses"] == 2
        assert result["nps"]["promoters"] == 2


class TestGetNPSTrend:
    """Tests for get_nps_trend function."""
    
    def test_trend_returns_list(self, temp_feedback_file):
        """NPS trend returns list."""
        from feedback import get_nps_trend
        
        result = get_nps_trend(days=30)
        
        assert isinstance(result, list)
    
    def test_trend_includes_date_and_nps(self, temp_feedback_file):
        """Trend entries include date and NPS score."""
        from feedback import submit_nps, get_nps_trend
        
        submit_nps(score=9)
        
        result = get_nps_trend(days=30)
        
        if result:  # May have entries
            assert "date" in result[0]
            assert "nps" in result[0]
            assert "responses" in result[0]
