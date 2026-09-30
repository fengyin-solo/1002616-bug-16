import { defineStore } from 'pinia'

/** 除冰权限范围表里的一条操作人信息（与后端 /api/deicing/scope 对齐）。 */
export interface OperatorScope {
  name: string
  role: string
  team: string | null
  regions: string[]
  permissions: string[]
}

export const useSessionStore = defineStore('session', {
  state: () => ({
    operator: '王建国',
    role: '班组长',
    team: '甲班' as string | null,
    regions: ['A区除冰坪'] as string[],
    permissions: [] as string[],
    shiftLabel: '白班 08:00-20:00',
    scope: '机场地面保障管理平台',
  }),
  getters: {
    canOperate: (state) => state.operator.length > 0,
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    /** 切换当前操作人：权限、班组、区域全部以后端范围表返回的为准。 */
    setOperator(scope: OperatorScope) {
      this.operator = scope.name
      this.role = scope.role
      this.team = scope.team
      this.regions = scope.regions
      this.permissions = scope.permissions
    },
    hasPermission(perm: string): boolean {
      return this.permissions.includes(perm)
    },
    canReachRegion(region: string): boolean {
      return this.regions.includes(region)
    },
  },
})
