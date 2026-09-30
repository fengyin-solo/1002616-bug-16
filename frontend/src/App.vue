<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">机场地面保障管理平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向机场地面保障的航空器引导、客梯对接、行李装卸、航油加注、除冰作业与廊桥调度的一体化管理后台。</span>
        <span class="head-user">当前值班：{{ store.operator }}（{{ store.role }}岗<template v-if="store.team"> · {{ store.team }}</template>） · {{ store.shiftLabel }}</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { useSessionStore } from '@/stores/session'

const store = useSessionStore()

const navItems = [{ label: "运营概览", path: "/" }, { label: "机位分配", path: "/flightstand" }, { label: "引导入位", path: "/marshalling" }, { label: "廊桥对接", path: "/bridge" }, { label: "行李装卸", path: "/baggage" }, { label: "航食配餐", path: "/catering" }, { label: "航油加注", path: "/fueling" }, { label: "除冰作业", path: "/deicing" }, { label: "清水排污", path: "/lavatory" }, { label: "推出开车", path: "/pushback" }, { label: "地面设备", path: "/gse" }, { label: "货物装卸", path: "/cargo" }, { label: "放行签派", path: "/clearance" }, { label: "过站保障", path: "/turnaround" }, { label: "机坪巡查", path: "/ramp" }, { label: "航空气象", path: "/weather2" }, { label: "特种车辆", path: "/vehicle" }, { label: "人员排班", path: "/staffshift" }, { label: "跑道灯光", path: "/runway" }, { label: "应急处置", path: "/emergencyplan" }, { label: "质量监察", path: "/qualitycheck" }]
</script>
