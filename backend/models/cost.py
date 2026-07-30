"""Canonical tenant/principal-scoped AI cost observability models."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.sql import func

from database import Base


class CostRecordModel(Base):
    """One durable token/cost event owned by an authenticated scope."""

    __tablename__ = "cost_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_user_id = Column(String(100), nullable=True, index=True)
    tenant_id = Column(String(100), nullable=True, index=True)
    actor_kind = Column(String(20), nullable=True)
    key_id = Column(String(64), nullable=True)
    execution_id = Column(String, nullable=True)
    agent_id = Column(String, nullable=True, index=True)
    model = Column(String, nullable=False, index=True)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    caller = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_cost_records_scope_created", "owner_user_id", "tenant_id", "created_at"),
    )


class CostBudgetModel(Base):
    """Durable budget rule within one canonical caller scope."""

    __tablename__ = "cost_budgets"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_user_id = Column(String(100), nullable=False)
    tenant_id = Column(String(100), nullable=False)
    actor_kind = Column(String(20), nullable=False)
    key_id = Column(String(64), nullable=True)
    agent_id = Column(String(100), nullable=False)
    amount_usd = Column(Float, nullable=False)
    period = Column(String(20), nullable=False)
    alert_thresholds = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_cost_budgets_scope", "owner_user_id", "tenant_id"),
    )


class CostAlertModel(Base):
    """Durable cost alert bound to its budget and canonical caller scope."""

    __tablename__ = "cost_alerts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_user_id = Column(String(100), nullable=False)
    tenant_id = Column(String(100), nullable=False)
    actor_kind = Column(String(20), nullable=False)
    key_id = Column(String(64), nullable=True)
    agent_id = Column(String(100), nullable=False)
    budget_id = Column(String(36), nullable=False)
    severity = Column(String(20), nullable=False)
    threshold_pct = Column(Float, nullable=False)
    current_spend = Column(Float, nullable=False)
    budget_amount = Column(Float, nullable=False)
    period = Column(String(20), nullable=False)
    message = Column(Text, nullable=False)
    acknowledged = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_cost_alerts_scope_created", "owner_user_id", "tenant_id", "created_at"),
        Index("ux_cost_alerts_budget_threshold", "budget_id", "threshold_pct", unique=True),
    )
