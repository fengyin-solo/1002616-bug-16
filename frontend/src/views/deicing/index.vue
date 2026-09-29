<template>
  <section class="page" data-module="deicing">
    <header class="page-head">
      <div>
        <h2>除冰作业管理</h2>
        <p class="page-desc">维护除冰任务，围绕除冰编号、对应航班、除冰液类型、喷洒量做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <label class="operator-picker">
          <span>当班操作人</span>
          <select v-model="operator">
            <option v-for="op in operators" :key="op.姓名" :value="op.姓名">
              {{ op.姓名 }}（{{ op.班组 }} · {{ op.岗位 }} · {{ op.区域 }}）
            </option>
          </select>
        </label>
        <button class="btn primary" type="button" @click="openCreate">登记除冰任务</button>
        <button class="btn" type="button" @click="exportRows">导出除冰作业清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <details class="scope-panel">
      <summary>可用范围表（按作业区域划分）</summary>
      <table class="data-table">
        <thead>
          <tr><th>作业区域</th><th>可用班组</th></tr>
        </thead>
        <tbody>
          <tr v-for="area in scopeAreas" :key="area.作业区域">
            <td>{{ area.作业区域 }}</td>
            <td>{{ area.可用班组.join('、') }}</td>
          </tr>
        </tbody>
      </table>
    </details>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <form v-if="createOpen" class="create-panel" @submit.prevent="submitCreate">
      <label v-for="field in createFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="createForm[field]" :placeholder="`填写${field}`" />
      </label>
      <button class="btn primary" type="submit">提交登记</button>
      <button class="btn ghost" type="button" @click="createOpen = false">取消</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="row in rows" :key="String(row.id)">
          <tr>
            <td v-for="column in columns" :key="column">
              <template v-if="editingId === row.id && editableColumns.includes(column)">
                <input v-model="editForm[column]" class="cell-input" />
              </template>
              <template v-else>{{ row[column] ?? '—' }}</template>
            </td>
            <td class="row-actions">
              <template v-if="editingId === row.id">
                <button class="link" type="button" @click="submitEdit(row)">保存</button>
                <button class="link" type="button" @click="editingId = null">取消</button>
              </template>
              <template v-else>
                <button
                  v-for="action in actions"
                  :key="action"
                  class="link"
                  type="button"
                  @click="runAction(action, row)"
                >
                  {{ action }}
                </button>
                <button class="link" type="button" @click="openEdit(row)">改动</button>
              </template>
            </td>
          </tr>
          <tr v-if="rowError[String(row.id)]" class="row-error-line">
            <td :colspan="columns.length + 1">
              <span class="error-text">{{ rowError[String(row.id)] }}</span>
            </td>
          </tr>
        </template>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无除冰作业数据，可先登记除冰任务</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条除冰作业记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type OperatorInfo = { 姓名: string; 班组: string; 岗位: string; 区域: string }
type ScopeArea = { 作业区域: string; 可用班组: string[] }

const ENDPOINT = '/api/deicing'
const columns = ["除冰编号", "对应航班", "除冰液类型", "喷洒量", "作业车辆", "作业人员", "作业区域", "作业班组", "经办人", "末次改动人", "除冰状态"]
const editableColumns = ["除冰液类型", "喷洒量", "作业车辆", "作业人员"]
const actions = ["安排除冰", "开始除冰", "完成除冰", "跳过除冰"]
const createFields = ["除冰编号", "对应航班", "除冰液类型", "作业区域", "喷洒量", "作业车辆"]
const stats = ref([{ label: '待除冰航班', value: 0 }, { label: '除冰中航班', value: 0 }, { label: '已完成除冰', value: 0 }])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const rowError = ref<Record<string, string>>({})
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const operator = ref('')
const operators = ref<OperatorInfo[]>([])
const scopeAreas = ref<ScopeArea[]>([])

const createOpen = ref(false)
const createForm = ref<Record<string, string>>({})
const editingId = ref<number | null>(null)
const editForm = ref<Record<string, string>>({})

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  createForm.value = {}
  createOpen.value = true
  errorMessage.value = ''
}

function openEdit(row: Row) {
  editingId.value = Number(row.id)
  editForm.value = Object.fromEntries(editableColumns.map((field) => [field, String(row[field] ?? '')]))
  rowError.value = {}
}

async function loadPermissions() {
  try {
    const response = await request(`${ENDPOINT}/permissions`)
    if (!response.ok) return
    const payload = await response.json()
    operators.value = payload.operators ?? []
    scopeAreas.value = payload.areas ?? []
    if (!operator.value && operators.value.length) {
      operator.value = operators.value[0].姓名
    }
  } catch {
    // 权限表加载失败不阻塞列表，提交时后端仍会逐条拦截
  }
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm.value, operator: operator.value } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      errorMessage.value = payload.message ?? '除冰任务登记被拦截'
      return
    }
    createOpen.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '除冰任务登记失败'
  }
}

async function submitEdit(row: Row) {
  rowError.value = {}
  try {
    const response = await request(`${ENDPOINT}/${row.id}`, {
      method: 'PUT',
      body: JSON.stringify({ values: { ...editForm.value, operator: operator.value, 版本号: row.版本号 } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      rowError.value = { [String(row.id)]: payload.message ?? '改动被拦截' }
      return
    }
    editingId.value = null
    await reload()
  } catch (error) {
    rowError.value = { [String(row.id)]: error instanceof Error ? error.message : '除冰记录改动失败' }
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  rowError.value = {}
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action, operator: operator.value, 版本号: row.版本号 } }),
    })
    const payload = await response.json()
    if (!payload.ok) {
      // 越权拦截：在提交行上写明缺哪个权限
      rowError.value = { [String(row.id)]: payload.message ?? '除冰作业动作被拦截' }
      return
    }
    await reload()
  } catch (error) {
    rowError.value = { [String(row.id)]: error instanceof Error ? error.message : '除冰作业操作失败' }
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('除冰任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    const count = (status: string) => rows.value.filter((row) => row['除冰状态'] === status).length
    stats.value = [
      { label: '待除冰航班', value: count('待除冰') },
      { label: '除冰中航班', value: count('除冰中') },
      { label: '已完成除冰', value: count('已完成') },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '除冰作业列表读取失败'
  }
}

onMounted(() => {
  void loadPermissions()
  void reload()
})
</script>

<style scoped>
.operator-picker {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--muted);
}
.scope-panel {
  margin-bottom: 12px;
  font-size: 13px;
}
.scope-panel summary {
  cursor: pointer;
  color: var(--muted);
  margin-bottom: 6px;
}
.create-panel {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: flex-end;
  margin-bottom: 12px;
  padding: 10px 12px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
}
.create-panel .filter-item span {
  display: block;
  font-size: 12px;
  color: var(--muted);
}
.cell-input {
  width: 90px;
  padding: 2px 4px;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 13px;
}
.row-error-line td {
  background: #fef3f2;
  border: 1px solid var(--border);
  padding: 6px 10px;
  font-size: 12px;
}
</style>
