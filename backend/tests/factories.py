"""
Pydantic model factories for Archmorph tests (Issue #375).

Uses polyfactory to auto-generate valid model instances,
replacing inline dict literals in test code.
"""

from polyfactory.factories.pydantic_factory import ModelFactory

from cost_metering import (
    BudgetCreateRequest,
    BudgetRule,
    BudgetUpdateRequest,
    CostAlert,
    CostOverviewResponse,
    CostRecord,
    ModelCostResponse,
    TimeseriesPoint,
)
from error_envelope import ErrorBody, ErrorEnvelope
from models.infrastructure import CloudResource, LiveArchitectureSchema, ScanMetadata


# ── Cost Metering Factories ──────────────────────────────────


class CostRecordFactory(ModelFactory):
    __model__ = CostRecord


class BudgetRuleFactory(ModelFactory):
    __model__ = BudgetRule


class CostAlertFactory(ModelFactory):
    __model__ = CostAlert


class CostOverviewResponseFactory(ModelFactory):
    __model__ = CostOverviewResponse


class ModelCostResponseFactory(ModelFactory):
    __model__ = ModelCostResponse


class TimeseriesPointFactory(ModelFactory):
    __model__ = TimeseriesPoint


class BudgetCreateRequestFactory(ModelFactory):
    __model__ = BudgetCreateRequest


class BudgetUpdateRequestFactory(ModelFactory):
    __model__ = BudgetUpdateRequest


# ── Error Envelope Factories ─────────────────────────────────


class ErrorBodyFactory(ModelFactory):
    __model__ = ErrorBody


class ErrorEnvelopeFactory(ModelFactory):
    __model__ = ErrorEnvelope


# ── Infrastructure Factories ─────────────────────────────────


class CloudResourceFactory(ModelFactory):
    __model__ = CloudResource


class ScanMetadataFactory(ModelFactory):
    __model__ = ScanMetadata


class LiveArchitectureSchemaFactory(ModelFactory):
    __model__ = LiveArchitectureSchema
