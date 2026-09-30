<template>
  <section class="page" data-module="deicing">
    <header class="page-head">
      <div>
        <h2>除冰作业管理</h2>
        <p class="page-desc">权限按作业区域收口：提交前比对操作人所在区域与班组，越权在提交行写明缺哪个权限；完成除冰只能本班组确认。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记除冰任务</button>
        <button class="btn" type="button" @click="exportRows">导出除冰作业清单</button>
      </div>
    </header>

    <!-- 当前操作人：姓名/岗位/班组/区域/权限全部来自后端可用范围表 -->
    <div class="operator-bar">
      <strong>当前操作人</strong>
      <select :value="session.operator" @change="switchOperator(($event.target as HTMLSelectElement).value)">
        <option v-for="op in operators" :key="op.name" :value="op.name">
          {{ op.name }}（{{ op.role }}岗{{ op.team ? ' · ' + op.team : ' · 无班组' }}）
        </option>
      </select>
      <div class="operator-badges">
        <span class="badge" :class="roleBadgeClass">{{ session.role }}岗</span>
        <span v-if="session.team" class="badge">{{ session.team }}</span>
        <span v-for="region in session.regions" :key="region" class="badge">{{ region }}</span>
        <span v-if="!session.regions.length" class="badge role-temp">无可用作业区域</span>
      </div>
      <span class="muted-text">权限：{{ session.permissions.length ? session.permissions.join('、') : '无（只读/临时不可提交）' }}</span>
    </div>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>除冰编号</span>
        <input v-model="keyword" placeholder="按除冰编号检索" />
      </label>
      <label class="filter-item">
        <span>除冰状态</span>
        <select v-model="statusFilter">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th style="width: 230px">可执行操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '除冰编号'">
              <button class="link" type="button" @click="openDetail(row)">{{ row[column] ?? '—' }}</button>
            </template>
            <template v-else-if="column === '除冰状态'">
              <span class="status-tag" :class="statusClass(String(row[column]))">{{ row[column] ?? '—' }}</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <div>
              <template v-for="action in rowActions(row)" :key="action.name">
                <button
                  class="link"
                  :class="{ danger: action.name === '跳过作业', disabled: !action.enabled }"
                  type="button"
                  :disabled="!action.enabled"
                  :title="action.reason"
                  @click="action.enabled && runAction(action.name, row)"
                >
                  {{ action.name }}
                </button>
              </template>
              <button class="link" type="button" @click="openDetail(row)">用量/详情</button>
              <div v-if="actionDeniedHint(row)" class="row-feedback error-text">{{ actionDeniedHint(row) }}</div>
              <div v-if="feedback[Number(row.id)]" class="row-feedback" :class="feedback[Number(row.id)].ok ? 'ok-text' : 'error-text'">
                {{ feedback[Number(row.id)].message }}
              </div>
            </div>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无除冰作业数据，可先登记除冰任务</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条除冰作业记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 登记弹窗 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal">
        <h3>登记除冰任务</h3>
        <div class="form-grid">
          <label>除冰编号</label>
          <input v-model="createForm.除冰编号" placeholder="如 DEIC-1008" />
          <label>对应航班</label>
          <input v-model="createForm.对应航班" placeholder="如 CA1831" />
          <label>除冰液类型</label>
          <select v-model="createForm.除冰液类型">
            <option value="" disabled>请选择</option>
            <option v-for="t in fluidTypes" :key="t" :value="t">{{ t }}</option>
          </select>
          <label>作业区域</label>
          <select v-model="createForm.作业区域">
            <option value="" disabled>请选择（区域决定归属班组）</option>
            <option v-for="r in regions" :key="r.region" :value="r.region">{{ r.region }}（{{ r.team }}）</option>
          </select>
          <label>作业班组</label>
          <input :value="teamOfRegion(createForm.作业区域)" readonly class="readonly-box" />
          <label>作业车辆</label>
          <input v-model="createForm.作业车辆" placeholder="如 除冰车A-07" />
        </div>
        <p v-if="createError" class="error-text" style="margin-top: 10px">{{ createError }}</p>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="createOpen = false">取消</button>
          <button class="btn primary" type="button" @click="submitCreate">提交登记</button>
        </div>
      </div>
    </div>

    <!-- 详情/用量弹窗：列表与详情共用同一份后端记录，经办人字段不会再对不上 -->
    <div v-if="detailRow" class="modal-mask" @click.self="closeDetail">
      <div class="modal">
        <h3>除冰任务明细 · {{ detailRow.除冰编号 }}</h3>
        <div class="form-grid">
          <label>对应航班</label><span>{{ detailRow.对应航班 }}</span>
          <label>除冰状态</label>
          <span><span class="status-tag" :class="statusClass(String(detailRow.status))">{{ detailRow.status }}</span></span>
          <label>作业区域</label><span>{{ detailRow.作业区域 }}（{{ detailRow.作业班组 }}）</span>
          <label>作业车辆/人员</label><span>{{ detailRow.作业车辆 || '—' }} / {{ detailRow.作业人员 || '—' }}</span>
          <label>除冰液类型</label>
          <input v-model="detailForm.除冰液类型" :disabled="!canEditSpray" />
          <label>喷洒量(升)</label>
          <input v-model="detailForm.喷洒量" :disabled="!canEditSpray" placeholder="仅本班组操作/班组长可改" />
          <label>经办人</label><span>{{ detailRow.经办人 }}（首次登记，始终保留）</span>
          <label>末次改动人</label><span>{{ detailRow.末次改动人 }} · {{ detailRow.末次改动时间 }}</span>
          <label>记录版本</label><span>v{{ detailRow.version }}（并发提交按版本比对，旧版本会被挡回）</span>
        </div>
        <p v-if="!canEditSpray" class="detail-note">
          当前操作人无「除冰:改用量」权限（只读岗或非本班组/跨区域），喷洒量与除冰液类型不可修改。
        </p>
        <p v-if="detailError" class="error-text" style="margin-top: 10px">{{ detailError }}</p>
        <p v-if="detailOk" class="ok-text" style="margin-top: 10px">{{ detailOk }}</p>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
          <button
            v-if="canEditSpray && !isTerminal(detailRow.status)"
            class="btn primary"
            type="button"
            @click="saveFields"
          >
            保存用量/液型
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request, setRequestOperator } from '@/api/client'
import { useSessionStore, type OperatorScope } from '@/stores/session'

