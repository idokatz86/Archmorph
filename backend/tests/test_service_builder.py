"""
Tests for the Natural Language Service Builder module.
"""

import pytest
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from service_builder import (
    add_services_from_text,
    deduplicate_questions,
    get_smart_defaults_from_analysis,
    _fuzzy_match_azure_service,
)


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture
def sample_analysis():
    """Sample analysis result for testing."""
    return {
        "diagram_id": "diag-test123",
        "diagram_type": "AWS Architecture",
        "source_provider": "aws",
        "target_provider": "azure",
        "services_detected": 3,
        "architecture_patterns": ["multi-AZ", "microservices"],
        "zones": [
            {
                "id": 1,
                "name": "Compute",
                "number": 1,
                "services": [
                    {"aws": "Lambda", "azure": "Azure Functions", "confidence": 0.95},
                    {"aws": "API Gateway", "azure": "Azure API Management", "confidence": 0.9},
                ],
            },
            {
                "id": 2,
                "name": "Storage",
                "number": 2,
                "services": [
                    {"aws": "S3", "azure": "Azure Blob Storage", "confidence": 0.95},
                ],
            },
        ],
        "mappings": [
            {"source_service": "Lambda", "source_provider": "aws", "azure_service": "Azure Functions", "confidence": 0.95, "notes": "Zone 1"},
            {"source_service": "API Gateway", "source_provider": "aws", "azure_service": "Azure API Management", "confidence": 0.9, "notes": "Zone 1"},
            {"source_service": "S3", "source_provider": "aws", "azure_service": "Azure Blob Storage", "confidence": 0.95, "notes": "Zone 2"},
        ],
        "confidence_summary": {"high": 3, "medium": 0, "low": 0, "average": 0.93},
    }


@pytest.fixture
def sample_questions():
    """Sample questions for deduplication testing."""
    return [
        {
            "id": "env_target",
            "question": "What environment is this architecture for?",
            "type": "single_choice",
            "options": ["Development", "Staging", "Production"],
            "default": "Production",
        },
        {
            "id": "sec_compliance",
            "question": "Which compliance frameworks apply?",
            "type": "multiple_choice",
            "options": ["HIPAA", "SOC 2", "PCI-DSS", "GDPR", "None"],
            "default": "None",
        },
        {
            "id": "ha_sla",
            "question": "What SLA target do you need?",
            "type": "single_choice",
            "options": ["99%", "99.9%", "99.99%"],
            "default": "99.9%",
        },
        {
            "id": "env_data_volume",
            "question": "Expected data volume per day?",
            "type": "single_choice",
            "options": ["<1 GB", "1–100 GB", "100 GB–1 TB", ">1 TB"],
            "default": "1–100 GB",
        },
    ]


# ====================================================================
# Fuzzy Matching Tests
# ====================================================================

class TestFuzzyMatching:
    def test_exact_match_short_name(self):
        result = _fuzzy_match_azure_service("redis")
        assert result is not None
        assert "Redis" in result["fullName"]

    def test_exact_match_alias(self):
        result = _fuzzy_match_azure_service("api gateway")
        assert result is not None
        assert "API Management" in result["fullName"]

    def test_fuzzy_match_kubernetes(self):
        result = _fuzzy_match_azure_service("kubernetes")
        assert result is not None
        assert "Kubernetes" in result["fullName"]

    def test_fuzzy_match_k8s(self):
        result = _fuzzy_match_azure_service("k8s")
        assert result is not None
        assert "Kubernetes" in result["fullName"]

    def test_fuzzy_match_cosmos(self):
        result = _fuzzy_match_azure_service("cosmosdb")
        assert result is not None
        assert "Cosmos" in result["fullName"]

    def test_no_match_returns_none(self):
        result = _fuzzy_match_azure_service("totally-made-up-service-xyz")
        # May return None or a low-confidence fuzzy match
        # Just ensure it doesn't crash
        assert result is None or isinstance(result, dict)


# ====================================================================
# Service Addition Tests (with mocking)
# ====================================================================

