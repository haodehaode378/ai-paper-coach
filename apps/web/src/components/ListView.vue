<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { callApi } from '../lib/api'
import { loadLastResult, loadModelConfig } from '../lib/storage'

const props = defineProps({
  endpoint: { type: String, required: true },
  title: { type: String, required: true },
  subtitle: { type: String, required: true },
  emptyText: { type: String, required: true },
  itemKind: { type: String, required: true },
})

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
      { label: 'Record ID', value: selectedItem.value.record_id || '-' },
      { label: 'Paper ID', value: selectedItem.value.paper_id || '-' },
      { label: 'Stage', value: selectedItem.value.stage || '-' },
      { label: 'Status', value: selectedItem.value.status || '-' },
      { label: 'Saved At', value: formatDate(selectedItem.value.saved_at) },
      { label: 'Source', value: selectedItem.value.source_name || selectedItem.value.source_type || '-' }
    ]
  }

  return [
    { label: 'Name', value: selectedItem.value.name || '-' },
    { label: 'Path', value: selectedItem.value.path || '-' },
    { label: 'Size', value: formatSize(selectedItem.value.size) },
    { label: 'Updated', value: formatDate(selectedItem.value.modified_at) },
    { label: 'Kind', value: selectedItem.value.kind || props.itemKind }
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
  } finally {
    loading.value = false
  }
}

function openItem(item) {
  selectedItem.value = item

  if (props.itemKind === 'history') {
    router.push({ name: 'results', query: { record_id: item.record_id, api_base: apiBase.value } })
    return
  }
  if (props.itemKind === 'saved') {
    router.push({ name: 'results', query: { saved_id: item.record_id, api_base: apiBase.value } })
  }
}

function formatDate(value) {
  if (!value && value !== 0) return '-'

  const numericValue = Number(value)
  if (Number.isFinite(numericValue) && numericValue > 100000) {
    return new Date(numericValue * 1000).toLocaleString()
  }

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
      <div class="brand-block">
        <p class="eyebrow">Research Runtime Console</p>
        <h1>AI Paper Coach</h1>
      </div>
      <div class="topbar-search">{{ subtitle }}</div>
      <div class="topbar-actions">
        <span class="status-pill status-pill-idle">API {{ apiBase }}</span>
        <RouterLink class="button button-secondary" :to="{ name: 'task' }">Console</RouterLink>
      </div>
    </header>

    <div class="workspace-grid">
      <aside class="workspace-sidebar">
        <section class="sidebar-section">
          <p class="sidebar-title">Navigation</p>
          <div class="nav-list">
            <RouterLink class="nav-item" :to="{ name: 'task', query: { api_base: apiBase } }">Console</RouterLink>
            <RouterLink class="nav-item" :class="{ 'nav-item-active': route.name === 'history' }" :to="{ name: 'history', query: { api_base: apiBase } }">History</RouterLink>
            <RouterLink class="nav-item" :class="{ 'nav-item-active': route.name === 'saved' }" :to="{ name: 'saved', query: { api_base: apiBase } }">Saved Reports</RouterLink>
            <RouterLink class="nav-item" :class="{ 'nav-item-active': route.name === 'uploads' }" :to="{ name: 'uploads', query: { api_base: apiBase } }">Uploads</RouterLink>
            <RouterLink class="nav-item" :class="{ 'nav-item-active': route.name === 'cache' }" :to="{ name: 'cache', query: { api_base: apiBase } }">Cache</RouterLink>
          </div>
        </section>
      </aside>

      <main class="workspace-main workspace-main-span-two">
        <section class="hero-panel panel-soft hero-panel-single">
          <div>
            <p class="eyebrow">Library View</p>
            <h2>{{ title }}</h2>
            <p class="panel-subtitle">{{ subtitle }}</p>
          </div>
        </section>

        <section class="panel-soft library-layout">
          <div>
            <div class="section-row">
              <div>
                <p class="eyebrow">Items</p>
                <h3>Available Entries</h3>
              </div>
            </div>

            <p v-if="loading" class="empty-state">Loading ...</p>
            <p v-else-if="error" class="error-text">{{ error }}</p>
            <p v-else-if="!items.length" class="empty-state">{{ emptyText }}</p>

            <div v-else class="file-list-grid">
              <button
                v-for="item in items"
                :key="item.record_id || item.path || item.name"
                class="file-card button-plain"
                :class="{ 'file-card-active': selectedItem === item }"
                @click="openItem(item)"
              >
                <strong>{{ item.title || item.name || item.record_id }}</strong>
                <p>{{ item.saved_at || item.status || item.path || '-' }}</p>
              </button>
            </div>
          </div>

          <aside class="detail-card" v-if="selectedItem">
            <div class="section-row">
              <div>
                <p class="eyebrow">Details</p>
                <h3>{{ selectedItem.title || selectedItem.name || selectedItem.record_id }}</h3>
              </div>
            </div>

            <div class="summary-list">
              <div v-for="row in selectedDetails" :key="row.label" class="summary-row">
                <span>{{ row.label }}</span>
                <strong class="mono-text">{{ row.value }}</strong>
              </div>
            </div>

            <div class="section-actions" v-if="itemKind === 'history' || itemKind === 'saved'">
              <button class="button button-primary" @click="openItem(selectedItem)">Open Reader</button>
            </div>
          </aside>
        </section>
      </main>
    </div>
  </div>
</template>