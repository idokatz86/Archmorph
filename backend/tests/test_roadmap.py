"""
Tests for Archmorph Roadmap module.

Tests roadmap retrieval, feature request submission, and bug reporting.
"""

from datetime import datetime
from unittest.mock import patch, MagicMock

from roadmap import (
    get_roadmap,
    get_release_by_version,
    submit_feature_request,
    submit_bug_report,
    create_github_issue,
    RELEASE_TIMELINE,
    ReleaseStatus,
    IssueType,
)


class TestGetRoadmap:
    """Tests for roadmap retrieval."""

    def test_get_roadmap_returns_timeline(self):
        """Roadmap should return timeline grouped by status."""
        result = get_roadmap()
        assert "timeline" in result
        assert "released" in result["timeline"]
        assert "in_progress" in result["timeline"]
        assert "planned" in result["timeline"]
        assert "ideas" in result["timeline"]

    def test_get_roadmap_returns_stats(self):
        """Roadmap should include statistics."""
        result = get_roadmap()
        assert "stats" in result
        stats = result["stats"]
        assert "total_releases" in stats
        assert "features_shipped" in stats
        assert "days_since_launch" in stats
        assert "current_version" in stats

    def test_get_roadmap_has_released_versions(self):
        """Roadmap should have released versions."""
        result = get_roadmap()
        released = result["timeline"]["released"]
        assert len(released) > 0
        # Check first release is 1.0.0
        versions = [r["version"] for r in released]
        assert "1.0.0" in versions

    def test_get_roadmap_has_planned_features(self):
        """Roadmap should have planned features."""
        result = get_roadmap()
        planned = result["timeline"]["planned"]
        assert len(planned) > 0
        # All planned should have status = planned
        for release in planned:
            assert release["status"] == ReleaseStatus.PLANNED

    def test_get_roadmap_includes_generated_at(self):
        """Roadmap should include generation timestamp."""
        result = get_roadmap()
        assert "generated_at" in result
        # Should be valid ISO timestamp
        datetime.fromisoformat(result["generated_at"].replace("Z", "+00:00"))

    def test_stats_services_supported(self):
        """Stats should show 405 services supported."""
        result = get_roadmap()
        assert result["stats"]["services_supported"] == 405

    def test_stats_cloud_mappings(self):
        """Stats should show 122 cloud mappings."""
        result = get_roadmap()
        assert result["stats"]["cloud_mappings"] == 122

    def test_stats_progress_pct(self):
        """Stats should include progress_pct between 0 and 100."""
        result = get_roadmap()
        pct = result["stats"]["progress_pct"]
        assert isinstance(pct, float)
        assert 0.0 <= pct <= 100.0

    def test_stats_releases_remaining(self):
        """Stats should include non-negative releases_remaining."""
        result = get_roadmap()
        remaining = result["stats"]["releases_remaining"]
        assert isinstance(remaining, int)
        assert remaining >= 0

    def test_stats_velocity(self):
        """Stats should include positive velocity (releases per week)."""
        result = get_roadmap()
        velocity = result["stats"]["velocity"]
        assert isinstance(velocity, float)
        assert velocity > 0.0

    def test_productivity_progress_pct_reflects_releases(self):
        """progress_pct should equal (released + in_progress) / total_versioned * 100."""
        result = get_roadmap()
        timeline = result["timeline"]
        released = len(timeline["released"])
        in_progress = len(timeline["in_progress"])
        planned = len(timeline["planned"])
        total = released + in_progress + planned
        expected = round((released + in_progress) / max(total, 1) * 100, 1)
        assert result["stats"]["progress_pct"] == expected

    def test_productivity_releases_remaining_is_planned_plus_in_progress(self):
        """releases_remaining should equal planned + in_progress count."""
        result = get_roadmap()
        timeline = result["timeline"]
        expected = len(timeline["planned"]) + len(timeline["in_progress"])
        assert result["stats"]["releases_remaining"] == expected


