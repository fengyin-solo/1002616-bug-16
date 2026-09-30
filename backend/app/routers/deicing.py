"""除冰作业接口：维护除冰任务，覆盖登记、安排除冰、完成除冰、跳过作业与用量补录。

所有写接口都要求带操作人（请求头 X-Operator 或 values.operator），
服务层先按权限范围表比对区域/班组/岗位，越权时在响应里写明缺哪个权限并挡住。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.deicing import RuleViolation
from app.services.deicing import DeicingService
from app.services.deicing_scope import REGION_TEAMS, list_scopes

router = APIRouter(prefix="/api/deicing", tags=["除冰作业"])

service = DeicingService()

LIST_FIELDS = ["除冰编号", "对应航班", "除冰液类型", "喷洒量", "作业车辆", "作业人员", "作业区域", "作业班组", "经办人", "末次改动人", "除冰状态"]
STATUSES = ["待除冰", "除冰中", "已完成", "已跳过"]


def _operator(payload: EntryPayload, x_operator: str | None) -> str | None:
    """操作人取值：请求头优先，回落提交体里的 operator。"""
    return x_operator or payload.values.get("operator")


def _denied(exc: RuleViolation) -> ActionResult:
    missing = [exc.missing_permission] if exc.missing_permission else []
    return ActionResult(ok=False, message=exc.message, code=exc.code, missing_permissions=missing)


@router.get("/scope")
def get_scope() -> dict[str, Any]:
    """除冰作业可用范围表：按作业区域划分的人员、班组、岗位与权限点。"""
    return {
        "regions": [{"region": region, "team": team} for region, team in REGION_TEAMS.items()],
        "operators": list_scopes(),
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按除冰编号检索"),
    status: str | None = Query(default=None, description="待除冰、除冰中、已完成、已跳过"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按除冰编号与状态过滤除冰作业列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出除冰作业清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "deicing", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条除冰任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"除冰任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload, x_operator: str | None = Header(default=None)) -> ActionResult:
    """登记一条除冰任务；缺字段、越权、重复登记都会说明原因而不是静默丢弃。"""
    try:
        entry, missing = service.create_entry(payload.values, _operator(payload, x_operator))
    except RuleViolation as exc:
        return _denied(exc)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}", code="rule")
    return ActionResult(ok=True, message="除冰任务已登记", entry=entry)


@router.patch("/{entry_id}/fields", response_model=ActionResult)
def update_fields(
    entry_id: int,
    payload: EntryPayload,
    x_operator: str | None = Header(default=None),
) -> ActionResult:
    """补录喷洒量、除冰液类型；只读岗位与跨班组提交会被拦下。"""
    try:
        entry, message = service.update_fields(
            entry_id,
            payload.values,
            _operator(payload, x_operator),
            payload.values.get("version"),
        )
    except RuleViolation as exc:
        return _denied(exc)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int,
    payload: EntryPayload,
    x_operator: str | None = Header(default=None),
) -> ActionResult:
    """对单条任务执行安排除冰、完成除冰、跳过作业；越权/并发/终态都会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    try:
        entry, message = service.run_action(
            entry_id,
            action,
            _operator(payload, x_operator),
            payload.values.get("version"),
        )
    except RuleViolation as exc:
        return _denied(exc)
    return ActionResult(ok=True, message=message, entry=entry)
