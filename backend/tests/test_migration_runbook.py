"""
Tests for Migration Runbook Generator
"""

import pytest
from migration_runbook import (
    MigrationTask, MigrationRunbook, MigrationPhase, TaskPriority, TaskStatus,
    generate_migration_runbook, render_runbook_markdown,
    _detect_service_categories, _calculate_risk_level,
)


class TestMigrationTask:
    """Tests for MigrationTask class."""
    
    def test_task_creation(self):
        task = MigrationTask(
            id="task-1",
            title="Test Task",
            description="Test description",
            phase=MigrationPhase.ASSESSMENT,
            priority=TaskPriority.HIGH,
            estimated_hours=4,
        )
        assert task.id == "task-1"
        assert task.phase == MigrationPhase.ASSESSMENT
        assert task.status == TaskStatus.NOT_STARTED
    
    def test_task_to_dict(self):
        task = MigrationTask(
            id="task-1",
            title="Test Task",
            description="Test",
            phase=MigrationPhase.MIGRATION,
            priority=TaskPriority.CRITICAL,
            estimated_hours=8,
        )
        data = task.to_dict()
        assert data["id"] == "task-1"
        assert data["phase"] == "migration"
        assert data["priority"] == "critical"


class TestMigrationRunbook:
    """Tests for MigrationRunbook class."""
    
    def test_runbook_creation(self):
        runbook = MigrationRunbook(
            id="rb-123",
            diagram_id="diag-123",
            title="AWS Migration",
            source_cloud="AWS",
        )
        assert runbook.target_cloud == "Azure"
        assert len(runbook.tasks) == 0
    
    def test_runbook_summary(self):
        runbook = MigrationRunbook(
            id="rb-123",
            diagram_id="diag-123",
            title="Test",
            source_cloud="AWS",
        )
        runbook.tasks.append(MigrationTask(
            id="task-1",
            title="Task 1",
            description="Test",
            phase=MigrationPhase.ASSESSMENT,
            priority=TaskPriority.HIGH,
            estimated_hours=4,
        ))
        runbook.tasks.append(MigrationTask(
            id="task-2",
            title="Task 2",
            description="Test",
            phase=MigrationPhase.MIGRATION,
            priority=TaskPriority.CRITICAL,
            estimated_hours=8,
        ))
        
        summary = runbook.get_summary()
        assert summary["total_tasks"] == 2
        assert summary["total_estimated_hours"] == 12


class TestServiceCategoryDetection:
    """Tests for service category detection."""
    
    def test_detect_compute(self):
        mappings = [{"source_service": "EC2", "azure_service": "Virtual Machines"}]
        categories = _detect_service_categories(mappings)
        assert categories["compute"] is True
    
    def test_detect_database(self):
        mappings = [{"source_service": "RDS", "azure_service": "Azure SQL"}]
        categories = _detect_service_categories(mappings)
        assert categories["database"] is True
    
    def test_detect_multiple_categories(self):
        mappings = [
            {"source_service": "EC2", "azure_service": "VM"},
            {"source_service": "S3", "azure_service": "Blob Storage"},
            {"source_service": "RDS", "azure_service": "PostgreSQL"},
        ]
        categories = _detect_service_categories(mappings)
        assert categories["compute"] is True
        assert categories["storage"] is True
        assert categories["database"] is True


class TestRiskCalculation:
    """Tests for risk level calculation."""
    
    def test_low_risk(self):
        mappings = [
            {"source_service": "S3", "azure_service": "Blob", "confidence": 0.95},
        ]
        categories = {"storage": True, "compute": False, "database": False, "networking": False, "ai_ml": False, "containers": False}
        risk = _calculate_risk_level(mappings, categories)
        assert risk == "low"
    
    def test_high_risk_with_database(self):
        mappings = [
            {"source_service": "RDS", "azure_service": "Azure SQL", "confidence": 0.8},
            {"source_service": "EC2", "azure_service": "VM", "confidence": 0.9},
        ]
        categories = {"database": True, "compute": True, "storage": False, "networking": False, "ai_ml": False, "containers": False}
        risk = _calculate_risk_level(mappings, categories)
        assert risk in ["medium", "high"]
    
    def test_critical_risk_complex(self):
        mappings = [
            {"source_service": "EKS", "azure_service": "AKS", "confidence": 0.5},
            {"source_service": "RDS", "azure_service": "Azure SQL", "confidence": 0.4},
            {"source_service": "SageMaker", "azure_service": "Azure ML", "confidence": 0.5},
            {"source_service": "Lambda", "azure_service": "Functions", "confidence": 0.5},
        ]
        categories = {"database": True, "containers": True, "ai_ml": True, "serverless": True, "networking": False, "storage": False, "compute": False}
        risk = _calculate_risk_level(mappings, categories)
        assert risk in ["high", "critical"]


class TestRunbookGeneration:
    """Tests for runbook generation."""
    
    def test_generate_basic_runbook(self):
        analysis = {
            "mappings": [
                {"source_service": "EC2", "azure_service": "VM", "confidence": 0.9},
                {"source_service": "S3", "azure_service": "Blob Storage", "confidence": 0.95},
            ],
            "source_cloud": "AWS",
        }
        
        runbook = generate_migration_runbook("diag-123", analysis)
        
        assert runbook.diagram_id == "diag-123"
        assert runbook.source_cloud == "AWS"
        assert len(runbook.tasks) > 0
        assert runbook.estimated_duration_days > 0
    
    def test_generate_runbook_with_database(self):
        analysis = {
            "mappings": [
                {"source_service": "RDS PostgreSQL", "azure_service": "Azure Database for PostgreSQL"},
            ],
            "source_cloud": "AWS",
        }
        
        runbook = generate_migration_runbook("diag-456", analysis)
        
        # Should include database migration tasks
        task_titles = [t.title for t in runbook.tasks]
        assert any("database" in t.lower() for t in task_titles)
    
    def test_generate_runbook_with_project_name(self):
        analysis = {
            "mappings": [],
            "source_cloud": "GCP",
        }
        
        runbook = generate_migration_runbook("diag-789", analysis, project_name="Project Phoenix")
        assert runbook.title == "Project Phoenix"


class TestMarkdownRendering:
    """Tests for Markdown rendering."""
    
    def test_render_basic_markdown(self):
        runbook = MigrationRunbook(
            id="rb-123",
            diagram_id="diag-123",
            title="Test Migration",
            source_cloud="AWS",
            risk_level="medium",
            estimated_duration_days=10,
        )
        runbook.tasks.append(MigrationTask(
            id="task-1",
            title="Assessment Task",
            description="Assess the architecture",
            phase=MigrationPhase.ASSESSMENT,
            priority=TaskPriority.HIGH,
            estimated_hours=4,
            validation_steps=["Check A", "Check B"],
        ))
        
        markdown = render_runbook_markdown(runbook)
        
        assert "# Test Migration" in markdown
        assert "AWS" in markdown
        assert "Azure" in markdown
        assert "Assessment Task" in markdown
        assert "Check A" in markdown
    
    def test_render_includes_commands(self):
        runbook = MigrationRunbook(
            id="rb-123",
            diagram_id="diag-123",
            title="Test",
            source_cloud="AWS",
        )
        runbook.tasks.append(MigrationTask(
            id="task-1",
            title="Create Resources",
            description="Test",
            phase=MigrationPhase.PREPARATION,
            priority=TaskPriority.HIGH,
            estimated_hours=2,
            commands=["az group create --name rg"],
        ))
        
        markdown = render_runbook_markdown(runbook)
        assert "az group create" in markdown
        assert "```bash" in markdown
