<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import RunDiagnosticsPanel from '../components/RunDiagnosticsPanel.vue'
import { callApi } from '../lib/api'
import { loadLastResult } from '../lib/storage'
import { useTraceHistory } from '../composables/useTraceHistory'

const route = useRoute()
const router = useRouter()
const statuses = ref([])
const report = ref(null)
const reportError = ref('')
const loading = ref(false)
const paperId = ref('')
const apiBase = ref('')
const historyRecords = ref([])
const activeRecordId = ref('')

function addStatus(message) {
  const timestamp = new Date().toLocaleTimeString()
  statuses.value.unshift(`${timestamp} - ${message}`)
}

const { traces, traceError, startPolling, stopPolling, fetchTraces } = useTraceHistory({
  paperIdRef: paperId,
  apiBaseRef: apiBase,
  addStatus
})

function textLen(value) {
  if (value === null || value === undefined) return 0
  if (typeof value === 'string') return value.trim().length
  if (Array.isArray(value)) return value.reduce((sum, item) => sum + textLen(item), 0)
  if (typeof value === 'object') return Object.values(value).reduce((sum, item) => sum + textLen(item), 0)
  return String(value).trim().length
}

function asArray(value) {
  return Array.isArray(value) ? value : []
}

const context = computed(() => {
  const querySavedId = route.query.saved_id
  const queryRecordId = route.query.record_id
  const queryPaperId = route.query.paper_id
  const queryApiBase = route.query.api_base
  if (querySavedId && queryApiBase) {
    return { saved_id: String(querySavedId), api_base: String(queryApiBase) }
  }
  if (queryRecordId && queryApiBase) {
    return { record_id: String(queryRecordId), api_base: String(queryApiBase) }
  }
  if (queryPaperId && queryApiBase) {
    return { paper_id: String(queryPaperId), api_base: String(queryApiBase) }
  }
  return loadLastResult()
})

const paperMetaLine = computed(() => {
  if (!paperId.value) return 'Waiting for a report.'
  const title = report.value?.paper_meta?.title || 'Untitled paper'
  return `Paper ID: ${paperId.value} | Title: ${title}`
})

const requirementChecks = computed(() => {
  const summary = report.value?.three_minute_summary || {}
  const reproduction = report.value?.reproduction_guide || {}
  const readingQa = report.value?.reading_qa || {}
  const reproductionTotal =
    textLen(reproduction.environment || '') +
    textLen(reproduction.dataset || '') +
    textLen(reproduction.commands || []) +
    textLen(reproduction.key_hyperparams || []) +
    textLen(reproduction.expected_range || '') +
    textLen(reproduction.common_errors || [])

  const qaKeys = [
    'q1_problem_and_novelty',
    'q2_related_work_and_researchers',
    'q3_key_idea',
    'q4_experiment_design',
    'q5_dataset_and_code',
    'q6_support_for_claims',
    'q7_contribution_and_next_step'
  ]

  const checks = [
    { key: 'three_minute_summary.problem', min: 1000, actual: textLen(summary.problem || '') },
    { key: 'reproduction_guide.total', min: 1000, actual: reproductionTotal }
  ]

  qaKeys.forEach((key) => {
    checks.push({ key: `reading_qa.${key}`, min: 700, actual: textLen(readingQa[key] || '') })
  })

  return checks.map((item) => ({ ...item, ok: item.actual >= item.min }))
})

const reportSections = computed(() => {
  if (!report.value) return []

  const summary = report.value.three_minute_summary || {}
  const reproduction = report.value.reproduction_guide || {}
  const readingQa = report.value.reading_qa || {}

  return [
    {
      title: 'Summary',
      blocks: [
        { label: 'Paper analysis', type: 'text', value: summary.problem || '-' },
        { label: 'Method points', type: 'list', value: summary.method_points || [] },
        { label: 'Key results', type: 'list', value: summary.key_results || [] }
      ]
    },
    {
      title: 'Reproduction Guide',
      blocks: [
        { label: 'Environment', type: 'text', value: reproduction.environment || '-' },
        { label: 'Dataset', type: 'text', value: reproduction.dataset || '-' },
        { label: 'Commands', type: 'list', value: reproduction.commands || [] },
        { label: 'Key hyperparameters', type: 'list', value: reproduction.key_hyperparams || [] }
      ]
    },
    {
      title: 'Seven Questions',
      blocks: [
        { label: 'Question 1', type: 'text', value: readingQa.q1_problem_and_novelty || '-' },
        { label: 'Question 2', type: 'text', value: readingQa.q2_related_work_and_researchers || '-' },
        { label: 'Question 3', type: 'text', value: readingQa.q3_key_idea || '-' },
        { label: 'Question 4', type: 'text', value: readingQa.q4_experiment_design || '-' },
        { label: 'Question 5', type: 'text', value: readingQa.q5_dataset_and_code || '-' },
        { label: 'Question 6', type: 'text', value: readingQa.q6_support_for_claims || '-' },
        { label: 'Question 7', type: 'text', value: readingQa.q7_contribution_and_next_step || '-' }
      ]
    }
  ]
})

