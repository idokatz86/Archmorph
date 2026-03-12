from error_envelope import ArchmorphException
"""User Dashboard API — analysis history, saved diagrams, usage stats (#151).

Endpoints:
  GET  /api/dashboard/analyses          — paginated analysis history
  GET  /api/dashboard/analyses/{id}     — single analysis detail
  POST /api/dashboard/analyses/{id}/save — bookmark / pin an analysis
  DELETE /api/dashboard/analyses/{id}/save — remove bookmark
  GET  /api/dashboard/stats             — usage summary for dashboard cards
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func, desc
from sqlalchemy.orm import Session

from database import get_db
from models.user_history import UserAnalysis, SavedDiagram

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ── Pydantic Schemas ─────────────────────────────────────────
class AnalysisSummary(BaseModel):
    analysis_id: str
    diagram_id: str
    title: Optional[str] = None
    source_provider: str = "aws"
    target_provider: str = "azure"
    services_detected: int = 0
    mappings_count: int = 0
    confidence_avg: Optional[float] = None
    status: str = "completed"
    iac_generated: bool = False
    hld_generated: bool = False
    cost_estimated: bool = False
    is_saved: bool = False
    created_at: Optional[str] = None


class AnalysisListResponse(BaseModel):
    analyses: list[AnalysisSummary]
    total: int
    page: int
    page_size: int
    has_more: bool


class DashboardStats(BaseModel):
    total_analyses: int = 0
    analyses_this_month: int = 0
    iac_generated: int = 0
    hld_generated: int = 0
    cost_estimated: int = 0
    saved_diagrams: int = 0
    top_source_providers: dict = Field(default_factory=dict)


class SaveRequest(BaseModel):
    label: Optional[str] = None
    pinned: bool = False


# ── Helpers ──────────────────────────────────────────────────
def _get_user_id() -> str:
    """Placeholder — in production wired to auth dependency."""
    return "anonymous"


# ── Endpoints ────────────────────────────────────────────────
@router.get("/analyses", response_model=AnalysisListResponse)
def list_analyses(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source_provider: Optional[str] = None,
    target_provider: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Paginated list of user's past analyses."""
    user_id = _get_user_id()
    q = db.query(UserAnalysis).filter(UserAnalysis.user_id == user_id)

    if source_provider:
        q = q.filter(UserAnalysis.source_provider == source_provider)
    if target_provider:
        q = q.filter(UserAnalysis.target_provider == target_provider)

    total = q.count()
    analyses = (
        q.order_by(desc(UserAnalysis.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # Check which are saved/bookmarked
    saved_ids = set()
    if analyses:
        aids = [a.analysis_id for a in analyses]
        saved_rows = (
            db.query(SavedDiagram.analysis_id)
            .filter(SavedDiagram.user_id == user_id, SavedDiagram.analysis_id.in_(aids))
            .all()
        )
        saved_ids = {r[0] for r in saved_rows}

    return AnalysisListResponse(
        analyses=[
            AnalysisSummary(
                **{k: v for k, v in a.to_dict().items() if k in AnalysisSummary.model_fields},
                is_saved=a.analysis_id in saved_ids,
            )
            for a in analyses
        ],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str, db: Session = Depends(get_db)):
    """Full analysis detail (includes snapshot)."""
    user_id = _get_user_id()
    row = (
        db.query(UserAnalysis)
        .filter(UserAnalysis.analysis_id == analysis_id, UserAnalysis.user_id == user_id)
        .first()
    )
    if not row:
        raise ArchmorphException(status_code=404, detail="Analysis not found")
    return row.to_dict()


@router.post("/analyses/{analysis_id}/save")
def save_analysis(analysis_id: str, body: SaveRequest, db: Session = Depends(get_db)):
    """Bookmark an analysis."""
    user_id = _get_user_id()
    # Verify analysis belongs to user
    analysis = (
        db.query(UserAnalysis)
        .filter(UserAnalysis.analysis_id == analysis_id, UserAnalysis.user_id == user_id)
        .first()
    )
    if not analysis:
        raise ArchmorphException(status_code=404, detail="Analysis not found")

    existing = (
        db.query(SavedDiagram)
        .filter(SavedDiagram.user_id == user_id, SavedDiagram.analysis_id == analysis_id)
        .first()
    )
    if existing:
        existing.label = body.label or existing.label
        existing.pinned = body.pinned
    else:
        db.add(SavedDiagram(
            user_id=user_id,
            analysis_id=analysis_id,
            label=body.label,
            pinned=body.pinned,
        ))
    db.commit()
    return {"status": "saved"}


@router.delete("/analyses/{analysis_id}/save")
def unsave_analysis(analysis_id: str, db: Session = Depends(get_db)):
    """Remove bookmark."""
    user_id = _get_user_id()
    deleted = (
        db.query(SavedDiagram)
        .filter(SavedDiagram.user_id == user_id, SavedDiagram.analysis_id == analysis_id)
        .delete()
    )
    db.commit()
    if not deleted:
        raise ArchmorphException(status_code=404, detail="Bookmark not found")
    return {"status": "removed"}


@router.get("/stats", response_model=DashboardStats)
def dashboard_stats(db: Session = Depends(get_db)):
    """Usage summary for dashboard header cards."""
    user_id = _get_user_id()
    base = db.query(UserAnalysis).filter(UserAnalysis.user_id == user_id)

    total = base.count()
    month_count = (
        base.filter(
            sa_func.strftime("%Y-%m", UserAnalysis.created_at) == sa_func.strftime("%Y-%m", sa_func.now())
        ).count()
    )
    iac_count = base.filter(UserAnalysis.iac_generated.is_(True)).count()
    hld_count = base.filter(UserAnalysis.hld_generated.is_(True)).count()
    cost_count = base.filter(UserAnalysis.cost_estimated.is_(True)).count()
    saved_count = db.query(SavedDiagram).filter(SavedDiagram.user_id == user_id).count()

    # Top source providers
    provider_rows = (
        base.with_entities(UserAnalysis.source_provider, sa_func.count())
        .group_by(UserAnalysis.source_provider)
        .order_by(sa_func.count().desc())
        .limit(5)
        .all()
    )

    return DashboardStats(
        total_analyses=total,
        analyses_this_month=month_count,
        iac_generated=iac_count,
        hld_generated=hld_count,
        cost_estimated=cost_count,
        saved_diagrams=saved_count,
        top_source_providers={row[0]: row[1] for row in provider_rows},
    )