type Row = Record<string, string | number | null>
interface ScopeRegion { region: string; team: string }
interface Feedback { ok: boolean; message: string }

const ENDPOINT = '/api/deicing'
const columns = ['除冰编号', '对应航班', '除冰液类型', '喷洒量', '作业区域', '作业班组', '经办人', '末次改动人', '除冰状态']
const statuses = ['待除冰', '除冰中', '已完成', '已跳过']
const fluidTypes = ['I型除冰液', 'II型除冰液', 'IV型除冰液']

const session = useSessionStore()
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const feedback = reactive<Record<number, Feedback>>({})

const operators = ref<OperatorScope[]>([])
const regions = ref<ScopeRegion[]>([])

const stats = computed(() => [
  { label: '待除冰航班', value: rows.value.filter((r) => r.status === '待除冰').length },
  { label: '除冰中航班', value: rows.value.filter((r) => r.status === '除冰中').length },
  { label: '已完成除冰', value: rows.value.filter((r) => r.status === '已完成').length },
  { label: '已跳过', value: rows.value.filter((r) => r.status === '已跳过').length },
])

const roleBadgeClass = computed(() => {
  if (session.role === '只读') return 'role-readonly'
  if (session.role === '临时') return 'role-temp'
  if (session.role === '班组长') return 'role-leader'
  return 'role-operator'
})

function statusClass(status: string) {
  return {
    待除冰: 'status-pending',
    除冰中: 'status-running',
    已完成: 'status-done',
    已跳过: 'status-skipped',
  }[status] ?? ''
}

function isTerminal(status: string | number | null) {
  return status === '已完成' || status === '已跳过'
}

function teamOfRegion(region: string) {
  return regions.value.find((r) => r.region === region)?.team ?? ''
}

// 按当前状态应出现的动作；每个动作带上能否提交与被挡原因，
// 越权时按钮置灰并在提交行写明缺哪个权限（后端仍会再拦一道）。
function rowActions(row: Row) {
  const all = [
    { name: '安排除冰', perm: '除冰:安排', from: ['待除冰'] },
    { name: '完成除冰', perm: '除冰:完成确认', from: ['除冰中'] },
    { name: '跳过作业', perm: '除冰:跳过', from: ['待除冰', '除冰中'] },
  ]
  const currentStatus = String(row.status)
  return all
    .filter((a) => a.from.includes(currentStatus))
    .map((a) => {
      let reason = ''
      if (!session.regions.includes(String(row.作业区域))) {
        reason = `${session.operator} 的可用区域不含${row.作业区域}，缺少权限「${a.perm}」`
      } else if (session.team && row.作业班组 && session.team !== row.作业班组) {
        reason = `该作业归属${row.作业班组}，完成除冰只能本班组确认，缺少权限「${a.perm}」`
      } else if (!session.hasPermission(a.perm)) {
        reason = `${session.operator}（${session.role}岗）缺少权限「${a.perm}」`
      }
      return { ...a, enabled: !reason, reason }
    })
}

