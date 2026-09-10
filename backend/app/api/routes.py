"""REST API routes (.freebuff/10_API_CONTRACTS.md)."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from app.schemas.api import (
    AnalysisDetailResponse,
    AnalysisListResponse,
    AnalysisStartRequest,
    AnalysisStartResponse,
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    HealthResponse,
)
from app.services.analysis_service import AnalysisService

router = APIRouter(prefix="/api")


def get_service(request: Request) -> AnalysisService:
    return request.app.state.analysis_service


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post(
    "/analyses",
    response_model=AnalysisStartResponse,
    status_code=201,
    tags=["analyses"],
)
def start_analysis(
    payload: AnalysisStartRequest,
    background: BackgroundTasks,
    service: AnalysisService = Depends(get_service),
) -> AnalysisStartResponse:
    """Start an analysis. The agent runs in the background; poll
    GET /api/analyses/{id} for progress."""
    analysis_id = service.start_analysis(payload.repository, payload.issue_number)
    background.add_task(service.run_analysis, analysis_id)
    return AnalysisStartResponse(analysis_id=analysis_id, status="queued")


@router.get("/analyses", response_model=AnalysisListResponse, tags=["analyses"])
def list_analyses(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: AnalysisService = Depends(get_service),
) -> AnalysisListResponse:
    return service.list_analyses(limit=limit, offset=offset)


@router.get(
    "/analyses/{analysis_id}",
    response_model=AnalysisDetailResponse,
    tags=["analyses"],
)
def get_analysis(
    analysis_id: str, service: AnalysisService = Depends(get_service)
) -> AnalysisDetailResponse:
    return service.get_analysis(analysis_id)


@router.post(
    "/analyses/{analysis_id}/approve",
    response_model=ApprovalDecisionResponse,
    tags=["analyses"],
)
def approve(
    analysis_id: str,
    payload: ApprovalDecisionRequest | None = None,
    service: AnalysisService = Depends(get_service),
) -> ApprovalDecisionResponse:
    result = service.approve(analysis_id, payload.approval_id if payload else None)
    status_code = 200 if result["success"] else 502
    if not result["success"]:
        raise HTTPException(
            status_code=status_code,
            detail={"code": "approval_execution_failed", "message": result["error"]},
        )
    return ApprovalDecisionResponse(
        analysis_id=analysis_id,
        approval_id=result["approval_id"],
        status="approved",
    )


@router.post(
    "/analyses/{analysis_id}/reject",
    response_model=ApprovalDecisionResponse,
    tags=["analyses"],
)
def reject(
    analysis_id: str,
    payload: ApprovalDecisionRequest | None = None,
    service: AnalysisService = Depends(get_service),
) -> ApprovalDecisionResponse:
    result = service.reject(analysis_id, payload.approval_id if payload else None)
    return ApprovalDecisionResponse(
        analysis_id=analysis_id,
        approval_id=result["approval_id"],
        status="rejected",
    )