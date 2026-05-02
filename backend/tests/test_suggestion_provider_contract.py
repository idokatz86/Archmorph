import pytest
from pydantic import ValidationError

from routers.suggestions import GenerateBatchRequest, GenerateRequest, SuggestBatchRequest, SuggestMappingRequest


class TestSuggestionProviderContract:
    @pytest.mark.parametrize(
        "model_cls,payload",
        [
            (SuggestMappingRequest, {"source_service": "EC2", "source_provider": "AWS"}),
            (GenerateRequest, {"source_service": "Compute Engine", "source_provider": " gCp "}),
            (SuggestBatchRequest, {"services": [{"name": "EC2"}], "source_provider": None}),
            (GenerateBatchRequest, {"services": [{"name": "Cloud SQL"}]}),
        ],
    )
    def test_request_models_normalize_supported_values_and_defaults(self, model_cls, payload):
        model = model_cls(**payload)
        assert model.source_provider in {"aws", "gcp"}

    @pytest.mark.parametrize(
        "model_cls,payload",
        [
            (SuggestMappingRequest, {"source_service": "VM", "source_provider": "azure"}),
            (GenerateRequest, {"source_service": "EC2", "source_provider": ""}),
            (SuggestBatchRequest, {"services": [{"name": "EC2"}], "source_provider": "amazon"}),
            (GenerateBatchRequest, {"services": [{"name": "Cloud SQL"}], "source_provider": 123}),
        ],
    )
    def test_request_models_reject_unsupported_values(self, model_cls, payload):
        with pytest.raises(ValidationError):
            model_cls(**payload)