// 终态以外的行若当前一个动作都交不出去，在提交行汇总说明。
function actionDeniedHint(row: Row) {
  if (isTerminal(row.status)) return ''
  const blocked = rowActions(row).filter((a) => !a.enabled)
  if (!blocked.length) return ''
  const reasons = Array.from(new Set(blocked.map((a) => a.reason)))
  return `当前操作人对该行无提交权：${reasons.join('；')}`
}

const canEditSpray = computed(() => {
  const row = detailRow.value
  if (!row) return false
  if (!session.hasPermission('除冰:改用量')) return false
  if (!session.regions.includes(String(row.作业区域))) return false
  if (session.team && row.作业班组 && session.team !== row.作业班组) return false
  return true
})
async function loadScope(selectName?: string) {
  const response = await request(`${ENDPOINT}/scope`)
  if (!response.ok) throw new Error('权限范围表读取失败')
  const payload = await response.json()
  operators.value = payload.operators ?? []
  regions.value = payload.regions ?? []
  const name = selectName ?? session.operator
  const target = operators.value.find((o) => o.name === name) ?? operators.value[0]
  if (target) session.setOperator(target)
  setRequestOperator(session.operator)
}

function switchOperator(name: string) {
  const target = operators.value.find((o) => o.name === name)
  if (target) {
    session.setOperator(target)
    setRequestOperator(name)
  }
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

// ------------------------------------------------------------- 登记
const createOpen = ref(false)
const createError = ref('')
const createForm = reactive<Record<string, string>>({
  除冰编号: '', 对应航班: '', 除冰液类型: '', 作业区域: '', 作业班组: '', 作业车辆: '',
})

function openCreate() {
  createError.value = ''
  const firstRegion = regions.value.find((r) => session.regions.includes(r.region)) ?? regions.value[0]
  Object.assign(createForm, {
    除冰编号: '', 对应航班: '', 除冰液类型: '',
    作业区域: firstRegion?.region ?? '',
    作业班组: firstRegion?.team ?? '',
    作业车辆: '',
  })
  createOpen.value = true
}

async function submitCreate() {
  createError.value = ''
  createForm.作业班组 = teamOfRegion(createForm.作业区域)
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      // 越权/重复登记的原因直接显示在登记弹窗里（后端已写明缺哪个权限）
      createError.value = payload.message
      return
    }
    createOpen.value = false
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '登记请求失败'
  }
}

// ------------------------------------------------------------- 动作
async function runAction(action: string, row: Row) {
  feedback[Number(row.id)] = { ok: false, message: '提交中…' }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, version: row.version } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      const perms = payload.missing_permissions?.length
        ? `（缺少权限：${payload.missing_permissions.join('、')}）`
        : ''
      feedback[Number(row.id)] = { ok: false, message: `${payload.message}${perms}` }
      await reload() // 并发落败时刷新出最新版本与末次改动人
      return
    }
    feedback[Number(row.id)] = { ok: true, message: payload.message }
    await reload()
  } catch (error) {
    feedback[Number(row.id)] = {
      ok: false,
      message: error instanceof Error ? error.message : '除冰作业操作失败',
    }
  }
}

// ------------------------------------------------------------- 详情/用量
const detailRow = ref<Row | null>(null)
const detailForm = reactive({ 除冰液类型: '', 喷洒量: '' })
const detailError = ref('')
const detailOk = ref('')

async function openDetail(row: { id?: string | number | null }) {
  detailError.value = ''
  detailOk.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('除冰任务明细读取失败')
    const detail: Row = await response.json()
    detailRow.value = detail
    detailForm.除冰液类型 = String(detail.除冰液类型 ?? '')
    detailForm.喷洒量 = String(detail.喷洒量 ?? '')
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '明细读取失败'
  }
}

function closeDetail() {
  detailRow.value = null
}

async function saveFields() {
  if (!detailRow.value) return
  detailError.value = ''
  detailOk.value = ''
  try {
    const response = await request(`${ENDPOINT}/${detailRow.value.id}/fields`, {
      method: 'PATCH',
      body: JSON.stringify({
        values: {
          除冰液类型: detailForm.除冰液类型,
          喷洒量: detailForm.喷洒量,
          version: detailRow.value.version,
        },
      }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      const perms = payload.missing_permissions?.length
        ? `（缺少权限：${payload.missing_permissions.join('、')}）`
        : ''
      detailError.value = `${payload.message}${perms}`
      await openDetail(detailRow.value) // 刷新版本，便于用最新数据重试
      return
    }
    detailOk.value = payload.message
    await reload()
    await openDetail(payload.entry as Row)
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '用量保存失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('除冰任务列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (detailRow.value) {
      const latest = rows.value.find((r) => r.id === detailRow.value?.id)
      if (latest) detailRow.value = latest
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '除冰作业列表读取失败'
  }
}

onMounted(async () => {
  try {
    await loadScope()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '初始化失败'
  }
})
</script>
