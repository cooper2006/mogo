"""Compatibility and pipeline support endpoints for the admin API.

Provides:
- GET /api/v1/admin/compatibility/pipeline-support: Return aggregate stage
  support status across the codebase, including supported stages list and
  call site details.

Endpoints require the admin dependency (``get_current_admin_user``) — the
management plane is not reachable by ordinary callers.
"""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..deps import get_current_admin_user
from ...core.pg_compat import SUPPORTED_AGGREGATION_STAGES, UNSUPPORTED_STAGE_EXPLANATIONS


api_router = APIRouter(
    prefix="/admin/compatibility",
    tags=["compatibility"],
    dependencies=[Depends(get_current_admin_user)],
)


class StageSupportInfo(BaseModel):
    stage: str
    status: str = Field(description="Whether the stage is supported or unsupported")
    recommended_fix: Optional[str] = Field(default=None, description="Recommended alternative if unsupported")


class CallSiteInfo(BaseModel):
    file: str = Field(description="Python source file path")
    line: int = Field(description="Line number where the aggregate call occurs")
    stages: List[str] = Field(description="List of aggregate stages used in this call")
    status: str = Field(description="Overall support status: 'fully_supported' or 'has_unsupported_stage'")


class PipelineSupportResponse(BaseModel):
    supported_stages: List[str] = Field(description="List of stages supported by the pg_compat layer")
    call_sites: List[CallSiteInfo] = Field(description="Details of aggregate call sites and their support status")
    summary: dict = Field(description="Summary statistics")


@api_router.get(
    "/pipeline-support",
    response_model=PipelineSupportResponse,
    summary="Get pipeline support status across codebase",
    description="Returns the supported aggregation stages and details of aggregate call sites "
    "with their support status. Useful for admin diagnostics and CI gate reporting.",
)
async def get_pipeline_support(
    current_admin_user = Depends(get_current_admin_user),
) -> PipelineSupportResponse:
    """Return aggregate stage support status across the codebase.

    Scans all Python files (excluding tests/) for aggregate() calls and reports
    which stages are supported by the pg_compat layer and which are unsupported.
    """
    # 收集所有 aggregate 调用点的阶段信息
    from scripts.check_pg_compat_pipeline_stages import find_aggregate_calls

    violations = find_aggregate_calls("services/admin-api")

    # 构建 call_sites 列表
    call_sites = []
    for v in violations:
        call_sites.append(
            CallSiteInfo(
                file=v["file"],
                line=v["line"],
                stages=[v["stage"]],
                status="has_unsupported_stage" if v["stage"] not in SUPPORTED_AGGREGATION_STAGES else "fully_supported",
            )
        )

    # 计算摘要
    total_calls = len(call_sites)
    fully_supported = sum(
        1 for cs in call_sites if cs.status == "fully_supported"
    )
    has_unsupported = total_calls - fully_supported

    supported_stages_list = sorted(
        list(SUPPORTED_AGGREGATION_STAGES)
    )

    return PipelineSupportResponse(
        supported_stages=supported_stages_list,
        call_sites=call_sites,
        summary={
            "total_calls": total_calls,
            "fully_supported": fully_supported,
            "has_unsupported_stage": has_unsupported,
        },
    )