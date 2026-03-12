import logging
from typing import Dict, Any
from fastapi import APIRouter
from pydantic import BaseModel
from error_envelope import ArchmorphException

from services.drift_detection import DriftDetector

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/drift", tags=["Drift Detection"])

class DriftRequest(BaseModel):
    designed_state: Dict[str, Any]
    live_state: Dict[str, Any]

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
