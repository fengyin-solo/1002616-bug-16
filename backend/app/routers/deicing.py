"""除冰作业接口：维护除冰任务，覆盖安排除冰、开始除冰、完成除冰等动作。

权限判断全部在 service 层：路由只负责把操作人、版本号等上下文原样透传。
注意 /export 与 /permissions 必须声明在 /{entry_id} 之前，否则会被路径参数吃掉。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.deicing import DeicingService

router = APIRouter(prefix="/api/deicing", tags=["除冰作业"])

service = DeicingService()

LIST_FIELDS = ["除冰编号", "对应航班", "除冰液类型", "喷洒量", "作业车辆", "作业人员", "作业区域", "作业班组", "经办人", "末次改动人", "除冰状态"]
STATUSES = ["待除冰", "除冰中", "已完成", "已跳过"]


@router.get("/permissions")
def get_permissions() -> dict[str, Any]:
    """按作业区域划分的可用范围表与操作人台账，前端据此提示谁能干什么。"""
    return service.permission_table()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出除冰作业清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "deicing", "total": total, "items": items}


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


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条除冰任务明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"除冰任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条除冰任务。重复登记只认头一次，越权登记会写明缺哪个权限。"""
    entry, message, created = service.create_entry(payload.values)
    if not created:
        return ActionResult(ok=False, message=message, entry=entry)
    return ActionResult(ok=True, message=message, entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult:
    """改动喷洒量、除冰液类型等字段；只读岗位与跨班组改动会被拦下并说明原因。"""
    entry, message = service.update_entry(entry_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条除冰任务执行安排除冰、开始除冰、完成除冰、跳过除冰；越权或状态不符会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
