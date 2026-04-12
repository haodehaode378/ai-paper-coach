<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { callApi } from '../lib/api'
import { loadLastResult, loadModelConfig } from '../lib/storage'

const props = defineProps({ endpoint: { type: String, required: true }, title: { type: String, required: true }, subtitle: { type: String, required: true }, emptyText: { type: String, required: true }, itemKind: { type: String, required: true } })
const router = useRouter()
const route = useRoute()
const items = ref([])
const selectedItem = ref(null)
const error = ref('')
const loading = ref(false)

const apiBase = computed(() => {
  const queryApiBase = route.query.api_base ? String(route.query.api_base) : ''
  if (queryApiBase) return queryApiBase
  const lastResult = loadLastResult()
  if (lastResult?.api_base) return String(lastResult.api_base)
  const modelConfig = loadModelConfig()
  if (modelConfig?.apiBase) return String(modelConfig.apiBase)
  return 'http://localhost:8000'
})

const selectedDetails = computed(() => {
  if (!selectedItem.value) return []
  if (props.itemKind === 'history' || props.itemKind === 'saved') {
    return [
      { label: '记录 ID', value: selectedItem.value.record_id || '-' },
      { label: '论文 ID', value: selectedItem.value.paper_id || '-' },
      { label: '阶段', value: selectedItem.value.stage || '-' },
      { label: '状态', value: selectedItem.value.status || '-' },
      { label: '保存时间', value: formatDate(selectedItem.value.saved_at) },
      { label: '来源', value: selectedItem.value.source_name || selectedItem.value.source_type || '-' }
    ]
  }
  return [
    { label: '文件名', value: selectedItem.value.name || '-' },
    { label: '路径', value: selectedItem.value.path || '-' },
    { label: '大小', value: formatSize(selectedItem.value.size) },
    { label: '更新时间', value: formatDate(selectedItem.value.modified_at) },
    { label: '类型', value: selectedItem.value.kind || props.itemKind }
  ]
})

async function loadItems() {
  loading.value = true
  error.value = ''
  try {
    const data = await callApi(apiBase.value, props.endpoint)
    items.value = Array.isArray(data.items) ? data.items : []
    selectedItem.value = items.value[0] || null
  } catch (err) {
    error.value = err.message
    items.value = []
    selectedItem.value = null
  } finally { loading.value = false }
}

function openItem(item) {
  selectedItem.value = item
  if (props.itemKind === 'history') {
    router.push({ name: 'results', query: { record_id: item.record_id, api_base: apiBase.value } })
    return
  }
  if (props.itemKind === 'saved') router.push({ name: 'results', query: { saved_id: item.record_id, api_base: apiBase.value } })
}

function formatDate(value) {
  if (!value && value !== 0) return '-'
  const numericValue = Number(value)
  if (Number.isFinite(numericValue) && numericValue > 100000) return new Date(numericValue * 1000).toLocaleString()
  const parsed = new Date(String(value))
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString()
}

function formatSize(value) {
  const size = Number(value || 0)
  if (!Number.isFinite(size) || size <= 0) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(2)} MB`
}

watch(() => route.fullPath, loadItems)
onMounted(loadItems)
</script>

<template>
  <div class="workspace-shell">
    <header class="topbar">
      <div class="brand-block"><p class="eyebrow">研究运行控制台</p><h1>AI 论文教练</h1></div>
      <div class="topbar-search">{{ subtitle }}</div>
      <div class="topbar-actions"><span class="status-pill status-pill-idle">接口 {{ apiBase }}</span><RouterLink class="button button-secondary" :to="{ name: 'task' }">返回控制台</RouterLink></div>
    </header>
    <div class="workspace-grid">
      <aside class="workspace-sidebar">
        <section class="sidebar-section">
          <p class="sidebar-title">导航</p>
          <div class="nav-list">
            <RouterLink class="nav-item" :to="{ name: 'task', query: { api_base: apiBase } }">控制台</RouterLink>
            <RouterLink class="nav-item" :class="{ 'nav-item-active': route.name === 'history' }" :to="{ name: 'history', query: { api_base: apiBase } }">历史记录</RouterLink>
            <RouterLink class="nav-item" :class="{ 'nav-item-active': route.name === 'saved' }" :to="{ name: 'saved', query: { api_base: apiBase } }">已保存报告</RouterLink>
            <RouterLink class="nav-item" :class="{ 'nav-item-active': route.name === 'uploads' }" :to="{ name: 'uploads', query: { api_base: apiBase } }">上传文件</RouterLink>
            <RouterLink class="nav-item" :class="{ 'nav-item-active': route.name === 'cache' }" :to="{ name: 'cache', query: { api_base: apiBase } }">缓存资源</RouterLink>
          </div>
        </section>
      </aside>
      <main class="workspace-main workspace-main-span-two">
        <section class="hero-panel panel-soft hero-panel-single"><div><p class="eyebrow">资源视图</p><h2>{{ title }}</h2><p class="panel-subtitle">{{ subtitle }}</p></div></section>
        <section class="panel-soft library-layout">
          <div>
            <div class="section-row"><div><p class="eyebrow">条目列表</p><h3>可用内容</h3></div></div>
            <p v-if="loading" class="empty-state">正在加载...</p>
            <p v-else-if="error" class="error-text">{{ error }}</p>
            <p v-else-if="!items.length" class="empty-state">{{ emptyText }}</p>
            <div v-else class="file-list-grid">
              <button v-for="item in items" :key="item.record_id || item.path || item.name" class="file-card button-plain" :class="{ 'file-card-active': selectedItem === item }" @click="openItem(item)">
                <strong>{{ item.title || item.name || item.record_id }}</strong>
                <p>{{ item.saved_at || item.status || item.path || '-' }}</p>
              </button>
            </div>
          </div>
          <aside class="detail-card" v-if="selectedItem">
            <div class="section-row"><div><p class="eyebrow">详情</p><h3>{{ selectedItem.title || selectedItem.name || selectedItem.record_id }}</h3></div></div>
            <div class="summary-list"><div v-for="row in selectedDetails" :key="row.label" class="summary-row"><span>{{ row.label }}</span><strong class="mono-text">{{ row.value }}</strong></div></div>
            <div class="section-actions" v-if="itemKind === 'history' || itemKind === 'saved'"><button class="button button-primary" @click="openItem(selectedItem)">打开阅读器</button></div>
          </aside>
        </section>
      </main>
    </div>
  </div>
</template>