"""
Archmorph Cost Metering — AI Cost & Token Observability Pipeline (Issue #392).

Provides enterprise-grade cost visibility for all LLM operations:
  - Token counting per call (prompt, completion, total)
  - Cost calculation with per-model pricing
  - Thread-safe in-memory metrics store
  - Budget management with daily/monthly limits per agent
  - Alert thresholds at configurable percentages

Singleton CostMeter — same in-memory pattern as SESSION_STORE.
"""

import csv
import io
import json
import logging
import os
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
# Bootstrap only the most recent slice to bound startup memory; operators can
# tune/disable this via COST_METER_BOOTSTRAP_LIMIT based on deployment size.
try:
    _BOOTSTRAP_RECORD_LIMIT = max(0, int(os.getenv("COST_METER_BOOTSTRAP_LIMIT", "5000")))
except (TypeError, ValueError):
    _BOOTSTRAP_RECORD_LIMIT = 5000


# ─────────────────────────────────────────────────────────────
# Model Pricing (per 1M tokens)
# ─────────────────────────────────────────────────────────────
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "text-embedding-3-small": {"input": 0.02, "output": 0.02},
    "text-embedding-3-large": {"input": 0.13, "output": 0.13},
}

DEFAULT_PRICING = {"input": 2.50, "output": 10.00}


