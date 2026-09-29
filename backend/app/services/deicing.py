"""除冰作业业务规则：状态流转、字段校验与权限口径都收在这里。

权限模型收成一张按作业区域划分的可用范围表（AREA_SCOPE）：
提交任何改动前先比对操作人所在的区域与班组，越权一律挡住并在报文里写明缺哪个权限。
"""
from __future__ import annotations

import threading
from typing import Any

from app.store import store

MODULE = "deicing"
REQUIRED_FIELDS = ["除冰编号", "对应航班", "除冰液类型", "作业区域"]
STATUS_ORDER = ["待除冰", "除冰中", "已完成", "已跳过"]
TERMINAL_STATUSES = {"已完成", "已跳过"}

# 状态机：动作 -> (允许的前置状态, 目标状态)。终态不再接受任何动作，跳过的作业不能二次登记。
ACTION_RULES = {
    "安排除冰": ({"待除冰"}, "除冰中"),
    "开始除冰": ({"待除冰"}, "除冰中"),
    "完成除冰": ({"除冰中"}, "已完成"),
    "跳过除冰": ({"待除冰", "除冰中"}, "已跳过"),
}
NEGATIVE_ACTIONS = {"跳过除冰"}

# 允许手工改动的字段；除冰编号、对应航班、作业区域登记后不再改，避免账目对不上。
EDITABLE_FIELDS = ["除冰液类型", "喷洒量", "作业车辆", "作业人员"]
# 只读岗位碰不得的字段
READONLY_LOCKED_FIELDS = ["喷洒量", "除冰液类型"]

# 可用范围表：作业区域 -> 允许在该区域作业的班组
AREA_SCOPE = {
    "东区机坪": ["除冰一班"],
    "西区机坪": ["除冰二班"],
    "北区机坪": ["除冰一班", "除冰二班"],
}

# 操作人台账：姓名 -> 班组 / 岗位 / 所在区域
OPERATORS = {
    "王冰": {"班组": "除冰一班", "岗位": "正式工", "区域": "东区机坪"},
    "李霜": {"班组": "除冰一班", "岗位": "临时工", "区域": "东区机坪"},
    "钱晴": {"班组": "除冰一班", "岗位": "正式工", "区域": "北区机坪"},
    "赵雪": {"班组": "除冰二班", "岗位": "正式工", "区域": "西区机坪"},
    "孙露": {"班组": "除冰二班", "岗位": "正式工", "区域": "北区机坪"},
    "周览": {"班组": "除冰一班", "岗位": "只读", "区域": "东区机坪"},
}

# 岗位可执行的动作：临时工不能点完成，只读岗位只能看
ROLE_ACTIONS = {
    "正式工": {"登记除冰", "安排除冰", "开始除冰", "完成除冰", "跳过除冰", "改动记录"},
    "临时工": {"登记除冰", "安排除冰", "开始除冰", "跳过除冰", "改动记录"},
    "只读": set(),
}


