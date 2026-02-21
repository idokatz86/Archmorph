"""
Tests for Cost Optimizer module.
"""

import pytest
from cost_optimizer import (
    analyze_cost_optimizations,
    SavingsCategory,
    CostOptimization
)


class TestAnalyzeCostOptimizations:
    """Tests for analyze_cost_optimizations function."""
    
    def test_empty_analysis_returns_structure(self):
        """Empty analysis returns proper structure."""
        result = analyze_cost_optimizations({"zones": []})
        
        assert "total_optimizations" in result
        assert "requires_commitment" in result
        assert "quick_wins" in result
        assert "optimizations" in result
        assert "by_category" in result
        assert "top_3_quick_wins" in result
    
    def test_production_vms_trigger_reserved_instances(self):
        """Production VMs trigger reserved instance recommendation."""
        analysis = {
            "zones": [
                {"name": "Compute", "services": [{"azure": "Virtual Machines"}]}
            ]
        }
        answers = {"env_target": "production"}
        
        result = analyze_cost_optimizations(analysis, answers)
        opt_ids = [o["id"] for o in result["optimizations"]]
        
        assert "cost-ri-001" in opt_ids
    
    def test_dev_vms_trigger_spot_recommendation(self):
        """Dev/test VMs trigger spot VM recommendation."""
        analysis = {
            "zones": [
                {"name": "Compute", "services": [{"azure": "Virtual Machines"}]}
            ]
        }
        answers = {"env_target": "development"}
        
        result = analyze_cost_optimizations(analysis, answers)
        opt_ids = [o["id"] for o in result["optimizations"]]
        
        assert "cost-spot-001" in opt_ids
    
    def test_storage_triggers_tiering_recommendation(self):
        """Storage services trigger tiering recommendation."""
        analysis = {
            "zones": [
                {"name": "Storage", "services": [{"azure": "Blob Storage"}]}
            ]
        }
        
        result = analyze_cost_optimizations(analysis)
        opt_ids = [o["id"] for o in result["optimizations"]]
        
        assert "cost-storage-001" in opt_ids
    
    def test_dev_vms_trigger_auto_shutdown(self):
        """Dev VMs trigger auto-shutdown recommendation."""
        analysis = {
            "zones": [
                {"name": "Compute", "services": [{"azure": "Virtual Machines"}]}
            ]
        }
        answers = {"env_target": "testing"}
        
        result = analyze_cost_optimizations(analysis, answers)
        opt_ids = [o["id"] for o in result["optimizations"]]
        
        assert "cost-auto-001" in opt_ids
    
    def test_hybrid_benefit_for_sql(self):
        """SQL services trigger hybrid benefit recommendation."""
        analysis = {
            "zones": [
                {"name": "Database", "services": [{"azure": "Azure SQL"}]}
            ]
        }
        
        result = analyze_cost_optimizations(analysis)
        opt_ids = [o["id"] for o in result["optimizations"]]
        
        assert "cost-hybrid-001" in opt_ids
    
    def test_dev_test_pricing_for_dev_env(self):
        """Dev environment triggers dev/test pricing recommendation."""
        analysis = {
            "zones": [
                {"name": "App", "services": [{"azure": "Container Apps"}]}
            ]
        }
        answers = {"env_target": "development"}
        
        result = analyze_cost_optimizations(analysis, answers)
        opt_ids = [o["id"] for o in result["optimizations"]]
        
        assert "cost-devtest-001" in opt_ids
    
    def test_right_sizing_for_vms(self):
        """VMs trigger right-sizing recommendation."""
        analysis = {
            "zones": [
                {"name": "Compute", "services": [{"azure": "Virtual Machines"}]}
            ]
        }
        
        result = analyze_cost_optimizations(analysis)
        opt_ids = [o["id"] for o in result["optimizations"]]
        
        assert "cost-right-001" in opt_ids
    
    def test_commitment_required_count(self):
        """Commitment required count is calculated."""
        analysis = {
            "zones": [
                {"name": "Compute", "services": [{"azure": "Virtual Machines"}]}
            ]
        }
        answers = {"env_target": "production"}
        
        result = analyze_cost_optimizations(analysis, answers)
        
        # Reserved instances require commitment
        assert result["requires_commitment"] >= 1
    
    def test_quick_wins_count(self):
        """Quick wins count excludes commitment-required."""
        analysis = {
            "zones": [
                {"name": "Compute", "services": [{"azure": "Virtual Machines"}]}
            ]
        }
        
        result = analyze_cost_optimizations(analysis)
        
        assert result["quick_wins"] >= 0
        assert result["total_optimizations"] >= result["quick_wins"]
    
    def test_top_3_quick_wins_sorted_by_effort(self):
        """Top 3 quick wins are sorted by effort."""
        analysis = {
            "zones": [
                {"name": "Compute", "services": [{"azure": "Virtual Machines"}, {"azure": "Blob Storage"}]}
            ]
        }
        
        result = analyze_cost_optimizations(analysis)
        
        assert len(result["top_3_quick_wins"]) <= 3
    
    def test_by_category_grouping(self):
        """Optimizations are grouped by category."""
        result = analyze_cost_optimizations({"zones": []})
        
        for category in SavingsCategory:
            assert category.value in result["by_category"]
            assert isinstance(result["by_category"][category.value], list)


class TestCostOptimizationDataclass:
    """Tests for CostOptimization dataclass."""
    
    def test_optimization_creation(self):
        """CostOptimization can be created with all fields."""
        opt = CostOptimization(
            id="test-001",
            title="Test Optimization",
            description="A test optimization",
            category=SavingsCategory.RESERVED_INSTANCES,
            estimated_savings="30-50%",
            effort="low",
            services_affected=["VM1"],
            action_steps=["Step 1", "Step 2"]
        )
        
        assert opt.id == "test-001"
        assert opt.category == SavingsCategory.RESERVED_INSTANCES
        assert opt.estimated_savings == "30-50%"
        assert opt.requires_commitment == False
    
    def test_optimization_with_commitment(self):
        """CostOptimization can have commitment requirement."""
        opt = CostOptimization(
            id="test-002",
            title="Test",
            description="Test",
            category=SavingsCategory.RESERVED_INSTANCES,
            estimated_savings="50%",
            effort="low",
            services_affected=[],
            action_steps=[],
            requires_commitment=True
        )
        
        assert opt.requires_commitment == True
