"""Tests for analysis_history.py — user analysis history and bookmarks."""

from analysis_history import (
    save_analysis,
    list_analyses,
    get_analysis,
    delete_analysis,
    toggle_bookmark,
    MAX_HISTORY_PER_USER,
)


class TestSaveAnalysis:
    def test_save_returns_analysis_record(self):
        result = save_analysis(
            user_id="user-1",
            diagram_id="diag-1",
            source_cloud="aws",
            target_cloud="azure",
            service_count=5,
            confidence_avg=0.92,
            title="Test Migration",
        )
        assert result["user_id"] == "user-1"
        assert result["diagram_id"] == "diag-1"
        assert "id" in result or "analysis_id" in result

    def test_save_with_defaults(self):
        result = save_analysis(user_id="user-2", diagram_id="diag-2")
        assert result["source_cloud"] == "aws"
        assert result["target_cloud"] == "azure"


class TestListAnalyses:
    def test_list_user_analyses(self):
        save_analysis(user_id="user-list", diagram_id="diag-a")
        save_analysis(user_id="user-list", diagram_id="diag-b")
        result = list_analyses("user-list")
        assert result["total"] >= 2

    def test_list_empty_user(self):
        result = list_analyses("nonexistent-user-xyz")
        assert result["total"] == 0

    def test_list_with_pagination(self):
        for i in range(5):
            save_analysis(user_id="user-page", diagram_id=f"diag-{i}")
        result = list_analyses("user-page", limit=2, offset=0)
        assert len(result["items"]) <= 2


class TestGetAnalysis:
    def test_get_existing(self):
        saved = save_analysis(user_id="user-get", diagram_id="diag-get")
        aid = saved.get("id") or saved.get("analysis_id")
        result = get_analysis("user-get", aid)
        assert result is not None

    def test_get_nonexistent(self):
        result = get_analysis("user-get", "nonexistent-id-xyz")
        assert result is None


class TestDeleteAnalysis:
    def test_delete_existing(self):
        saved = save_analysis(user_id="user-del", diagram_id="diag-del")
        aid = saved.get("id") or saved.get("analysis_id")
        assert delete_analysis("user-del", aid) is True

    def test_delete_nonexistent(self):
        assert delete_analysis("user-del", "nonexistent-xyz") is False


class TestToggleBookmark:
    def test_toggle_bookmark(self):
        saved = save_analysis(user_id="user-bm", diagram_id="diag-bm")
        aid = saved.get("id") or saved.get("analysis_id")
        result = toggle_bookmark("user-bm", aid)
        assert result is True or result is False

    def test_toggle_nonexistent(self):
        result = toggle_bookmark("user-bm", "nonexistent-xyz")
        assert result is None