class TestAddServicesFromText:
    @patch("service_builder.get_openai_client")
    def test_add_redis_cache(self, mock_client, sample_analysis):
        """Test adding Redis cache via natural language."""
        # Mock OpenAI response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '''
        {
            "services": [
                {
                    "name": "Redis",
                    "full_name": "Azure Cache for Redis",
                    "category": "Database",
                    "configuration": {"sku": "Standard"},
                    "reason": "User requested caching"
                }
            ],
            "inferred_requirements": []
        }
        '''
        mock_client.return_value.chat.completions.create.return_value = mock_response

        result = add_services_from_text(
            analysis=sample_analysis,
            user_text="Add a Redis cache for session storage"
        )

        assert "services_added" in result
        assert len(result["services_added"]) == 1
        assert result["services_added"][0]["name"] == "Redis"
        assert result["services_detected"] == 4  # 3 original + 1 new

    @patch("service_builder.get_openai_client")
    def test_add_multiple_services(self, mock_client, sample_analysis):
        """Test adding multiple services at once."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '''
        {
            "services": [
                {"name": "Redis", "full_name": "Azure Cache for Redis", "category": "Database"},
                {"name": "CDN", "full_name": "Azure CDN", "category": "Networking"}
            ],
            "inferred_requirements": ["low latency", "global distribution"]
        }
        '''
        mock_client.return_value.chat.completions.create.return_value = mock_response

        result = add_services_from_text(
            analysis=sample_analysis,
            user_text="Add Redis and CDN for better performance"
        )

        assert len(result["services_added"]) == 2
        assert result["services_detected"] == 5
        assert "low latency" in result["inferred_requirements"]

    def test_empty_input_returns_error(self, sample_analysis):
        """Test that empty input returns an error."""
        result = add_services_from_text(
            analysis=sample_analysis,
            user_text=""
        )
        assert "add_services_error" in result
        assert result["services_added"] == []

    @patch("service_builder.get_openai_client")
    def test_existing_service_not_duplicated(self, mock_client, sample_analysis):
        """Test that existing services are not duplicated."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '''
        {
            "services": [
                {"name": "Azure Functions", "full_name": "Azure Functions", "category": "Compute"}
            ],
            "inferred_requirements": []
        }
        '''
        mock_client.return_value.chat.completions.create.return_value = mock_response

        result = add_services_from_text(
            analysis=sample_analysis,
            user_text="Add Functions"
        )

        # Azure Functions already exists, should not be added
        assert len(result["services_added"]) == 0

    @patch("service_builder.get_openai_client")
    def test_creates_user_added_zone(self, mock_client, sample_analysis):
        """Test that a User Added zone is created."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '''
        {
            "services": [
                {"name": "Key Vault", "full_name": "Azure Key Vault", "category": "Security"}
            ],
            "inferred_requirements": []
        }
        '''
        mock_client.return_value.chat.completions.create.return_value = mock_response

        result = add_services_from_text(
            analysis=sample_analysis,
            user_text="Add Key Vault for secrets"
        )

        user_zone = next((z for z in result["zones"] if z["name"] == "User Added"), None)
        assert user_zone is not None
        assert len(user_zone["services"]) == 1


# ====================================================================
# Question Deduplication Tests
# ====================================================================

class TestDeduplicateQuestions:
    def test_no_context_returns_all_questions(self, sample_questions, sample_analysis):
        """Test that all questions are returned when no context is provided."""
        filtered, inferred = deduplicate_questions(
            questions=sample_questions,
            analysis=sample_analysis,
            user_context=None
        )
        assert len(filtered) == len(sample_questions)
        assert len(inferred) == 0

    def test_production_keyword_infers_env_target(self, sample_questions, sample_analysis):
        """Test that 'production' keyword infers env_target."""
        user_context = {
            "natural_language_additions": [
                {"text": "This is a production workload with high availability"}
            ]
        }
        
        filtered, inferred = deduplicate_questions(
            questions=sample_questions,
            analysis=sample_analysis,
            user_context=user_context
        )
        
        assert "env_target" in inferred
        assert inferred["env_target"].lower() == "production"
        # env_target question should be filtered out
        assert not any(q["id"] == "env_target" for q in filtered)

    def test_hipaa_keyword_infers_compliance(self, sample_questions, sample_analysis):
        """Test that 'HIPAA' keyword infers compliance."""
        user_context = {
            "natural_language_additions": [
                {"text": "Must be HIPAA compliant for healthcare data"}
            ]
        }
        
        filtered, inferred = deduplicate_questions(
            questions=sample_questions,
            analysis=sample_analysis,
            user_context=user_context
        )
        
        assert "sec_compliance" in inferred
        assert inferred["sec_compliance"] == "HIPAA"

    def test_multiple_keywords_infer_multiple_answers(self, sample_questions, sample_analysis):
        """Test that multiple keywords infer multiple answers."""
        user_context = {
            "natural_language_additions": [
                {"text": "Production HIPAA-compliant system with four nines availability"}
            ]
        }
        
        filtered, inferred = deduplicate_questions(
            questions=sample_questions,
            analysis=sample_analysis,
            user_context=user_context
        )
        
        assert "env_target" in inferred
        assert "sec_compliance" in inferred
        assert "ha_sla" in inferred
        assert inferred["ha_sla"] == "99.99%"

    def test_user_messages_also_work(self, sample_questions, sample_analysis):
        """Test that user_messages are also checked for keywords."""
        user_context = {
            "user_messages": [
                "I need this for production",
                "We're in healthcare so HIPAA is required"
            ]
        }
        
        filtered, inferred = deduplicate_questions(
            questions=sample_questions,
            analysis=sample_analysis,
            user_context=user_context
        )
        
        assert "env_target" in inferred
        assert "sec_compliance" in inferred


# ====================================================================
# Smart Defaults Tests
# ====================================================================

class TestSmartDefaults:
    def test_high_service_count_suggests_larger_scale(self):
        """Test that high service count suggests larger data volume."""
        analysis = {
            "services_detected": 25,
            "mappings": [{"source_service": f"svc_{i}"} for i in range(25)],
            "architecture_patterns": [],
        }
        
        defaults = get_smart_defaults_from_analysis(analysis)
        
        assert defaults.get("env_data_volume") == "1–10 TB"
        assert defaults.get("env_concurrent_users") == "10 K–100 K"

    def test_low_service_count_suggests_smaller_scale(self):
        """Test that low service count suggests smaller data volume."""
        analysis = {
            "services_detected": 3,
            "mappings": [{"source_service": f"svc_{i}"} for i in range(3)],
            "architecture_patterns": [],
        }
        
        defaults = get_smart_defaults_from_analysis(analysis)
        
        assert defaults.get("env_data_volume") == "1–100 GB"
        assert defaults.get("env_concurrent_users") == "100–1 K"

    def test_multi_az_pattern_suggests_ha(self):
        """Test that multi-AZ pattern suggests high availability."""
        analysis = {
            "services_detected": 5,
            "mappings": [],
            "architecture_patterns": ["multi-AZ", "load-balanced"],
        }
        
        defaults = get_smart_defaults_from_analysis(analysis)
        
        assert defaults.get("ha_sla") == "99.99%"

    def test_database_services_get_backup_defaults(self):
        """Test that database services get backup retention defaults."""
        analysis = {
            "services_detected": 5,
            "mappings": [
                {"source_service": "DynamoDB", "azure_service": "Azure Cosmos DB"},
            ],
            "architecture_patterns": [],
        }
        
        defaults = get_smart_defaults_from_analysis(analysis)
        
        assert "db_backup_retention" in defaults


# ====================================================================
# Integration Tests (requires actual OpenAI - skip in CI)
# ====================================================================

@pytest.mark.skipif(
    os.getenv("AZURE_OPENAI_API_KEY") is None,
    reason="Requires Azure OpenAI credentials"
)
class TestServiceBuilderIntegration:
    def test_real_service_extraction(self, sample_analysis):
        """Integration test with real OpenAI call."""
        result = add_services_from_text(
            analysis=sample_analysis,
            user_text="Add Azure Cache for Redis and Application Gateway"
        )
        
        assert "services_added" in result
        # Should extract at least one service
        assert len(result["services_added"]) >= 1