const reportStats = computed(() => [
  { label: 'State', value: report.value ? 'Loaded' : 'Missing' },
  { label: 'Requirements', value: requirementChecks.value.every((item) => item.ok) ? 'Pass' : 'Needs work' },
  { label: 'Trace count', value: `${traces.value.length}` },
  { label: 'Record ID', value: activeRecordId.value || '-' }
])

async function loadHistoryRecords() {
  try {
    const data = await callApi(apiBase.value || context.value?.api_base || 'http://localhost:8000', '/history')
    historyRecords.value = Array.isArray(data.items) ? data.items : []
  } catch (error) {
    addStatus(`History load failed: ${error.message}`)
  }
}

function openHistoryRecord(recordId) {
  router.push({ name: 'results', query: { record_id: recordId, api_base: apiBase.value || context.value?.api_base || 'http://localhost:8000' } })
}

async function saveCurrentReport() {
  if (!activeRecordId.value) {
    addStatus('No active record to save.')
    return
  }
  try {
    await callApi(apiBase.value, `/saved/${encodeURIComponent(activeRecordId.value)}`, { method: 'POST' })
    addStatus(`Saved report ${activeRecordId.value}`)
  } catch (error) {
    addStatus(`Save failed: ${error.message}`)
  }
}

async function loadReport() {
  reportError.value = ''
  report.value = null
  stopPolling()

  if (!context.value?.api_base) {
    addStatus('No API base available. Return to the console and run a task again.')
    return
  }

  apiBase.value = context.value.api_base
  loading.value = true

  try {
    if (context.value.saved_id) {
      activeRecordId.value = context.value.saved_id
      addStatus(`Loading saved report ${context.value.saved_id} ...`)
      const detail = await callApi(apiBase.value, `/saved/${encodeURIComponent(context.value.saved_id)}`)
      report.value = detail.report || null
      paperId.value = detail.paper_id || detail.meta?.paper_id || ''
      addStatus('Saved report loaded.')
    } else if (context.value.record_id) {
      activeRecordId.value = context.value.record_id
      addStatus(`Loading history record ${context.value.record_id} ...`)
      const detail = await callApi(apiBase.value, `/history/${encodeURIComponent(context.value.record_id)}`)
      report.value = detail.report || null
      paperId.value = detail.paper_id || detail.meta?.paper_id || ''
      addStatus('History record loaded.')
    } else if (context.value.paper_id) {
      paperId.value = context.value.paper_id
      addStatus(`Loading latest report for paper_id=${paperId.value} ...`)
      startPolling()
      await fetchTraces()
      report.value = await callApi(apiBase.value, `/report/${encodeURIComponent(paperId.value)}`)
      addStatus('Latest report loaded.')
    } else {
      addStatus('No paper or record context found.')
    }
  } catch (error) {
    reportError.value = error.message
    addStatus(`Error: ${error.message}`)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadHistoryRecords()
})

watch(() => route.fullPath, loadReport, { immediate: true })
</script>

