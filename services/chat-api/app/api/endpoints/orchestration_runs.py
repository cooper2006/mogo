"""编排运行与审批待办端点（050 FR-002/003/005/007/008，T008/T015）。

数据面 = ``orchestration_runs`` 集合（050 ``run_store.py``）。鉴权与租户隔离
沿用 039 ``orchestrations.py`` 口径：端用户 principal + ``tenant_id`` 过滤；
审批决策的三重校验（非发起人 / 待办审批人本人 / 审批人仍有效）在
``RunDriver.decide`` 内 fail-closed。

节点执行体（runner）：编排运行 API 与引擎保持 transport-agnostic —— 默认
runner 为**声明式回显**（输出节点 payload 的 inputs/skill 声明），真实技能执行
由调用方经 ``set_run_runner`` 注入（生产接线点，与 010 runner 注入同构）。

恢复扫描：``POST /api/v1/orchestration-runs/recovery-sweep`` 供部署侧手动触发；``app/main.py``
启动时执行一次，且常驻 ``_orchestration_recovery_loop``（60s）持续扫描（重启后挂起
运行/超时判定不丢，FR-005/FR-006；扫描周期压在 R-7「≤ 租约 TTL 一半」上限）。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.principal import ApiPrincipal, require_end_user_principal
from app.core.db import get_db
from app.core.ids import to_backend_id
from app.core.tenant import add_tenant_scope
from app.governance.approval_runtime import ApprovalRuntime
from app.orchestration.human_approval import ApprovalError, RunDriver
from app.orchestration.loader import OrchestrationLoadError, load_orchestration_document
from app.orchestration.notifications import render_approval_reminder
from app.orchestration.run_store import RunStore, RunStoreError
from app.services.portal.requests import PortalRequestError, require_asset_use

router = APIRouter(
    prefix="/api/v1/orchestration-runs",
    dependencies=[Depends(require_end_user_principal)],
)

#: 进程级审批票据运行时（两段式设计：持久化待办在 DB，票据只在决策瞬间存在）。
_approval_runtime = ApprovalRuntime()

#: 生产 runner 注入点：默认声明式回显，接线方替换为真实技能执行。
_run_runner: Optional[Callable[..., Awaitable[Any]]] = None


def set_run_runner(runner: Callable[..., Awaitable[Any]] | None) -> None:
    global _run_runner
    _run_runner = runner


async def _declarative_runner(node: Any, context: dict[str, Any]) -> Any:
    payload = dict(node.payload or {})
    return {
        "node_id": node.id,
        "skill": payload.get("skill"),
        "inputs": payload.get("inputs"),
        "echo": True,
    }


def effective_runner() -> Callable[..., Awaitable[Any]]:
    return _run_runner or _declarative_runner


class ApiResponse(BaseModel):
    code: int = 0
    message: Optional[str] = None
    data: Optional[Any] = None


class StartRunPayload(BaseModel):
    document: dict[str, Any]
    context: Optional[dict[str, Any]] = None
    debug: bool = False


class DecisionPayload(BaseModel):
    decision: str
    reason: str = ""
    node_id: str = Field(validation_alias="nodeId")


class ReassignPayload(BaseModel):
    node_id: str = Field(validation_alias="nodeId")
    approver: str


class CancelPayload(BaseModel):
    reason: str = ""


class ReviewPayload(BaseModel):
    node_id: str = Field(validation_alias="nodeId")
    action: str


def _store() -> RunStore:
    db = get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="data backend not initialized")
    try:
        return RunStore(db)
    except RunStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


async def _approver_exists(tenant_id: str) -> Callable[[str], Awaitable[bool]]:
    async def validate(user_id: str) -> bool:
        db = get_db()
        if db is None:
            return False
        try:
            doc = await db["end_users"].find_one(
                add_tenant_scope({"_id": to_backend_id(user_id), "status": "active"}, tenant_id)
            )
        except Exception:  # noqa: BLE001 - 非法 id 形状按不存在处理（fail-closed）
            return False
        return doc is not None

    return validate


async def _driver(principal: ApiPrincipal) -> RunDriver:
    return RunDriver(
        _store(),
        approval_runtime=_approval_runtime,
        approver_validator=await _approver_exists(principal.tenant_id),
    )


def _run_view(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "runId": doc.get("run_id"),
        "orchestrationId": doc.get("orchestration_id"),
        "definitionVersion": doc.get("definition_version"),
        "status": doc.get("status"),
        "initiatorId": doc.get("initiator_id"),
        "outcomes": doc.get("outcomes") or {},
        "context": doc.get("context") or {},
        "pendingApprovals": doc.get("pending_approvals") or {},
        "decisionHistory": doc.get("decision_history") or [],
        "events": doc.get("events") or [],
        "createdAt": doc.get("created_at"),
        "updatedAt": doc.get("updated_at"),
    }


@router.post("", response_model=ApiResponse)
async def start_run(
    payload: StartRunPayload,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> ApiResponse:
    try:
        load_orchestration_document(payload.document)
    except OrchestrationLoadError as exc:
        raise HTTPException(status_code=422, detail=f"orchestration document invalid: {exc}") from exc
    # T019 副本使用检查点（FR-007 fail-closed）：document 带 template_ref 即 SOP
    # 模板副本 → 用户必须已开通 asset:use:<orchestration_id> 授权（037/001 申领）。
    header = payload.document.get("orchestration") or {}
    template_ref = header.get("template_ref") if isinstance(header, dict) else None
    if template_ref:
        orchestration_id = str(header.get("id") or "")
        try:
            await require_asset_use(
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                asset_key=orchestration_id,
            )
        except PortalRequestError as exc:
            raise HTTPException(status_code=403, detail=exc.reason) from exc
    # T021 调试工作区（FR-009 / OQ-1 已定）：显式调试标记合并进 run context，
    # 复用既有会话试跑（不新建隔离环境）；调试标记随 run 文档持久化（可查）。
    run_context = dict(payload.context or {})
    if payload.debug:
        run_context["debug"] = True
    # 生产 runner（LocalBridge）按 user_id 绑定浏览器 agent 会话，缺省补发起人
    # 身份，调用方不必每次手传（session_id 无法代补，仍由 payload.context 提供）。
    run_context.setdefault("user_id", principal.user_id)
    driver = await _driver(principal)
    try:
        run = await driver.start(
            document=payload.document,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            runner=effective_runner(),
            context=run_context,
        )
    except OrchestrationLoadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RunStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApiResponse(data=_run_view(run))


@router.get("", response_model=ApiResponse)
async def list_runs(
    status: Optional[str] = None,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> ApiResponse:
    runs = await _store().list_runs(tenant_id=principal.tenant_id, status=status)
    return ApiResponse(data=[_run_view(run) for run in runs])


@router.get("/todos", response_model=ApiResponse)
async def list_todos(
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> ApiResponse:
    todos = await _store().list_todos(tenant_id=principal.tenant_id, approver=principal.user_id)
    for todo in todos:
        todo["rendered"] = render_approval_reminder(todo)
    return ApiResponse(data=todos)


@router.get("/{run_id}", response_model=ApiResponse)
async def get_run(
    run_id: str,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> ApiResponse:
    run = await _store().get_run(run_id, tenant_id=principal.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    return ApiResponse(data=_run_view(run))


@router.post("/{run_id}/decisions", response_model=ApiResponse)
async def submit_decision(
    run_id: str,
    payload: DecisionPayload,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> ApiResponse:
    driver = await _driver(principal)
    try:
        outcome = await driver.decide(
            run_id,
            node_id=payload.node_id,
            actor_id=principal.user_id,
            decision=payload.decision,
            reason=payload.reason,
            runner=effective_runner(),
            tenant_id=principal.tenant_id,
        )
    except ApprovalError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RunStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # 056 R-7：SOP 审批决策旁路镜像到统一内核（补 P1-3 审计链缺口）。
    # 开关默认关闭、失败不阻断；RunStore 仍是 run 文档的唯一仲裁源。
    from app.common.approval_mirror import mirror_decision

    await mirror_decision(
        source="sop", source_id=f"{run_id}:{payload.node_id}",
        tenant_id=principal.tenant_id, actor_id=principal.user_id,
        approved=outcome.decision == "approve", reason=str(payload.reason or ""),
    )
    return ApiResponse(data={
        "runId": outcome.run_id, "nodeId": outcome.node_id,
        "decision": outcome.decision, "status": outcome.run_status,
    })


@router.post("/{run_id}/cancel", response_model=ApiResponse)
async def cancel_run(
    run_id: str,
    payload: CancelPayload,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> ApiResponse:
    store = _store()
    run = await store.get_run(run_id, tenant_id=principal.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    if run.get("initiator_id") != principal.user_id:
        raise HTTPException(status_code=403, detail="only the initiator (or admin) may cancel a run")
    try:
        await store.cancel(run_id, actor_id=principal.user_id, reason=payload.reason)
    except RunStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApiResponse(data={"runId": run_id, "status": "cancelled"})


@router.post("/{run_id}/reassign", response_model=ApiResponse)
async def reassign_approval(
    run_id: str,
    payload: ReassignPayload,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> ApiResponse:
    store = _store()
    run = await store.get_run(run_id, tenant_id=principal.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    if run.get("initiator_id") != principal.user_id:
        raise HTTPException(status_code=403, detail="only the initiator (or admin) may reassign")
    validate = await _approver_exists(principal.tenant_id)
    if not await validate(payload.approver):
        raise HTTPException(status_code=422, detail=f"approver {payload.approver!r} not found or inactive")
    try:
        await store.reassign(run_id, node_id=payload.node_id, new_approver=payload.approver, actor_id=principal.user_id)
    except RunStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ApiResponse(data={"runId": run_id, "nodeId": payload.node_id, "approver": payload.approver})


@router.post("/{run_id}/review", response_model=ApiResponse)
async def resolve_review(
    run_id: str,
    payload: ReviewPayload,
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> ApiResponse:
    """needs_review 处置（OQ-3 首期交付）：skip 续跑 / terminate 终止。"""
    store = _store()
    run = await store.get_run(run_id, tenant_id=principal.tenant_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id!r} not found")
    if run.get("initiator_id") != principal.user_id:
        raise HTTPException(status_code=403, detail="only the initiator (or admin) may resolve review")
    try:
        await store.resolve_review(run_id, node_id=payload.node_id, action=payload.action, actor_id=principal.user_id)
    except RunStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    driver = await _driver(principal)
    if payload.action == "skip":
        try:
            final = await driver.resume(run_id, runner=effective_runner(), tenant_id=principal.tenant_id)
        except (ApprovalError, RunStoreError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ApiResponse(data=_run_view(final))
    refreshed = await store.get_run(run_id)
    return ApiResponse(data=_run_view(refreshed or run))


@router.post("/recovery-sweep", response_model=ApiResponse)
async def recovery_sweep(
    principal: ApiPrincipal = Depends(require_end_user_principal),
) -> ApiResponse:
    driver = RunDriver(_store(), approval_runtime=_approval_runtime)
    summary = await driver.recovery_sweep()
    return ApiResponse(data=summary)


async def startup_recovery() -> None:
    """启动即扫一次：重启后超时判定与中断标记不丢（FR-005/FR-006）。"""
    db = get_db()
    if db is None:
        return
    try:
        driver = RunDriver(RunStore(db), approval_runtime=_approval_runtime)
        await driver.recovery_sweep()
    except Exception:  # noqa: BLE001 - 启动扫描失败不阻断服务，定时器会再扫
        pass


async def periodic_recovery_sweep() -> dict[str, Any] | None:
    """常驻循环入口：与 ``startup_recovery`` 同一扫描体，但**异常上抛**。

    调用方（main.py 的 60s 循环）负责记录失败——扫描静默失败会让
    「超时 fail-closed」退化为不可观测的空转（FR-006）。db 未就绪返回
    ``None``（与端点层 503 口径不同：循环里重试下一轮即可，不该崩）。
    """
    db = get_db()
    if db is None:
        return None
    driver = RunDriver(RunStore(db), approval_runtime=_approval_runtime)
    return await driver.recovery_sweep()