class TestGetReleaseByVersion:
    """Tests for fetching specific release."""

    def test_get_existing_release(self):
        """Should return release details for existing version."""
        release = get_release_by_version("1.0.0")
        assert release is not None
        assert release["version"] == "1.0.0"
        assert release["name"] == "Initial Release"
        assert "highlights" in release

    def test_get_nonexistent_release(self):
        """Should return None for non-existent version."""
        release = get_release_by_version("99.99.99")
        assert release is None

    def test_get_release_2_9_0(self):
        """Should return v2.9.0 Enterprise Security release."""
        release = get_release_by_version("2.9.0")
        assert release is not None
        assert "Enterprise Security" in release["name"]
        assert release["status"] == ReleaseStatus.RELEASED

    def test_release_has_highlights(self):
        """Each release should have highlights list."""
        release = get_release_by_version("2.0.0")
        assert release is not None
        assert "highlights" in release
        assert len(release["highlights"]) > 0


class TestReleaseTimeline:
    """Tests for the release timeline data structure."""

    def test_timeline_has_required_fields(self):
        """Each release should have required fields."""
        required = {"version", "name", "status", "highlights"}
        for release in RELEASE_TIMELINE:
            for field in required:
                assert field in release, f"Release {release.get('version')} missing {field}"

    def test_timeline_versions_unique(self):
        """Version numbers should be unique (except 'Future')."""
        versions = [r["version"] for r in RELEASE_TIMELINE if r["version"] != "Future"]
        assert len(versions) == len(set(versions))

    def test_released_have_dates(self):
        """Released versions should have dates."""
        for release in RELEASE_TIMELINE:
            if release["status"] == ReleaseStatus.RELEASED:
                assert release.get("date"), f"Release {release['version']} missing date"

    def test_ideas_no_dates(self):
        """Ideas should not have dates."""
        for release in RELEASE_TIMELINE:
            if release["status"] == ReleaseStatus.IDEA:
                assert release.get("date") is None


class TestCreateGitHubIssue:
    """Tests for GitHub issue creation."""

    @patch("roadmap.GITHUB_TOKEN", "")
    def test_no_token_returns_error(self):
        """Should return error when GitHub token not configured."""
        result = create_github_issue(
            issue_type=IssueType.BUG,
            title="Test Bug",
            details={"description": "Test description"},
        )
        assert result["success"] is False
        assert "not configured" in result["error"].lower()

    @patch("roadmap.GITHUB_TOKEN", "fake-token")
    def test_creates_issue_successfully(self):
        """Should create GitHub issue with correct parameters."""
        with patch("github.Github") as mock_github_cls:
            # Setup mock
            mock_repo = MagicMock()
            mock_issue = MagicMock()
            mock_issue.number = 42
            mock_issue.html_url = "https://github.com/test/repo/issues/42"
            mock_issue.title = "[Bug] Test Bug"
            mock_repo.create_issue.return_value = mock_issue
            mock_repo.get_labels.return_value = [
                MagicMock(name="bug"),
                MagicMock(name="triage"),
            ]
            mock_github_cls.return_value.get_repo.return_value = mock_repo

            result = create_github_issue(
                issue_type=IssueType.BUG,
                title="Test Bug",
                details={"description": "This is a test bug"},
            )

            assert result["success"] is True
            assert result["issue_number"] == 42
            assert "github.com" in result["issue_url"]

    @patch("roadmap.GITHUB_TOKEN", "fake-token")
    def test_handles_github_error(self):
        """Should handle GitHub API errors gracefully."""
        with patch("github.Github") as mock_github_cls:
            mock_github_cls.return_value.get_repo.side_effect = Exception("API Error")

            result = create_github_issue(
                issue_type=IssueType.FEATURE,
                title="Test Feature",
                details={"description": "Test description"},
            )

            assert result["success"] is False
            assert "API Error" in result["error"]


