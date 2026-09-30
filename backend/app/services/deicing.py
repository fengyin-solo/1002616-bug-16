"""除冰作业业务规则：状态流转、字段校验、权限比对与并发口径都收在这里。

相对早期版本，这里补齐了几件事：
- 状态机按真实流程走：待除冰 →（安排除冰）→ 除冰中 →（完成除冰）→ 已完成；
  待除冰/除冰中 →（跳过作业）→ 已跳过；跳过即清掉上一轮喷洒量；
- 除冰编号全表唯一，重复登记只认头一次，已跳过的作业也不能拿来二次登记；
- 已完成 / 已跳过是终态，终态记录拒绝任何再操作；
- 每条记录保留原经办人（经办人/作业班组），另记末次改动人，交接回来仍可追溯；
- 提交带版本号做乐观并发：一架航班被两边同时操作时，只一边成功，另一边拿到冲突提示；
- 喷洒量、除冰液类型属于受控字段，只读岗位改不动，完成确认只能本班组做。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

from .deicing_scope import (
    PERM_ARRANGE,
    PERM_CONFIRM,
    PERM_RECORD,
    PERM_SKIP,
    PERM_SPRAY,
    REGION_TEAMS,
    check_region_team,
    missing_permission_message,
    resolve_scope,
)

MODULE = "deicing"
REQUIRED_FIELDS = ["除冰编号", "对应航班", "除冰液类型", "作业区域", "作业班组"]
# 允许在作业过程中补录/修改的受控字段（喷洒量、除冰液类型）。
EDITABLE_FIELDS = ["喷洒量", "除冰液类型"]
FLUID_TYPES = ["I型除冰液", "II型除冰液", "IV型除冰液"]

STATUS_PENDING = "待除冰"
STATUS_RUNNING = "除冰中"
STATUS_DONE = "已完成"
STATUS_SKIPPED = "已跳过"
STATUS_ORDER = [STATUS_PENDING, STATUS_RUNNING, STATUS_DONE, STATUS_SKIPPED]
TERMINAL_STATUSES = {STATUS_DONE, STATUS_SKIPPED}

# 动作 → 目标状态。状态推进按现场顺序走，不再出现“完成=跳过”这种错配。
ACTION_RULES = {
    "安排除冰": STATUS_RUNNING,
    "完成除冰": STATUS_DONE,
    "跳过作业": STATUS_SKIPPED,
}
ACTION_PERMISSIONS = {
    "安排除冰": PERM_ARRANGE,
    "完成除冰": PERM_CONFIRM,
    "跳过作业": PERM_SKIP,
}
# 允许从前置状态发起动作；完成除冰必须先安排，跳过只在作业闭环前允许。
ACTION_FROM_STATUSES = {
    "安排除冰": {STATUS_PENDING},
    "完成除冰": {STATUS_RUNNING},
    "跳过作业": {STATUS_PENDING, STATUS_RUNNING},
}

# 审计与并发字段（不进业务列，供详情与交接追溯使用）。
AUDIT_FIELDS = ["经办人", "作业班组", "末次改动人", "末次改动时间", "version"]


class RuleViolation(Exception):
    """业务规则被拦截；code 供前端区分“越权/冲突/重复/状态”，message 直接展示。"""

    def __init__(self, message: str, *, code: str = "rule", missing_permission: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.missing_permission = missing_permission


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class DeicingService:
    # ---------------------------------------------------------------- 读取
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("除冰编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    # ------------------------------------------------------------ 工具方法
    def _find_by_code(self, code: str) -> dict[str, Any] | None:
        code = code.strip()
        for row in store.rows(MODULE):
            if str(row.get("除冰编号", "")).strip() == code:
                return row
        return None

    def _check_version(self, entry: dict[str, Any], version: Any) -> None:
        """乐观并发：提交版本与当前版本不一致即冲突，两边只允许一边落账。"""
        if version is None or str(version) == "":
            return  # 老页面/演示脚本未带版本时不阻塞主流程
        try:
            submitted = int(version)
        except (TypeError, ValueError):
            raise RuleViolation("提交的版本号格式不正确，请刷新后重试", code="conflict")
        if submitted != int(entry.get("version", 1)):
            raise RuleViolation(
                f"该作业已被「{entry.get('末次改动人', '其他班组')}」改动过（当前版本 {entry.get('version', 1)}），"
                "请刷新获取最新记录后再提交，本次未覆盖任何数据",
                code="conflict",
            )

    def _touch(self, entry: dict[str, Any], operator: str) -> None:
        """记一笔末次改动并推进版本；原经办人始终不动。"""
        entry["末次改动人"] = operator
        entry["末次改动时间"] = _now()
        entry["version"] = int(entry.get("version", 1)) + 1

    def _guard_action_scope(self, scope: Any, action: str, entry: dict[str, Any]) -> None:
        """动作类提交的区域 + 班组 + 岗位三道比对。"""
        perm = ACTION_PERMISSIONS[action]
        region = str(entry.get("作业区域", "")).strip()
        team = str(entry.get("作业班组", "")).strip()
        # check_region_team 同时核对：记录班组是否为区域归属班组、操作人班组是否与之一致。
        region_error = check_region_team(scope, region, team)
        if region_error:
            raise RuleViolation(f"{region_error}；且缺少权限「{perm}」", code="forbidden", missing_permission=perm)
        if not scope.has(perm):
            raise RuleViolation(missing_permission_message(scope, perm), code="forbidden", missing_permission=perm)

    # ---------------------------------------------------------------- 登记
    def create_entry(self, values: dict[str, Any], operator: str | None = None) -> tuple[dict[str, Any] | None, list[str]]:
        scope = resolve_scope(operator)
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing

        code = str(values["除冰编号"]).strip()
        region = str(values["作业区域"]).strip()
        team = str(values["作业班组"]).strip()

        # 区域与班组先比对：区域要在可用范围内，且必须是该区域的归属班组。
        region_error = check_region_team(scope, region, team)
        if region_error:
            raise RuleViolation(f"{region_error}；且缺少权限「{PERM_RECORD}」",
                                code="forbidden", missing_permission=PERM_RECORD)
        if not scope.has(PERM_RECORD):
            raise RuleViolation(missing_permission_message(scope, PERM_RECORD),
                                code="forbidden", missing_permission=PERM_RECORD)

        # 重复登记只认头一次：编号已存在（含已跳过）一律拒绝，跳过的作业不能二次登记。
        existed = self._find_by_code(code)
        if existed is not None:
            raise RuleViolation(
                f"除冰编号「{code}」已于 {existed.get('末次改动时间', '此前')} 登记"
                f"（当前状态：{existed.get('status')}，经办人：{existed.get('经办人')}），重复登记已被拦截",
                code="duplicate",
            )

        fluid = str(values["除冰液类型"]).strip()
        if fluid not in FLUID_TYPES:
            raise RuleViolation(f"除冰液类型「{fluid}」不在允许范围：{'、'.join(FLUID_TYPES)}")

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({
            "除冰编号": code,
            "对应航班": str(values["对应航班"]).strip(),
            "除冰液类型": fluid,
            "喷洒量": "",  # 登记时尚未喷洒，避免把上一轮用量带进新作业
            "作业车辆": str(values.get("作业车辆") or "").strip(),
            "作业人员": str(values.get("作业人员") or scope.name).strip(),
            "作业区域": region,
            "作业班组": team,
            "除冰状态": STATUS_PENDING,
            # 原经办人：首次登记即固定，后续任何改动都不覆盖。
            "经办人": scope.name,
            "末次改动人": scope.name,
            "末次改动时间": _now(),
            "version": 1,
        })
        entry["status"] = STATUS_PENDING
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    # ------------------------------------------------------------ 字段修改
    def update_fields(
        self,
        entry_id: int,
        values: dict[str, Any],
        operator: str | None = None,
        version: Any = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """补录/修改喷洒量与除冰液类型。只读岗位、跨班组一律挡下。"""
        scope = resolve_scope(operator)
        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise RuleViolation(f"除冰任务 {entry_id} 不存在或已归档", code="not_found")

        region = str(entry.get("作业区域", "")).strip()
        team = str(entry.get("作业班组", "")).strip()
        region_error = check_region_team(scope, region, team)
        if region_error:
            raise RuleViolation(f"{region_error}；且缺少权限「{PERM_SPRAY}」",
                                code="forbidden", missing_permission=PERM_SPRAY)
        if not scope.has(PERM_SPRAY):
            raise RuleViolation(missing_permission_message(scope, PERM_SPRAY),
                                code="forbidden", missing_permission=PERM_SPRAY)

        if entry.get("status") in TERMINAL_STATUSES:
            # 旧版本撞上已闭环记录时先报冲突，让落败方刷新，而不是笼统地说“不能改”。
            self._check_version(entry, version)
            raise RuleViolation(f"作业已{entry.get('status')}，喷洒量与除冰液类型不允许再改", code="state")
        self._check_version(entry, version)

        changes: list[str] = []
        new_fluid = values.get("除冰液类型")
        if new_fluid is not None and str(new_fluid).strip():
            fluid = str(new_fluid).strip()
            if fluid not in FLUID_TYPES:
                raise RuleViolation(f"除冰液类型「{fluid}」不在允许范围：{'、'.join(FLUID_TYPES)}")
            if fluid != entry.get("除冰液类型"):
                changes.append(f"除冰液类型 {entry.get('除冰液类型') or '—'} → {fluid}")
                entry["除冰液类型"] = fluid

        new_amount = values.get("喷洒量")
        if new_fluid is None or new_amount is not None:
            amount_text = str(new_amount if new_amount is not None else "").strip()
            if amount_text:
                try:
                    amount = float(amount_text)
                except ValueError:
                    raise RuleViolation("喷洒量必须是非负数字（单位：升）")
                if amount < 0:
                    raise RuleViolation("喷洒量不能为负数")
                amount_text = str(int(amount)) if amount.is_integer() else str(amount)
            old_amount = str(entry.get("喷洒量") or "")
            if amount_text != old_amount:
                changes.append(f"喷洒量 {old_amount or '—'} → {amount_text or '—'}")
                entry["喷洒量"] = amount_text

        if not changes:
            return entry, "提交内容与现状一致，未做改动"
        self._touch(entry, scope.name)
        return entry, f"已更新{'；'.join(changes)}（末次改动人：{scope.name}）"

    # ---------------------------------------------------------------- 动作
    def run_action(
        self,
        entry_id: int,
        action: str,
        operator: str | None = None,
        version: Any = None,
    ) -> tuple[dict[str, Any] | None, str]:
        scope = resolve_scope(operator)
        entry = store.find(MODULE, entry_id)
        if entry is None:
            raise RuleViolation(f"除冰任务 {entry_id} 不存在或已归档", code="not_found")
        if action not in ACTION_RULES:
            raise RuleViolation(f"动作「{action}」不属于除冰作业可执行范围")

        # 终态记录一刀切：已完成不能重复确认，已跳过不能二次登记/再操作。
        if entry.get("status") in TERMINAL_STATUSES:
            # 带着旧版本撞终态，说明是两边同时提交的落败方：给冲突提示而不是笼统的终态提示。
            self._check_version(entry, version)
            raise RuleViolation(
                f"该作业当前为「{entry.get('status')}」，属于终态，不允许再执行「{action}」",
                code="state",
            )
        if entry.get("status") not in ACTION_FROM_STATUSES[action]:
            raise RuleViolation(
                f"作业处于「{entry.get('status')}」，不能直接{action}；请按 待除冰 → 除冰中 → 已完成 的顺序流转",
                code="state",
            )

        # 完成除冰只能由本班组确认：区域 + 班组 + 权限点三道都过才放行。
        self._guard_action_scope(scope, action, entry)
        # 乐观并发：两边拿着同一版本同时提交时，先到的落账，后到的明确拿到冲突，
        # 不会再出现“两边界面都提示成功、账上却只留一条”。
        self._check_version(entry, version)

        target = ACTION_RULES[action]
        if action == "完成除冰":
            # 完成确认前喷洒量必须已登记，防止空账闭环。
            if not str(entry.get("喷洒量") or "").strip():
                raise RuleViolation("尚未登记喷洒量，不能完成除冰，请先补录用量")
        if action == "跳过作业":
            # 取消过的作业里不能残留上一轮喷洒量：跳过即清空，除冰液类型保留备查。
            entry["喷洒量"] = ""

        entry["status"] = target
        entry["除冰状态"] = target
        entry["pending"] = target not in TERMINAL_STATUSES
        entry["abnormal"] = target == STATUS_SKIPPED
        self._touch(entry, scope.name)
        return entry, f"除冰任务已{action}（{scope.name}，{scope.team or '无班组'}）"