<template>
  <div class="workspace-shell">
    <header class="topbar">
      <div class="brand-block">
        <p class="eyebrow">Research Runtime Console</p>
        <h1>AI Paper Coach</h1>
      </div>
      <div class="topbar-search">History and saved report reader</div>
      <div class="topbar-actions">
        <span class="status-pill status-pill-live">Results</span>
        <RouterLink class="button button-secondary" :to="{ name: 'task' }">Console</RouterLink>
      </div>
    </header>

    <div class="workspace-grid">
      <aside class="workspace-sidebar">
        <section class="sidebar-section">
          <p class="sidebar-title">Navigation</p>
          <div class="nav-list">
            <RouterLink class="nav-item" :to="{ name: 'task' }">Console</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'history' }">History</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'saved' }">Saved Reports</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'uploads' }">Uploads</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'cache' }">Cache</RouterLink>
          </div>
        </section>

        <section class="sidebar-section">
          <div class="section-row">
            <p class="sidebar-title">Local History</p>
            <span class="sidebar-meta">{{ historyRecords.length }} items</span>
          </div>
          <div class="history-list">
            <button v-for="item in historyRecords" :key="item.record_id" class="history-item button-plain" @click="openHistoryRecord(item.record_id)">
              <div>
                <strong>{{ item.title }}</strong>
                <p>{{ item.saved_at || item.status || '-' }}</p>
              </div>
              <span class="history-dot"></span>
            </button>
            <div v-if="!historyRecords.length" class="history-empty">No history records yet.</div>
          </div>
        </section>
      </aside>

      <main class="workspace-main">
        <section class="hero-panel panel-soft">
          <div>
            <p class="eyebrow">Record Detail</p>
            <h2>Report Reader</h2>
            <p class="panel-subtitle">{{ paperMetaLine }}</p>
          </div>
          <div class="hero-meta-grid">
            <div>
              <span class="meta-label">Paper ID</span>
              <strong>{{ paperId || '-' }}</strong>
            </div>
            <div>
              <span class="meta-label">Status</span>
              <strong>{{ loading ? 'Loading' : (report ? 'Ready' : 'Missing') }}</strong>
            </div>
            <div>
              <span class="meta-label">Record ID</span>
              <strong>{{ activeRecordId || '-' }}</strong>
            </div>
          </div>
        </section>

        <section class="panel-soft">
          <div class="section-row">
            <div>
              <p class="eyebrow">Workspace Tabs</p>
              <h3>Reader</h3>
            </div>
            <div class="tab-strip">
              <span class="tab-pill tab-pill-active">Summary</span>
              <span class="tab-pill">Reproduction</span>
              <span class="tab-pill">Q&A</span>
              <span class="tab-pill">Trace</span>
            </div>
          </div>

          <p v-if="loading" class="empty-state">Loading report...</p>
          <p v-else-if="reportError" class="error-text">{{ reportError }}</p>
          <p v-else-if="!report" class="empty-state">No report to display.</p>

          <div v-else class="report-layout">
            <section class="report-section report-section-compact">
              <div class="section-header">
                <h3>Requirement Checks</h3>
                <p :class="requirementChecks.every((item) => item.ok) ? 'success-text' : 'error-text'">
                  {{ requirementChecks.every((item) => item.ok) ? 'All passed' : 'Some checks failed' }}
                </p>
              </div>
              <ul class="check-list">
                <li v-for="item in requirementChecks" :key="item.key">
                  <strong>{{ item.key }}</strong>
                  <span :class="item.ok ? 'success-text' : 'error-text'">{{ item.ok ? 'pass' : 'fail' }}</span>
                  <span>({{ item.actual }}/{{ item.min }})</span>
                </li>
              </ul>
            </section>

            <section v-for="section in reportSections" :key="section.title" class="report-section report-section-compact">
              <h3>{{ section.title }}</h3>
              <div class="report-blocks">
                <article v-for="block in section.blocks" :key="block.label" class="report-block">
                  <h4>{{ block.label }}</h4>
                  <pre v-if="block.type === 'text'">{{ block.value }}</pre>
                  <ul v-else class="bullet-list">
                    <li v-for="item in asArray(block.value)" :key="String(item)">{{ item }}</li>
                  </ul>
                </article>
              </div>
            </section>
          </div>
        </section>
      </main>

      <aside class="workspace-detail">
        <section class="panel-soft detail-panel">
          <div class="section-row">
            <div>
              <p class="eyebrow">Record Snapshot</p>
              <h3>Summary</h3>
            </div>
          </div>
          <div class="summary-list">
            <div v-for="item in reportStats" :key="item.label" class="summary-row">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>
          <div class="button-column" style="margin-top: 12px;">
            <button class="button button-secondary" @click="saveCurrentReport">Save Report</button>
          </div>
        </section>
      </aside>
    </div>

    <RunDiagnosticsPanel :statuses="statuses" :traces="traces" :trace-error="traceError" :compact="true" empty-trace-message="Trace records appear here when available." />
  </div>
</template>