class TestSubmitFeatureRequest:
    """Tests for feature request submission."""

    @patch("roadmap.create_github_issue")
    def test_calls_create_issue_with_feature_type(self, mock_create):
        """Should call create_github_issue with feature type."""
        mock_create.return_value = {"success": True, "issue_number": 1}

        submit_feature_request(
            title="Add dark mode",
            description="Please add dark mode support",
            use_case="Working at night",
        )

        mock_create.assert_called_once()
        call_args = mock_create.call_args
        assert call_args[1]["issue_type"] == IssueType.FEATURE
        assert "[Feature Request]" in call_args[1]["title"]

    @patch("roadmap.create_github_issue")
    def test_passes_email_when_provided(self, mock_create):
        """Should pass user email when provided."""
        mock_create.return_value = {"success": True, "issue_number": 1}

        submit_feature_request(
            title="New feature",
            description="Feature description here",
            user_email="test@example.com",
        )

        call_args = mock_create.call_args
        assert call_args[1]["user_email"] == "test@example.com"


class TestSubmitBugReport:
    """Tests for bug report submission."""

    @patch("roadmap.create_github_issue")
    def test_calls_create_issue_with_bug_type(self, mock_create):
        """Should call create_github_issue with bug type."""
        mock_create.return_value = {"success": True, "issue_number": 1}

        submit_bug_report(
            title="Button not working",
            description="Click button does nothing",
            steps="1. Click button\n2. Nothing happens",
        )

        mock_create.assert_called_once()
        call_args = mock_create.call_args
        assert call_args[1]["issue_type"] == IssueType.BUG
        assert "[Bug]" in call_args[1]["title"]

    @patch("roadmap.create_github_issue")
    def test_includes_all_details(self, mock_create):
        """Should include all bug details in the request."""
        mock_create.return_value = {"success": True, "issue_number": 1}

        submit_bug_report(
            title="Crash on upload",
            description="App crashes when uploading large files",
            steps="1. Upload 50MB file",
            expected="File uploads",
            actual="App crashes",
            browser="Chrome 120",
            os_info="macOS 14",
        )

        call_args = mock_create.call_args
        details = call_args[1]["details"]
        assert details["steps"] == "1. Upload 50MB file"
        assert details["expected"] == "File uploads"
        assert details["actual"] == "App crashes"
        assert details["browser"] == "Chrome 120"
        assert details["os"] == "macOS 14"


class TestIssueTemplates:
    """Tests for issue template formatting."""

    @patch("roadmap.GITHUB_TOKEN", "fake-token")
    def test_bug_template_has_required_sections(self):
        """Bug template should have all required sections."""
        with patch("github.Github") as mock_github_cls:
            mock_repo = MagicMock()
            mock_issue = MagicMock()
            mock_issue.number = 1
            mock_issue.html_url = "https://github.com/test"
            mock_issue.title = "Test"
            mock_repo.create_issue.return_value = mock_issue
            mock_repo.get_labels.return_value = []
            mock_github_cls.return_value.get_repo.return_value = mock_repo

            create_github_issue(
                issue_type=IssueType.BUG,
                title="Test",
                details={
                    "description": "Test desc",
                    "steps": "1. Do thing",
                    "expected": "Work",
                    "actual": "Broken",
                },
            )

            call_args = mock_repo.create_issue.call_args
            body = call_args[1]["body"]
            assert "Bug Report" in body
            assert "Description" in body
            assert "Steps to Reproduce" in body
            assert "Expected Behavior" in body
            assert "Actual Behavior" in body

    @patch("roadmap.GITHUB_TOKEN", "fake-token")
    def test_feature_template_has_required_sections(self):
        """Feature template should have all required sections."""
        with patch("github.Github") as mock_github_cls:
            mock_repo = MagicMock()
            mock_issue = MagicMock()
            mock_issue.number = 1
            mock_issue.html_url = "https://github.com/test"
            mock_issue.title = "Test"
            mock_repo.create_issue.return_value = mock_issue
            mock_repo.get_labels.return_value = []
            mock_github_cls.return_value.get_repo.return_value = mock_repo

            create_github_issue(
                issue_type=IssueType.FEATURE,
                title="Test",
                details={
                    "description": "New feature",
                    "use_case": "User needs this",
                },
            )

            call_args = mock_repo.create_issue.call_args
            body = call_args[1]["body"]
            assert "Feature Request" in body
            assert "Description" in body
            assert "Use Case" in body
