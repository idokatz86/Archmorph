import logging
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter
from pydantic import Field
from strict_models import StrictBaseModel
from error_envelope import ArchmorphException

from services.drift_detection import DriftDetector

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/drift", tags=["Drift Detection"])

_BASELINES: Dict[str, Dict[str, Any]] = {}

class DriftRequest(StrictBaseModel):
    designed_state: Dict[str, Any]
    live_state: Dict[str, Any]


class DriftBaselineCreate(StrictBaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    designed_state: Dict[str, Any]
    live_state: Optional[Dict[str, Any]] = None
    source: str = Field(default="manual", max_length=40)


class DriftCompareRequest(StrictBaseModel):
    live_state: Dict[str, Any]


class DriftFindingDecision(StrictBaseModel):
    decision: str = Field(..., pattern="^(accepted|rejected|deferred|open)$")
    note: Optional[str] = Field(default=None, max_length=500)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _detector() -> DriftDetector:
    return DriftDetector()


def _baseline_or_404(baseline_id: str) -> Dict[str, Any]:
    baseline = _BASELINES.get(baseline_id)
    if baseline is None:
        raise ArchmorphException(status_code=404, detail=f"Drift baseline '{baseline_id}' not found")
    return baseline


def _run_compare(designed_state: Dict[str, Any], live_state: Dict[str, Any]) -> Dict[str, Any]:
    result = _detector().detect_environmental_drift(designed_state, live_state)
    result["audit_id"] = f"audit-{uuid4().hex[:12]}"
    return result


def _summarize_baseline(baseline: Dict[str, Any]) -> Dict[str, Any]:
    last_result = baseline.get("last_result") or {}
    summary = last_result.get("summary") or {}
    return {
        "baseline_id": baseline["baseline_id"],
        "name": baseline["name"],
        "source": baseline["source"],
        "created_at": baseline["created_at"],
        "updated_at": baseline["updated_at"],
        "audit_count": len(baseline.get("history", [])),
        "last_score": last_result.get("overall_score"),
        "last_status": summary.get("status", "not_checked"),
        "last_summary": summary,
    }


def _build_report(baseline: Dict[str, Any]) -> str:
    last_result = baseline.get("last_result") or {}
    summary = last_result.get("summary") or {}
    findings: List[Dict[str, Any]] = last_result.get("detailed_findings") or []
    lines = [
        f"# Drift Report: {baseline['name']}",
        "",
        f"- Baseline ID: `{baseline['baseline_id']}`",
        f"- Generated: {last_result.get('generated_at', _now())}",
        f"- Overall Score: {round((last_result.get('overall_score') or 0) * 100)}%",
        f"- Status: {summary.get('status', 'not_checked')}",
        f"- Matched: {summary.get('matched', 0)}",
        f"- Modified: {summary.get('modified', 0)}",
        f"- Shadow: {summary.get('shadow', 0)}",
        f"- Missing: {summary.get('missing', 0)}",
        "",
        "## Findings",
    ]
    if not findings:
        lines.append("No drift findings recorded yet.")
    for finding in findings:
        lines.extend([
            "",
            f"### {finding.get('id', 'unknown')} ({finding.get('status', 'unknown')})",
            f"- Finding ID: `{finding.get('finding_id', '')}`",
            f"- Message: {finding.get('message', '')}",
            f"- Resolution: {finding.get('resolution_status', 'open')}",
            f"- Recommendation: {finding.get('recommendation', '')}",
        ])
        if finding.get("resolution_note"):
            lines.append(f"- Note: {finding['resolution_note']}")
    return "\n".join(lines) + "\n"

@router.post("/detect")
async def detect_drift(request: DriftRequest):
    """
    Compare designed diagram vs live cloud state.
    Returns drifted components.
    """
    try:
        detector = DriftDetector()
        results = detector.detect_environmental_drift(request.designed_state, request.live_state)
        return results
    except Exception as e:
        logger.error(f"Drift detection failed: {e}")
        raise ArchmorphException(status_code=500, message="Failed to analyze drift", context={"error": str(e)})


@router.post("/baselines")
async def create_baseline(request: DriftBaselineCreate):
    """Create a drift baseline and optionally run the first comparison."""
    baseline_id = f"baseline-{uuid4().hex[:12]}"
    now = _now()
    baseline = {
        "baseline_id": baseline_id,
        "name": request.name,
        "source": request.source,
        "designed_state": request.designed_state,
        "created_at": now,
        "updated_at": now,
        "history": [],
        "last_result": None,
    }
    if request.live_state is not None:
        result = _run_compare(request.designed_state, request.live_state)
        baseline["last_result"] = result
        baseline["history"].append(result)
    _BASELINES[baseline_id] = baseline
    return deepcopy(baseline)


@router.get("/baselines")
async def list_baselines():
    """List drift baselines with their last audit summary."""
    return {
        "baselines": [_summarize_baseline(item) for item in _BASELINES.values()],
        "total": len(_BASELINES),
    }


@router.get("/baselines/{baseline_id}")
async def get_baseline(baseline_id: str):
    """Return a complete drift baseline record."""
    return deepcopy(_baseline_or_404(baseline_id))


@router.post("/baselines/{baseline_id}/compare")
async def compare_baseline(baseline_id: str, request: DriftCompareRequest):
    """Run a new drift audit against a saved baseline."""
    baseline = _baseline_or_404(baseline_id)
    result = _run_compare(baseline["designed_state"], request.live_state)
    baseline["last_result"] = result
    baseline["history"].append(result)
    baseline["updated_at"] = _now()
    return deepcopy(result)


@router.patch("/baselines/{baseline_id}/findings/{finding_id}")
async def decide_finding(baseline_id: str, finding_id: str, request: DriftFindingDecision):
    """Accept, reject, defer, or reopen a drift finding."""
    baseline = _baseline_or_404(baseline_id)
    result = baseline.get("last_result")
    if not result:
        raise ArchmorphException(status_code=404, detail="Baseline has no drift audit yet")
    for finding in result.get("detailed_findings", []):
        if finding.get("finding_id") == finding_id:
            finding["resolution_status"] = request.decision
            finding["resolution_note"] = request.note or ""
            finding["resolved_at"] = _now() if request.decision != "open" else None
            baseline["updated_at"] = _now()
            return deepcopy(finding)
    raise ArchmorphException(status_code=404, detail=f"Finding '{finding_id}' not found")


@router.get("/baselines/{baseline_id}/report")
async def get_baseline_report(baseline_id: str):
    """Return a Markdown drift report for export."""
    baseline = _baseline_or_404(baseline_id)
    return {
        "baseline_id": baseline_id,
        "format": "markdown",
        "content": _build_report(baseline),
    }