class DeicingService:
    def __init__(self) -> None:
        # 内存仓库没有数据库事务，用锁把"校验+写入"收成原子操作，
        # 避免两个班组同时提交时各自校验通过、账上却互相覆盖。
        self._lock = threading.Lock()

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

    def permission_table(self) -> dict[str, Any]:
        """可用范围表与操作人台账，前端据此渲染权限说明与操作人选择。"""
        return {
            "areas": [{"作业区域": area, "可用班组": list(crews)} for area, crews in AREA_SCOPE.items()],
            "operators": [{"姓名": name, **info} for name, info in OPERATORS.items()],
        }

    def _check_operator(
        self,
        operator: str,
        area: str | None,
        action: str | None,
    ) -> tuple[dict[str, str] | None, str]:
        """比对操作人所在的区域与班组；越权时写明缺哪个权限。"""
        if not operator:
            return None, "缺少操作人：提交前请先选择当班操作人"
        info = OPERATORS.get(operator)
        if info is None:
            return None, f"缺少「登记与作业」权限：操作人「{operator}」不在除冰作业台账内"
        if action is not None and action not in ROLE_ACTIONS.get(info["岗位"], set()):
            return None, f"缺少「{action}」权限：岗位「{info['岗位']}」不可执行该动作"
        if area is not None:
            if area not in AREA_SCOPE:
                return None, f"作业区域「{area}」不在可用范围表内，任何班组都无权作业"
            if info["区域"] != area:
                return None, f"缺少「{area}」作业权限：{operator} 的可用范围是「{info['区域']}」"
            if info["班组"] not in AREA_SCOPE[area]:
                crews = "、".join(AREA_SCOPE[area])
                return None, f"缺少「{area}」作业权限：班组「{info['班组']}」不在可用范围（{crews}）内"
        return info, ""

    @staticmethod
    def _check_version(entry: dict[str, Any], values: dict[str, Any]) -> str:
        """乐观锁：提交人看到的版本与账上不一致时挡住，避免两边都提示成功却互相覆盖。"""
        client_version = values.get("版本号")
        if client_version is None:
            return ""
        try:
            stale = int(client_version) != int(entry.get("版本号", 0))
        except (TypeError, ValueError):
            stale = True
        if stale:
            return f"记录已被「{entry.get('末次改动人', '他人')}」改动，请刷新后重试"
        return ""

    @staticmethod
    def _touch(entry: dict[str, Any], operator: str) -> None:
        """保留原先的经办人，只更新末次改动人，交接回来仍能查到谁最后动过。"""
        entry.setdefault("经办人", operator)
        entry["末次改动人"] = operator
        entry["版本号"] = int(entry.get("版本号", 0)) + 1

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
        """登记除冰任务。重复登记只认头一次：同一编号或同一航班已有任务时返回首次登记。"""
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}", False
        operator = str(values.get("operator") or "").strip()
        area = str(values.get("作业区域") or "").strip()
        with self._lock:
            info, error = self._check_operator(operator, area, "登记除冰")
            if error:
                return None, error, False
            rows = store.rows(MODULE)
            code = str(values["除冰编号"]).strip()
            flight = str(values["对应航班"]).strip()
            for row in rows:
                if str(row.get("除冰编号")) == code or str(row.get("对应航班")) == flight:
                    return row, (
                        f"重复登记只认头一次：{row.get('除冰编号')}（{row.get('对应航班')}）"
                        f"已由「{row.get('经办人', '—')}」登记"
                    ), False
            entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            entry.update({field: str(values.get(field) or "").strip() for field in REQUIRED_FIELDS})
            entry["喷洒量"] = str(values.get("喷洒量") or "").strip()
            entry["作业车辆"] = str(values.get("作业车辆") or "").strip()
            entry["作业人员"] = str(values.get("作业人员") or "").strip() or operator
            entry["作业班组"] = info["班组"]
            entry["status"] = STATUS_ORDER[0]
            entry["除冰状态"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            entry["经办人"] = operator
            entry["末次改动人"] = operator
            entry["版本号"] = 1
            rows.append(entry)
            return entry, "除冰任务已登记", True

    def update_entry(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """改动喷洒量、除冰液类型等字段：只读本班组记录，只读岗位碰不得喷洒量与除冰液类型。"""
        operator = str(values.get("operator") or "").strip()
        with self._lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"除冰任务 {entry_id} 不存在或已归档"
            if entry.get("status") in TERMINAL_STATUSES:
                return None, f"除冰任务已{entry.get('status')}，账目封存不能再改动"
            info, error = self._check_operator(operator, str(entry.get("作业区域") or ""), None)
            if error:
                return None, error
            submitted = {field: str(values[field]).strip() for field in EDITABLE_FIELDS if field in values}
            if not submitted:
                return None, f"没有可改动的字段，仅支持：{'、'.join(EDITABLE_FIELDS)}"
            if info["岗位"] == "只读":
                locked = [field for field in READONLY_LOCKED_FIELDS if field in submitted]
                if locked:
                    return None, f"缺少「{'、'.join(locked)}」改动权限：只读岗位不能改动喷洒量与除冰液类型"
            _, error = self._check_operator(operator, None, "改动记录")
            if error:
                return None, error
            if info["班组"] != entry.get("作业班组"):
                return None, f"缺少「改动记录」权限：只能改动本班组（{entry.get('作业班组')}）的记录"
            error = self._check_version(entry, values)
            if error:
                return None, error
            entry.update(submitted)
            self._touch(entry, operator)
            return entry, "除冰记录已改动"

    def run_action(self, entry_id: int, action: str, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        operator = str(values.get("operator") or "").strip()
        with self._lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"除冰任务 {entry_id} 不存在或已归档"
            if action not in ACTION_RULES:
                return None, f"动作「{action}」不属于除冰作业可执行范围"
            info, error = self._check_operator(operator, str(entry.get("作业区域") or ""), action)
            if error:
                return None, error
            if action == "完成除冰" and info["班组"] != entry.get("作业班组"):
                return None, f"缺少「完成除冰」权限：完成除冰只能由本班组（{entry.get('作业班组')}）确认"
            if entry.get("status") in TERMINAL_STATUSES:
                return None, f"除冰任务已{entry.get('status')}，不能再执行「{action}」"
            allowed_from, target = ACTION_RULES[action]
            if entry.get("status") not in allowed_from:
                return None, f"当前状态「{entry.get('status')}」不允许执行「{action}」"
            error = self._check_version(entry, values)
            if error:
                return None, error
            if action in ("安排除冰", "开始除冰"):
                if not entry.get("作业班组"):
                    entry["作业班组"] = info["班组"]
                if not entry.get("作业人员"):
                    entry["作业人员"] = operator
            if action == "完成除冰":
                # 完成时顺带登记本轮喷洒量与除冰液类型（提交里带了才覆盖）
                for field in ("喷洒量", "除冰液类型"):
                    if str(values.get(field) or "").strip():
                        entry[field] = str(values[field]).strip()
            if target == "已跳过":
                # 取消的作业清掉上一轮喷洒量，不残留旧账
                entry["喷洒量"] = ""
            entry["status"] = target
            entry["除冰状态"] = target
            entry["pending"] = target not in TERMINAL_STATUSES
            entry["abnormal"] = action in NEGATIVE_ACTIONS
            self._touch(entry, operator)
            return entry, f"除冰任务已{action}"
