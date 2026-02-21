"""
Tests for Best Practices Linter module.
"""

from best_practices import (
    analyze_architecture,
    get_quick_wins,
    WAFPillar,
    Severity,
    Recommendation
)


class TestAnalyzeArchitecture:
    """Tests for analyze_architecture function."""
    
    def test_empty_analysis_returns_structure(self):
        """Empty analysis returns proper structure."""
        result = analyze_architecture({"zones": []})
        
        assert "overall_score" in result
        assert "pillar_scores" in result
        assert "recommendations" in result
        assert "by_pillar" in result
        assert isinstance(result["recommendations"], list)
    
    def test_compute_zone_triggers_az_recommendation(self):
        """Compute zone without AZ should trigger availability zone recommendation."""
        analysis = {
            "zones": [
                {"name": "Compute", "services": [{"azure": "Virtual Machines"}]}
            ]
        }
        
        result = analyze_architecture(analysis, {})
        rec_ids = [r["id"] for r in result["recommendations"]]
        
        assert "rel-001" in rec_ids  # Availability Zones
    
    def test_database_zone_triggers_backup_recommendation(self):
        """Database zone should trigger backup recommendation."""
        analysis = {
            "zones": [
                {"name": "Database", "services": [{"azure": "Azure SQL"}]}
            ]
        }
        
        result = analyze_architecture(analysis, {})
        rec_ids = [r["id"] for r in result["recommendations"]]
        
        assert "rel-002" in rec_ids  # Geo-redundant backups
    
    def test_no_keyvault_triggers_security_recommendation(self):
        """Missing Key Vault should trigger security recommendation."""
        analysis = {
            "zones": [
                {"name": "Application", "services": [{"azure": "Container Apps"}]}
            ]
        }
        
        result = analyze_architecture(analysis, {})
        rec_ids = [r["id"] for r in result["recommendations"]]
        
        assert "sec-001" in rec_ids  # Add Key Vault
    
    def test_api_without_waf_triggers_recommendation(self):
        """API Gateway without WAF triggers recommendation."""
        analysis = {
            "zones": [
                {"name": "API", "services": [{"azure": "API Management"}]}
            ]
        }
        
        result = analyze_architecture(analysis, {})
        rec_ids = [r["id"] for r in result["recommendations"]]
        
        assert "sec-002" in rec_ids  # Add WAF
    
    def test_container_triggers_autoscaling_recommendation(self):
        """Container workloads trigger auto-scaling recommendation."""
        analysis = {
            "zones": [
                {"name": "Compute", "services": [{"azure": "Azure Kubernetes Service"}]}
            ]
        }
        
        result = analyze_architecture(analysis, {})
        rec_ids = [r["id"] for r in result["recommendations"]]
        
        assert "ops-003" in rec_ids  # Auto-scaling
    
    def test_complex_architecture_triggers_app_insights(self):
        """Complex architecture (>10 services) triggers App Insights recommendation."""
        services = [{"azure": f"Service{i}"} for i in range(15)]
        analysis = {
            "zones": [
                {"name": "Application", "services": services}
            ]
        }
        
        result = analyze_architecture(analysis, {})
        rec_ids = [r["id"] for r in result["recommendations"]]
        
        assert "perf-003" in rec_ids  # Application Insights
    
    def test_pillar_scores_calculated(self):
        """WAF pillar scores are calculated correctly."""
        analysis = {
            "zones": [
                {"name": "Compute", "services": [{"azure": "Virtual Machines"}]}
            ]
        }
        
        result = analyze_architecture(analysis)
        
        for pillar in WAFPillar:
            assert pillar.value in result["pillar_scores"]
            assert 0 <= result["pillar_scores"][pillar.value] <= 100
    
    def test_overall_score_is_average(self):
        """Overall score is average of pillar scores."""
        analysis = {
            "zones": [
                {"name": "Compute", "services": [{"azure": "VM"}]}
            ]
        }
        
        result = analyze_architecture(analysis)
        expected_avg = sum(result["pillar_scores"].values()) / len(result["pillar_scores"])
        
        assert abs(result["overall_score"] - expected_avg) < 0.1
    
    def test_waf_alignment_levels(self):
        """WAF alignment level is set correctly."""
        # Minimal architecture should have good alignment
        analysis = {"zones": []}
        result = analyze_architecture(analysis)
        
        assert result["waf_alignment"] in ["good", "needs_improvement", "critical"]


class TestGetQuickWins:
    """Tests for get_quick_wins function."""
    
    def test_returns_max_3_recommendations(self):
        """Quick wins returns at most 3 recommendations."""
        recommendations = [
            {"id": f"rec-{i}", "severity": "high", "title": f"Rec {i}"}
            for i in range(10)
        ]
        
        result = get_quick_wins(recommendations)
        
        assert len(result) <= 3
    
    def test_prioritizes_high_severity(self):
        """Quick wins prioritizes high severity."""
        recommendations = [
            {"id": "low", "severity": "low", "title": "Low"},
            {"id": "high", "severity": "high", "title": "High"},
            {"id": "medium", "severity": "medium", "title": "Medium"},
        ]
        
        result = get_quick_wins(recommendations)
        
        assert result[0]["id"] == "high"
    
    def test_excludes_info_severity(self):
        """Quick wins excludes info severity."""
        recommendations = [
            {"id": "info", "severity": "info", "title": "Info"},
            {"id": "medium", "severity": "medium", "title": "Medium"},
        ]
        
        result = get_quick_wins(recommendations)
        ids = [r["id"] for r in result]
        
        assert "info" not in ids
    
    def test_empty_recommendations_returns_empty(self):
        """Empty recommendations returns empty list."""
        result = get_quick_wins([])
        assert result == []


class TestRecommendationDataclass:
    """Tests for Recommendation dataclass."""
    
    def test_recommendation_creation(self):
        """Recommendation can be created with all fields."""
        rec = Recommendation(
            id="test-001",
            title="Test Recommendation",
            description="A test recommendation",
            pillar=WAFPillar.SECURITY,
            severity=Severity.HIGH,
            category="Test",
            action="Do something"
        )
        
        assert rec.id == "test-001"
        assert rec.pillar == WAFPillar.SECURITY
        assert rec.severity == Severity.HIGH
        assert rec.services_affected == []
    
    def test_recommendation_with_services(self):
        """Recommendation can include affected services."""
        rec = Recommendation(
            id="test-002",
            title="Test",
            description="Test",
            pillar=WAFPillar.COST,
            severity=Severity.MEDIUM,
            category="Test",
            action="Test",
            services_affected=["VM1", "VM2"]
        )
        
        assert rec.services_affected == ["VM1", "VM2"]