# ─────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────
class BudgetPeriod(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class AlertSeverity(str, Enum):
    WARNING = "warning"
    CRITICAL = "critical"
    EXCEEDED = "exceeded"


# ─────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────
class CostRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    execution_id: Optional[str] = None
    agent_id: Optional[str] = None
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    caller: Optional[str] = None
    owner_user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    actor_kind: Optional[str] = None
    key_id: Optional[str] = None


class BudgetRule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    amount_usd: float = Field(..., gt=0)
    period: BudgetPeriod
    alert_thresholds: List[float] = Field(default=[50.0, 80.0, 100.0])
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    owner_user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    actor_kind: Optional[str] = None
    key_id: Optional[str] = None


class CostAlert(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_id: str
    budget_id: str
    severity: AlertSeverity
    threshold_pct: float
    current_spend: float
    budget_amount: float
    period: BudgetPeriod
    message: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    acknowledged: bool = False
    owner_user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    actor_kind: Optional[str] = None
    key_id: Optional[str] = None


@dataclass(frozen=True)
class CostScope:
    """Canonical cost visibility boundary derived from authentication."""

    owner_user_id: str
    tenant_id: str
    actor_kind: str
    key_id: Optional[str] = None
    global_admin: bool = False

    @classmethod
    def from_credential(cls, context, *, global_admin: bool = False) -> "CostScope":
        if not context.owner_user_id or not context.tenant_id:
            raise ValueError("Canonical cost scope requires owner and tenant")
        return cls(
            owner_user_id=context.owner_user_id,
            tenant_id=context.tenant_id,
            actor_kind=context.kind.value,
            key_id=context.key_id,
            global_admin=bool(global_admin and context.has_scope("admin")),
        )


class CostOverviewResponse(BaseModel):
    total_spend_usd: float
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_records: int
    active_agents: int
    active_models: int
    period_start: Optional[str] = None
    period_end: Optional[str] = None


class AgentCostResponse(BaseModel):
    agent_id: str
    total_spend_usd: float
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_executions: int
    avg_cost_per_execution: float
    models_used: List[str]


class ModelCostResponse(BaseModel):
    model: str
    total_spend_usd: float
    total_prompt_tokens: int
    total_completion_tokens: int
    total_tokens: int
    total_calls: int
    avg_cost_per_call: float


class TimeseriesPoint(BaseModel):
    timestamp: str
    cost_usd: float
    tokens: int
    calls: int


class TopConsumer(BaseModel):
    agent_id: str
    total_spend_usd: float
    total_tokens: int
    execution_count: int
    pct_of_total: float


class BudgetUtilization(BaseModel):
    id: str
    agent_id: str
    amount_usd: float
    period: BudgetPeriod
    current_spend: float
    utilization_pct: float
    alert_thresholds: List[float]
    created_at: str
    updated_at: str


class BudgetCreateRequest(BaseModel):
    agent_id: str
    amount_usd: float = Field(..., gt=0)
    period: BudgetPeriod
    alert_thresholds: List[float] = Field(default=[50.0, 80.0, 100.0])


class BudgetUpdateRequest(BaseModel):
    amount_usd: Optional[float] = Field(None, gt=0)
    period: Optional[BudgetPeriod] = None
    alert_thresholds: Optional[List[float]] = None


# ─────────────────────────────────────────────────────────────
# Cost Calculator
# ─────────────────────────────────────────────────────────────
def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate USD cost from token counts using model pricing table."""
    pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)
    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 8)


# ─────────────────────────────────────────────────────────────
# Singleton Cost Meter
# ─────────────────────────────────────────────────────────────
class CostMeter:
    """Thread-safe in-memory cost metering store.

    Singleton pattern — use CostMeter.instance() to access.
    """

    _instance: Optional["CostMeter"] = None
    _init_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: List[CostRecord] = []
        self._budgets: Dict[str, BudgetRule] = {}
        self._alerts: List[CostAlert] = []
        # Track which alert thresholds have already fired per budget
        # to avoid duplicate alerts: {budget_id: set of threshold_pct values}
        self._fired_thresholds: Dict[str, set] = defaultdict(set)
        # PostgreSQL is canonical. These collections remain only as a local
        # fallback for unit/dev environments without the migrated schema.

    @classmethod
    def instance(cls) -> "CostMeter":
        if cls._instance is not None:
            return cls._instance
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton — for testing only."""
        cls._instance = None

    # ── Record a cost event ──────────────────────────────────
    def record(
        self,
        *,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        execution_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        caller: Optional[str] = None,
        scope: Optional[CostScope] = None,
    ) -> CostRecord:
        """Record a single LLM call's token usage and cost."""
        cost = calculate_cost(model, prompt_tokens, completion_tokens)
        rec = CostRecord(
            execution_id=execution_id,
            agent_id=agent_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=cost,
            caller=caller,
            owner_user_id=scope.owner_user_id if scope else None,
            tenant_id=scope.tenant_id if scope else None,
            actor_kind=scope.actor_kind if scope else None,
            key_id=scope.key_id if scope else None,
        )
        with self._lock:
            self._records.append(rec)

        # Persist to DB (#494) — non-blocking, best-effort
        self._persist_record(rec)

        # Check budgets asynchronously (non-blocking)
        if agent_id and scope:
            self._check_budgets(agent_id, scope=scope)

        return rec

    def _persist_record(self, rec: CostRecord) -> None:
        """Persist cost record to PostgreSQL (best-effort, non-blocking)."""
        try:
            from database import SessionLocal
            db = SessionLocal()
            try:
                from sqlalchemy import text
                db.execute(text(
                    "INSERT INTO cost_records (id, owner_user_id, tenant_id, actor_kind, key_id, execution_id, agent_id, model, prompt_tokens, completion_tokens, total_tokens, cost_usd, caller) "
                    "VALUES (:id, :owner, :tenant, :actor_kind, :key_id, :eid, :aid, :model, :pt, :ct, :tt, :cost, :caller)"
                ), {
                    "id": rec.id, "eid": rec.execution_id, "aid": rec.agent_id,
                    "model": rec.model, "pt": rec.prompt_tokens, "ct": rec.completion_tokens,
                    "tt": rec.total_tokens, "cost": rec.cost_usd, "caller": rec.caller,
                    "owner": rec.owner_user_id, "tenant": rec.tenant_id,
                    "actor_kind": rec.actor_kind, "key_id": rec.key_id,
                })
                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()
        except Exception:
            pass  # DB not available — in-memory still works

    def _hydrate_records_from_db(self) -> None:
        """Bootstrap in-memory records from durable storage after process restarts."""
        if _BOOTSTRAP_RECORD_LIMIT <= 0:
            return
        try:
            from database import SessionLocal
            from sqlalchemy import text
            db = SessionLocal()
            try:
                try:
                    rows = db.execute(
                        text(
                            "SELECT id, owner_user_id, tenant_id, actor_kind, key_id, execution_id, agent_id, model, prompt_tokens, completion_tokens, "
                            "total_tokens, cost_usd, caller, created_at "
                            "FROM cost_records ORDER BY created_at DESC LIMIT :limit"
                        ),
                        {"limit": _BOOTSTRAP_RECORD_LIMIT},
                    ).fetchall()
                except Exception:
                    rows = db.execute(
                        text(
                            "SELECT id, execution_id, agent_id, model, prompt_tokens, completion_tokens, "
                            "total_tokens, cost_usd, caller, created_at "
                            "FROM cost_records ORDER BY created_at DESC LIMIT :limit"
                        ),
                        {"limit": _BOOTSTRAP_RECORD_LIMIT},
                    ).fetchall()
            finally:
                db.close()
        except Exception:
            return

        hydrated: List[CostRecord] = []
        for row in reversed(rows):
            created_at = row.created_at
            if hasattr(created_at, "isoformat"):
                timestamp = created_at.isoformat()
            else:
                timestamp = datetime.now(timezone.utc).isoformat()
            hydrated.append(
                CostRecord(
                    id=row.id,
                    execution_id=row.execution_id,
                    agent_id=row.agent_id,
                    model=row.model,
                    prompt_tokens=int(row.prompt_tokens or 0),
                    completion_tokens=int(row.completion_tokens or 0),
                    total_tokens=int(row.total_tokens or 0),
                    cost_usd=float(row.cost_usd or 0.0),
                    timestamp=timestamp,
                    caller=row.caller,
                    owner_user_id=getattr(row, "owner_user_id", None),
                    tenant_id=getattr(row, "tenant_id", None),
                    actor_kind=getattr(row, "actor_kind", None),
                    key_id=getattr(row, "key_id", None),
                )
            )
        with self._lock:
            self._records = hydrated

    # ── Aggregation helpers ──────────────────────────────────
    def _filter_records(
        self,
        agent_id: Optional[str] = None,
        model: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        scope: Optional[CostScope] = None,
    ) -> List[CostRecord]:
        records = self._load_records(scope=scope)

        filtered = []
        for r in records:
            if agent_id and r.agent_id != agent_id:
                continue
            if model and r.model != model:
                continue
            if since or until:
                ts = datetime.fromisoformat(r.timestamp)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if since and ts < since:
                    continue
                if until and ts > until:
                    continue
            filtered.append(r)
        return filtered

    def _load_records(self, *, scope: Optional[CostScope]) -> List[CostRecord]:
        """Read canonical records; legacy unscoped rows are admin-global only."""
        if scope is None:
            with self._lock:
                return list(self._records)
        try:
            from database import SessionLocal
            from models.cost import CostRecordModel

            db = SessionLocal()
            try:
                query = db.query(CostRecordModel)
                if scope is not None and not scope.global_admin:
                    query = query.filter(
                        CostRecordModel.owner_user_id == scope.owner_user_id,
                        CostRecordModel.tenant_id == scope.tenant_id,
                    )
                rows = query.order_by(CostRecordModel.created_at.asc()).all()
                return [
                    CostRecord(
                        id=row.id,
                        owner_user_id=row.owner_user_id,
                        tenant_id=row.tenant_id,
                        actor_kind=row.actor_kind,
                        key_id=row.key_id,
                        execution_id=row.execution_id,
                        agent_id=row.agent_id,
                        model=row.model,
                        prompt_tokens=int(row.prompt_tokens or 0),
                        completion_tokens=int(row.completion_tokens or 0),
                        total_tokens=int(row.total_tokens or 0),
                        cost_usd=float(row.cost_usd or 0.0),
                        timestamp=row.created_at.isoformat(),
                        caller=row.caller,
                    )
                    for row in rows
                ]
            finally:
                db.close()
        except Exception:
            with self._lock:
                records = list(self._records)
            if scope.global_admin:
                return records
            return [
                record
                for record in records
                if record.owner_user_id == scope.owner_user_id
                and record.tenant_id == scope.tenant_id
            ]

    def get_overview(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        scope: Optional[CostScope] = None,
    ) -> CostOverviewResponse:
        records = self._filter_records(since=since, until=until, scope=scope)
        agents = set()
        models = set()
        total_spend = 0.0
        total_prompt = 0
        total_completion = 0

        for r in records:
            total_spend += r.cost_usd
            total_prompt += r.prompt_tokens
            total_completion += r.completion_tokens
            if r.agent_id:
                agents.add(r.agent_id)
            models.add(r.model)

        return CostOverviewResponse(
            total_spend_usd=round(total_spend, 6),
            total_prompt_tokens=total_prompt,
            total_completion_tokens=total_completion,
            total_tokens=total_prompt + total_completion,
            total_records=len(records),
            active_agents=len(agents),
            active_models=len(models),
            period_start=since.isoformat() if since else None,
            period_end=until.isoformat() if until else None,
        )

    def get_agent_cost(self, agent_id: str, *, scope: Optional[CostScope] = None) -> AgentCostResponse:
        records = self._filter_records(agent_id=agent_id, scope=scope)
        total_spend = 0.0
        total_prompt = 0
        total_completion = 0
        models_used: set = set()

        for r in records:
            total_spend += r.cost_usd
            total_prompt += r.prompt_tokens
            total_completion += r.completion_tokens
            models_used.add(r.model)

        count = len(records)
        return AgentCostResponse(
            agent_id=agent_id,
            total_spend_usd=round(total_spend, 6),
            total_prompt_tokens=total_prompt,
            total_completion_tokens=total_completion,
            total_tokens=total_prompt + total_completion,
            total_executions=count,
            avg_cost_per_execution=round(total_spend / count, 6) if count else 0.0,
            models_used=sorted(models_used),
        )

    def get_model_breakdown(self, *, scope: Optional[CostScope] = None) -> List[ModelCostResponse]:
        records = self._load_records(scope=scope)

        by_model: Dict[str, Dict[str, Any]] = {}
        for r in records:
            if r.model not in by_model:
                by_model[r.model] = {
                    "spend": 0.0, "prompt": 0, "completion": 0, "calls": 0
                }
            m = by_model[r.model]
            m["spend"] += r.cost_usd
            m["prompt"] += r.prompt_tokens
            m["completion"] += r.completion_tokens
            m["calls"] += 1

        result = []
        for model, data in by_model.items():
            calls = data["calls"]
            result.append(ModelCostResponse(
                model=model,
                total_spend_usd=round(data["spend"], 6),
                total_prompt_tokens=data["prompt"],
                total_completion_tokens=data["completion"],
                total_tokens=data["prompt"] + data["completion"],
                total_calls=calls,
                avg_cost_per_call=round(data["spend"] / calls, 6) if calls else 0.0,
            ))
        result.sort(key=lambda x: x.total_spend_usd, reverse=True)
        return result

    def get_timeseries(
        self,
        granularity: str = "hourly",
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        scope: Optional[CostScope] = None,
    ) -> List[TimeseriesPoint]:
        records = self._filter_records(since=since, until=until, scope=scope)

        buckets: Dict[str, Dict[str, Any]] = {}
        for r in records:
            ts = datetime.fromisoformat(r.timestamp)
            if granularity == "daily":
                key = ts.strftime("%Y-%m-%dT00:00:00+00:00")
            elif granularity == "weekly":
                # ISO week start (Monday)
                monday = ts - timedelta(days=ts.weekday())
                key = monday.strftime("%Y-%m-%dT00:00:00+00:00")
            else:  # hourly
                key = ts.strftime("%Y-%m-%dT%H:00:00+00:00")

            if key not in buckets:
                buckets[key] = {"cost": 0.0, "tokens": 0, "calls": 0}
            buckets[key]["cost"] += r.cost_usd
            buckets[key]["tokens"] += r.total_tokens
            buckets[key]["calls"] += 1

        result = []
        for ts_key in sorted(buckets.keys()):
            b = buckets[ts_key]
            result.append(TimeseriesPoint(
                timestamp=ts_key,
                cost_usd=round(b["cost"], 6),
                tokens=b["tokens"],
                calls=b["calls"],
            ))
        return result

    def get_top_consumers(self, limit: int = 10, *, scope: Optional[CostScope] = None) -> List[TopConsumer]:
        records = self._load_records(scope=scope)

        total_spend = sum(r.cost_usd for r in records)
        by_agent: Dict[str, Dict[str, Any]] = {}

        for r in records:
            aid = r.agent_id or "_unattributed"
            if aid not in by_agent:
                by_agent[aid] = {"spend": 0.0, "tokens": 0, "count": 0}
            by_agent[aid]["spend"] += r.cost_usd
            by_agent[aid]["tokens"] += r.total_tokens
            by_agent[aid]["count"] += 1

        result = []
        for aid, data in by_agent.items():
            result.append(TopConsumer(
                agent_id=aid,
                total_spend_usd=round(data["spend"], 6),
                total_tokens=data["tokens"],
                execution_count=data["count"],
                pct_of_total=round(
                    (data["spend"] / total_spend * 100) if total_spend > 0 else 0.0, 2
                ),
            ))
        result.sort(key=lambda x: x.total_spend_usd, reverse=True)
        return result[:limit]

    # ── Budget management ────────────────────────────────────
    def create_budget(self, req: BudgetCreateRequest, *, scope: Optional[CostScope] = None) -> BudgetRule:
        rule = BudgetRule(
            agent_id=req.agent_id,
            amount_usd=req.amount_usd,
            period=req.period,
            alert_thresholds=sorted(req.alert_thresholds),
            owner_user_id=scope.owner_user_id if scope else None,
            tenant_id=scope.tenant_id if scope else None,
            actor_kind=scope.actor_kind if scope else None,
            key_id=scope.key_id if scope else None,
        )
        with self._lock:
            self._budgets[rule.id] = rule
        self._persist_budget(rule)
        return rule

    def update_budget(self, budget_id: str, req: BudgetUpdateRequest, *, scope: Optional[CostScope] = None) -> BudgetRule:
        self._hydrate_budgets(scope=scope)
        with self._lock:
            rule = self._budgets.get(budget_id)
            if not rule:
                raise KeyError(f"Budget {budget_id} not found")
            if req.amount_usd is not None:
                rule.amount_usd = req.amount_usd
            if req.period is not None:
                rule.period = req.period
            if req.alert_thresholds is not None:
                rule.alert_thresholds = sorted(req.alert_thresholds)
            rule.updated_at = datetime.now(timezone.utc).isoformat()
            # Reset fired thresholds when budget is updated
            self._fired_thresholds.pop(budget_id, None)
        self._persist_budget(rule)
        return rule

    def list_budgets(self, *, scope: Optional[CostScope] = None) -> List[BudgetUtilization]:
        self._hydrate_budgets(scope=scope)
        with self._lock:
            budgets = [
                budget
                for budget in self._budgets.values()
                if scope is None
                or scope.global_admin
                or (
                    budget.owner_user_id == scope.owner_user_id
                    and budget.tenant_id == scope.tenant_id
                )
            ]

        result = []
        for b in budgets:
            budget_scope = CostScope(
                owner_user_id=b.owner_user_id or "",
                tenant_id=b.tenant_id or "",
                actor_kind=b.actor_kind or "legacy",
                key_id=b.key_id,
            ) if b.owner_user_id and b.tenant_id else scope
            spend = self._get_period_spend(b.agent_id, b.period, scope=budget_scope)
            util_pct = round((spend / b.amount_usd * 100) if b.amount_usd > 0 else 0.0, 2)
            result.append(BudgetUtilization(
                id=b.id,
                agent_id=b.agent_id,
                amount_usd=b.amount_usd,
                period=b.period,
                current_spend=round(spend, 6),
                utilization_pct=util_pct,
                alert_thresholds=b.alert_thresholds,
                created_at=b.created_at,
                updated_at=b.updated_at,
            ))
        return result

    def _get_period_start(self, period: BudgetPeriod) -> datetime:
        now = datetime.now(timezone.utc)
        if period == BudgetPeriod.DAILY:
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == BudgetPeriod.WEEKLY:
            monday = now - timedelta(days=now.weekday())
            return monday.replace(hour=0, minute=0, second=0, microsecond=0)
        else:  # monthly
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def _get_period_spend(self, agent_id: str, period: BudgetPeriod, *, scope: Optional[CostScope] = None) -> float:
        since = self._get_period_start(period)
        records = self._filter_records(agent_id=agent_id, since=since, scope=scope)
        return sum(r.cost_usd for r in records)

    def _check_budgets(self, agent_id: str, *, scope: CostScope) -> None:
        self._hydrate_budgets(scope=scope)
        with self._lock:
            budgets = [
                b for b in self._budgets.values()
                if b.agent_id == agent_id
                and b.owner_user_id == scope.owner_user_id
                and b.tenant_id == scope.tenant_id
            ]

        for b in budgets:
            spend = self._get_period_spend(agent_id, b.period, scope=scope)
            util_pct = (spend / b.amount_usd * 100) if b.amount_usd > 0 else 0.0

            for threshold in b.alert_thresholds:
                if util_pct >= threshold and threshold not in self._fired_thresholds[b.id]:
                    if threshold >= 100:
                        severity = AlertSeverity.EXCEEDED
                    elif threshold >= 80:
                        severity = AlertSeverity.CRITICAL
                    else:
                        severity = AlertSeverity.WARNING

                    alert = CostAlert(
                        agent_id=agent_id,
                        budget_id=b.id,
                        severity=severity,
                        threshold_pct=threshold,
                        current_spend=round(spend, 6),
                        budget_amount=b.amount_usd,
                        period=b.period,
                        message=(
                            f"Agent {agent_id} has reached {util_pct:.1f}% "
                            f"of its {b.period.value} budget "
                            f"(${spend:.4f} / ${b.amount_usd:.2f})"
                        ),
                        owner_user_id=scope.owner_user_id,
                        tenant_id=scope.tenant_id,
                        actor_kind=scope.actor_kind,
                        key_id=scope.key_id,
                    )
                    with self._lock:
                        self._alerts.append(alert)
                        self._fired_thresholds[b.id].add(threshold)
                    self._persist_alert(alert)

                    logger.warning(
                        "Cost alert: agent=%s budget=%s severity=%s spend=$%.4f limit=$%.2f",
                        agent_id, b.id, severity.value, spend, b.amount_usd,
                    )

    def get_alerts(self, active_only: bool = True, *, scope: Optional[CostScope] = None) -> List[CostAlert]:
        self._hydrate_alerts(scope=scope)
        with self._lock:
            alerts = [
                alert
                for alert in self._alerts
                if scope is None
                or scope.global_admin
                or (
                    alert.owner_user_id == scope.owner_user_id
                    and alert.tenant_id == scope.tenant_id
                )
            ]
        if active_only:
            alerts = [a for a in alerts if not a.acknowledged]
        alerts.sort(key=lambda a: a.timestamp, reverse=True)
        return alerts

    def is_budget_exceeded(self, agent_id: str, *, scope: Optional[CostScope] = None) -> bool:
        """Check if any budget for this agent is exceeded (for enforcement)."""
        self._hydrate_budgets(scope=scope)
        with self._lock:
            budgets = [
                b for b in self._budgets.values()
                if b.agent_id == agent_id
                and (
                    scope is None
                    or scope.global_admin
                    or (
                        b.owner_user_id == scope.owner_user_id
                        and b.tenant_id == scope.tenant_id
                    )
                )
            ]

        for b in budgets:
            spend = self._get_period_spend(agent_id, b.period, scope=scope)
            if spend >= b.amount_usd:
                return True
        return False

    # ── CSV Export ────────────────────────────────────────────
    def export_csv(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        scope: Optional[CostScope] = None,
    ) -> str:
        records = self._filter_records(since=since, until=until, scope=scope)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "execution_id", "agent_id", "model",
            "prompt_tokens", "completion_tokens", "total_tokens",
            "cost_usd", "timestamp", "caller",
        ])
        for r in records:
            writer.writerow([
                r.id, r.execution_id or "", r.agent_id or "", r.model,
                r.prompt_tokens, r.completion_tokens, r.total_tokens,
                r.cost_usd, r.timestamp, r.caller or "",
            ])
        return output.getvalue()

    def _persist_budget(self, rule: BudgetRule) -> None:
        if not rule.owner_user_id or not rule.tenant_id:
            return
        try:
            from database import SessionLocal
            from models.cost import CostBudgetModel

            db = SessionLocal()
            try:
                row = db.get(CostBudgetModel, rule.id) or CostBudgetModel(id=rule.id)
                row.owner_user_id = rule.owner_user_id
                row.tenant_id = rule.tenant_id
                row.actor_kind = rule.actor_kind or "unknown"
                row.key_id = rule.key_id
                row.agent_id = rule.agent_id
                row.amount_usd = rule.amount_usd
                row.period = rule.period.value
                row.alert_thresholds = json.dumps(rule.alert_thresholds)
                db.add(row)
                db.commit()
            finally:
                db.close()
        except Exception:
            logger.warning("cost_budget_persistence_failed error_type=database")

    def _hydrate_budgets(self, *, scope: Optional[CostScope]) -> None:
        try:
            from database import SessionLocal
            from models.cost import CostBudgetModel

            db = SessionLocal()
            try:
                query = db.query(CostBudgetModel)
                if scope is not None and not scope.global_admin:
                    query = query.filter(
                        CostBudgetModel.owner_user_id == scope.owner_user_id,
                        CostBudgetModel.tenant_id == scope.tenant_id,
                    )
                rows = query.all()
            finally:
                db.close()
            with self._lock:
                for row in rows:
                    self._budgets[row.id] = BudgetRule(
                        id=row.id,
                        owner_user_id=row.owner_user_id,
                        tenant_id=row.tenant_id,
                        actor_kind=row.actor_kind,
                        key_id=row.key_id,
                        agent_id=row.agent_id,
                        amount_usd=row.amount_usd,
                        period=BudgetPeriod(row.period),
                        alert_thresholds=json.loads(row.alert_thresholds),
                        created_at=row.created_at.isoformat(),
                        updated_at=row.updated_at.isoformat(),
                    )
        except Exception:
            return

    def _persist_alert(self, alert: CostAlert) -> None:
        if not alert.owner_user_id or not alert.tenant_id:
            return
        try:
            from database import SessionLocal
            from models.cost import CostAlertModel

            db = SessionLocal()
            try:
                db.merge(CostAlertModel(
                    id=alert.id,
                    owner_user_id=alert.owner_user_id,
                    tenant_id=alert.tenant_id,
                    actor_kind=alert.actor_kind or "unknown",
                    key_id=alert.key_id,
                    agent_id=alert.agent_id,
                    budget_id=alert.budget_id,
                    severity=alert.severity.value,
                    threshold_pct=alert.threshold_pct,
                    current_spend=alert.current_spend,
                    budget_amount=alert.budget_amount,
                    period=alert.period.value,
                    message=alert.message,
                    acknowledged=alert.acknowledged,
                ))
                db.commit()
            finally:
                db.close()
        except Exception:
            logger.warning("cost_alert_persistence_failed error_type=database")

    def _hydrate_alerts(self, *, scope: Optional[CostScope]) -> None:
        try:
            from database import SessionLocal
            from models.cost import CostAlertModel

            db = SessionLocal()
            try:
                query = db.query(CostAlertModel)
                if scope is not None and not scope.global_admin:
                    query = query.filter(
                        CostAlertModel.owner_user_id == scope.owner_user_id,
                        CostAlertModel.tenant_id == scope.tenant_id,
                    )
                rows = query.all()
            finally:
                db.close()
            with self._lock:
                by_id = {alert.id: alert for alert in self._alerts}
                for row in rows:
                    by_id[row.id] = CostAlert(
                        id=row.id,
                        owner_user_id=row.owner_user_id,
                        tenant_id=row.tenant_id,
                        actor_kind=row.actor_kind,
                        key_id=row.key_id,
                        agent_id=row.agent_id,
                        budget_id=row.budget_id,
                        severity=AlertSeverity(row.severity),
                        threshold_pct=row.threshold_pct,
                        current_spend=row.current_spend,
                        budget_amount=row.budget_amount,
                        period=BudgetPeriod(row.period),
                        message=row.message,
                        timestamp=row.created_at.isoformat(),
                        acknowledged=bool(row.acknowledged),
                    )
                self._alerts = list(by_id.values())
        except Exception:
            return
