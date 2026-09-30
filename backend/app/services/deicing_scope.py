"""除冰作业权限范围表。

权限按「作业区域 → 班组 → 岗位」收成一张可用范围表（SCOPE_TABLE）：
- 区域与班组是绑定的：每个除冰区域固定由一个除冰班组负责，跨班组改不到别组的用量；
- 岗位决定在该区域内能做什么：操作岗可安排/确认，只读岗只能看，临时岗没有任何写权限。

任何提交都先比对操作人所在的区域与班组，越权时给出缺少的具体权限，由调用方挡在提交行上。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 权限点：越权提示里直接引用这些名字，方便在提交行上写明“缺哪个权限”。
PERM_RECORD = "除冰:登记"
PERM_ARRANGE = "除冰:安排"
PERM_SPRAY = "除冰:改用量"      # 改动喷洒量、除冰液类型
PERM_CONFIRM = "除冰:完成确认"
PERM_SKIP = "除冰:跳过"

READONLY_ROLE = "只读"
TEMP_ROLE = "临时"
OPERATOR_ROLE = "操作"
LEADER_ROLE = "班组长"

# 区域 → 负责班组。区域权限表里出现的区域都必须在这里有归属。
REGION_TEAMS: dict[str, str] = {
    "A区除冰坪": "甲班",
    "B区除冰坪": "乙班",
    "C区除冰坪": "丙班",
}

# 各岗位在其可用区域内拥有的权限点。
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    LEADER_ROLE: frozenset({PERM_RECORD, PERM_ARRANGE, PERM_SPRAY, PERM_CONFIRM, PERM_SKIP}),
    OPERATOR_ROLE: frozenset({PERM_RECORD, PERM_ARRANGE, PERM_SPRAY, PERM_SKIP}),
    # 只读岗位：只有读，不挂任何写权限，喷洒量与除冰液类型一律改不动。
    READONLY_ROLE: frozenset(),
    # 临时人员：名义上能进场，但权限表不给任何写权限，点“完成”会被挡下。
    TEMP_ROLE: frozenset(),
}


@dataclass(frozen=True)
class OperatorScope:
    """操作人在权限范围表中的一条可用范围。"""

    name: str
    role: str
    team: str | None
    regions: frozenset[str]

    @property
    def permissions(self) -> frozenset[str]:
        return ROLE_PERMISSIONS.get(self.role, frozenset())

    def has(self, perm: str) -> bool:
        return perm in self.permissions

    def can_reach_region(self, region: str) -> bool:
        """区域是否落在该操作人的可用范围内（表里没有的区域一律视为不可达）。"""
        return region in REGION_TEAMS and region in self.regions

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "team": self.team,
            "regions": sorted(self.regions),
            "permissions": sorted(self.permissions),
        }


# 可用范围表：一行就是“谁、在哪个区域、属于哪个班组、能干什么”。
# 只读岗位与临时人员的班组/区域仍登记在册（看得到现场），但没有任何写权限。
SCOPE_TABLE: dict[str, OperatorScope] = {
    "王建国": OperatorScope("王建国", LEADER_ROLE, "甲班", frozenset({"A区除冰坪"})),
    "李雪": OperatorScope("李雪", OPERATOR_ROLE, "甲班", frozenset({"A区除冰坪"})),
    "陈志强": OperatorScope("陈志强", LEADER_ROLE, "乙班", frozenset({"B区除冰坪"})),
    "赵敏": OperatorScope("赵敏", OPERATOR_ROLE, "乙班", frozenset({"B区除冰坪"})),
    "孙伟": OperatorScope("孙伟", LEADER_ROLE, "丙班", frozenset({"C区除冰坪"})),
    "周婷": OperatorScope("周婷", READONLY_ROLE, "甲班", frozenset({"A区除冰坪"})),
    "吴磊": OperatorScope("吴磊", READONLY_ROLE, "乙班", frozenset({"B区除冰坪"})),
    "临时人员": OperatorScope("临时人员", TEMP_ROLE, None, frozenset()),
}

# 默认值班人：未带操作人时按此人处理，保证列表页直接能演示。
DEFAULT_OPERATOR = "王建国"


def get_scope(operator: str | None) -> OperatorScope | None:
    """按姓名查可用范围；查不到说明该人不在权限表里，视为无任何权限。"""
    if not operator:
        return None
    return SCOPE_TABLE.get(str(operator).strip())


def resolve_scope(operator: str | None) -> OperatorScope:
    """供写操作解析操作人：空值回落到默认值班人，查不到则给一条零权限范围。"""
    scope = get_scope(operator)
    if scope is not None:
        return scope
    name = (operator or "").strip()
    if not name:
        # 未带操作人（如直接调接口/老页面）按默认值班人处理，保证演示链路可用。
        return SCOPE_TABLE[DEFAULT_OPERATOR]
    return OperatorScope(name, TEMP_ROLE, None, frozenset())


def list_scopes() -> list[dict[str, Any]]:
    """整张可用范围表，供前端按当前操作人渲染按钮与提交行提示。"""
    return [scope.describe() for scope in SCOPE_TABLE.values()]


def check_region_team(scope: OperatorScope, region: str, team: str | None) -> str | None:
    """比对操作人所在区域与班组。

    返回 None 表示通过；否则返回一句可读的越权说明。
    - 区域不在可用范围 → 缺该区域的作业权限；
    - 区域到了但班组对不上（跨班组）→ 明确点出归属班组。
    """
    if not scope.can_reach_region(region):
        return f"区域「{region}」不在 {scope.name} 的可用作业范围内"
    owner_team = REGION_TEAMS.get(region)
    if team and owner_team and team != owner_team:
        return f"区域「{region}」归属{owner_team}，班组「{team}」不能跨区作业"
    if scope.team is not None and owner_team and scope.team != owner_team:
        return f"区域「{region}」归属{owner_team}，{scope.name} 所在的{scope.team}不能跨班组操作"
    return None


def missing_permission_message(scope: OperatorScope, perm: str) -> str:
    """生成“缺哪个权限”的统一提示，挂在提交行上。"""
    return f"{scope.name}（{scope.role}岗）缺少权限「{perm}」，该提交已被拦截"
