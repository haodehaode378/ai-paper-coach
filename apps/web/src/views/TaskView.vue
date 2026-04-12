<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import RunDiagnosticsPanel from '../components/RunDiagnosticsPanel.vue'
import { callApi, isTimeoutError } from '../lib/api'
import {
  buildModelConfig,
  clearModelConfig,
  defaultFormState,
  loadModelConfig,
  saveLastResult,
  saveModelConfig
} from '../lib/storage'
import { useTraceHistory } from '../composables/useTraceHistory'

const TIMEOUT_ANALYZE_MS = 480000
const TIMEOUT_REVIEW_MS = 600000
const TIMEOUT_FINALIZE_MS = 1200000

const router = useRouter()
const form = ref(loadModelConfig())
const statuses = ref([])
const currentPaperId = ref('')
const paperFile = ref(null)
const isRunning = ref(false)
const historyRecords = ref([])
const stageState = ref({ ingest: false, analyze: false, review: false, finalize: false })
const apiBaseRef = computed(() => form.value.apiBase)

function addStatus(message) {
  const timestamp = new Date().toLocaleTimeString()
  statuses.value.unshift(`${timestamp} - ${message}`)
}

const { traces, traceError, startPolling, stopPolling } = useTraceHistory({
  paperIdRef: currentPaperId,
  apiBaseRef,
  addStatus
})

const pipelineSteps = computed(() => [
  { key: 'ingest', label: 'Ingest', done: stageState.value.ingest },
  { key: 'analyze', label: 'Analyze', done: stageState.value.analyze },
  { key: 'review', label: 'Review', done: stageState.value.review },
  { key: 'finalize', label: 'Finalize', done: stageState.value.finalize }
])

const configSummary = computed(() => {
  const modelConfig = buildModelConfig(form.value)
  return [
    { label: 'API', value: form.value.apiBase },
    { label: 'Mode', value: form.value.runMode || 'deep' },
    { label: 'Model A', value: modelConfig.primary.model },
    { label: 'Model B', value: modelConfig.secondary.model },
    { label: 'Paper ID', value: currentPaperId.value || '-' }
  ]
})

function resetStageState() {
  stageState.value = { ingest: false, analyze: false, review: false, finalize: false }
}

async function loadHistoryRecords() {
  try {
    const data = await callApi(form.value.apiBase, '/history')
    historyRecords.value = Array.isArray(data.items) ? data.items : []
  } catch (error) {
    addStatus(`History load failed: ${error.message}`)
  }
}

function openHistoryRecord(recordId) {
  router.push({ name: 'results', query: { record_id: recordId, api_base: form.value.apiBase } })
}

function currentModelConfig() {
  return buildModelConfig(form.value)
}

function onFileChange(event) {
  paperFile.value = event.target.files?.[0] || null
}

function setPaperId(paperId) {
  currentPaperId.value = paperId || ''
}

function handleSaveConfig() {
  saveModelConfig(form.value)
  addStatus('Model configuration saved to local storage.')
}

function handleClearConfig() {
  const next = clearModelConfig()
  form.value = { ...defaultFormState(), ...next, apiBase: form.value.apiBase }
  addStatus('Model configuration cleared from local storage.')
}

async function handleValidateConfig() {
  try {
    addStatus('Validating model APIs ...')
    const data = await callApi(form.value.apiBase, '/validate-models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_config: currentModelConfig() })
    })

    if (Array.isArray(data.results)) {
      for (const item of data.results) {
        if (item.ok) {
          addStatus(`Validation passed: ${item.display_name || item.provider} (${item.latency_ms} ms)`) 
        } else {
          addStatus(`Validation failed: ${item.display_name || item.provider} - ${item.error || 'unknown error'}`)
        }
      }
    }

    addStatus(data.ok ? 'API validation finished successfully.' : 'API validation finished with failures.')
  } catch (error) {
    addStatus(`API validation request failed: ${error.message}`)
  }
}

async function ingest() {
  const url = String(form.value.paperUrl || '').trim()
  if (!url && !paperFile.value) {
    throw new Error('Provide a paper URL or upload a PDF file.')
  }

  addStatus('Importing paper input ...')

  let payload
  if (paperFile.value) {
    const formData = new FormData()
    formData.append('file', paperFile.value)
    if (url) {
      formData.append('url', url)
    }

    payload = await callApi(form.value.apiBase, '/ingest', {
      method: 'POST',
      body: formData
    })
  } else {
    payload = await callApi(form.value.apiBase, '/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    })
  }

  const paperId = payload.paper_id || payload.id || payload.paperId
  if (!paperId) {
    throw new Error('Ingest completed but the API did not return paper_id.')
  }

  setPaperId(paperId)
  stageState.value.ingest = true
  startPolling()
  addStatus(`Ingest complete: paper_id=${paperId}`)
  return paperId
}

function emitStageMessages(data, fallbackStage) {
  if (Array.isArray(data?.warnings)) {
    data.warnings.forEach((warning) => addStatus(`Warning: ${warning}`))
  }

  if (data?.stage_metrics) {
    const metrics = data.stage_metrics
    addStatus(
      `Stage metrics: ${metrics.stage || fallbackStage || '-'} input=${Number(metrics.input_chars || 0)} output=${Number(metrics.output_chars || 0)} elapsed=${Number(metrics.elapsed_ms || 0)} ms`
    )
  }
}

async function runAnalyze(paperId, mode, modelConfig) {
  addStatus(`Running analyze stage (${mode}) ...`)
  const data = await callApi(
    form.value.apiBase,
    '/analyze',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paper_id: paperId, mode, model_config: modelConfig })
    },
    TIMEOUT_ANALYZE_MS
  )
  stageState.value.analyze = true
  addStatus('Analyze stage complete.')
  emitStageMessages(data, 'analyze')
}

async function runReview(paperId, modelConfig) {
  addStatus('Running review stage ...')
  const data = await callApi(
    form.value.apiBase,
    '/review',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paper_id: paperId, model_config: modelConfig })
    },
    TIMEOUT_REVIEW_MS
  )
  stageState.value.review = true
  addStatus('Review stage complete.')
  emitStageMessages(data, 'review')
}

async function runFinalize(paperId, mode, modelConfig) {
  addStatus('Running finalize stage ...')
  const data = await callApi(
    form.value.apiBase,
    '/finalize',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paper_id: paperId, strict: mode === 'strict', model_config: modelConfig })
    },
    TIMEOUT_FINALIZE_MS
  )
  stageState.value.finalize = true
  addStatus('Finalize stage complete.')
  emitStageMessages(data, 'finalize')
}

async function runPipeline() {
  try {
    isRunning.value = true
    statuses.value = []
    resetStageState()
    stopPolling()

    const mode = form.value.runMode || 'deep'
    const modelConfig = currentModelConfig()
    addStatus(`Pipeline configuration: Model A=${modelConfig.primary.model} | Model B=${modelConfig.secondary.model} | mode=${mode}`)

    const paperId = await ingest()
    await runAnalyze(paperId, mode, modelConfig)

    if (mode !== 'fast') {
      await runReview(paperId, modelConfig)
      await runFinalize(paperId, mode, modelConfig)
    }

    stopPolling()
    await loadHistoryRecords()
    saveLastResult({ paper_id: paperId, api_base: form.value.apiBase })
    await router.push({ name: 'results', query: { paper_id: paperId, api_base: form.value.apiBase } })
  } catch (error) {
    if (isTimeoutError(error) && currentPaperId.value) {
      addStatus(error.message)
      addStatus('The backend may still be processing. Redirecting to the report reader.')
      saveLastResult({ paper_id: currentPaperId.value, api_base: form.value.apiBase })
      await router.push({ name: 'results', query: { paper_id: currentPaperId.value, api_base: form.value.apiBase } })
      return
    }

    stopPolling()
    addStatus(`Error: ${error.message}`)
  } finally {
    isRunning.value = false
  }
}

onMounted(() => {
  loadHistoryRecords()
  addStatus('Console ready. Start a task or open a saved record.')
})
</script>

<template>
  <div class="workspace-shell">
    <header class="topbar">
      <div class="brand-block">
        <p class="eyebrow">Research Runtime Console</p>
        <h1>AI Paper Coach</h1>
      </div>
      <div class="topbar-search">Search papers, records, and file assets</div>
      <div class="topbar-actions">
        <span class="status-pill" :class="isRunning ? 'status-pill-live' : 'status-pill-idle'">
          {{ isRunning ? 'Pipeline running' : 'System idle' }}
        </span>
        <button class="button button-secondary" @click="handleValidateConfig">Validate APIs</button>
        <button class="button button-primary" :disabled="isRunning" @click="runPipeline">
          {{ isRunning ? 'Running ...' : 'Start Run' }}
        </button>
      </div>
    </header>

    <div class="workspace-grid">
      <aside class="workspace-sidebar">
        <section class="sidebar-section">
          <p class="sidebar-title">Navigation</p>
          <div class="nav-list">
            <RouterLink class="nav-item nav-item-active" :to="{ name: 'task' }">Console</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'history', query: { api_base: form.apiBase } }">History</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'saved', query: { api_base: form.apiBase } }">Saved Reports</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'uploads', query: { api_base: form.apiBase } }">Uploads</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'cache', query: { api_base: form.apiBase } }">Cache</RouterLink>
          </div>
        </section>

        <section class="sidebar-section">
          <div class="section-row">
            <p class="sidebar-title">Recent History</p>
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
            <p class="eyebrow">Current Session</p>
            <h2>Paper Control Console</h2>
            <p class="panel-subtitle">Import a paper, configure both models, run the pipeline, and keep each result in local history.</p>
          </div>
          <div class="hero-meta-grid">
            <div>
              <span class="meta-label">Current Paper ID</span>
              <strong>{{ currentPaperId || '-' }}</strong>
            </div>
            <div>
              <span class="meta-label">Run Mode</span>
              <strong>{{ form.runMode || 'deep' }}</strong>
            </div>
            <div>
              <span class="meta-label">Input Source</span>
              <strong>{{ paperFile ? 'Uploaded PDF' : (form.paperUrl ? 'Remote URL' : 'Not selected') }}</strong>
            </div>
          </div>
        </section>

        <section class="panel-soft">
          <div class="section-row">
            <div>
              <p class="eyebrow">Pipeline</p>
              <h3>Stage Progress</h3>
            </div>
          </div>
          <div class="pipeline-row">
            <div v-for="step in pipelineSteps" :key="step.key" class="pipeline-step" :class="{ 'pipeline-step-done': step.done }">
              <span class="pipeline-badge">{{ step.done ? 'Done' : 'Pending' }}</span>
              <strong>{{ step.label }}</strong>
            </div>
          </div>
        </section>

        <section class="panel-soft">
          <div class="section-row">
            <div>
              <p class="eyebrow">Task Intake</p>
              <h3>Run Input</h3>
            </div>
          </div>
          <div class="form-grid control-grid">
            <label class="field span-two">
              <span>API Base URL</span>
              <input v-model="form.apiBase" autocomplete="off" />
            </label>
            <label class="field span-two">
              <span>Paper URL</span>
              <input v-model="form.paperUrl" placeholder="arXiv URL or direct PDF URL" autocomplete="off" />
            </label>
            <label class="field">
              <span>Upload PDF</span>
              <input type="file" accept="application/pdf" @change="onFileChange" />
            </label>
            <label class="field">
              <span>Run Mode</span>
              <select v-model="form.runMode">
                <option value="deep">Deep read</option>
                <option value="full">Full pass</option>
                <option value="fast">Fast pass</option>
              </select>
            </label>
          </div>
        </section>
      </main>

      <aside class="workspace-detail">
        <section class="panel-soft detail-panel">
          <div class="section-row">
            <div>
              <p class="eyebrow">Runtime Config</p>
              <h3>Models and Keys</h3>
            </div>
          </div>

          <div class="detail-stack">
            <label class="field">
              <span>Model A Base URL</span>
              <input v-model="form.qwenBase" autocomplete="off" />
            </label>
            <label class="field">
              <span>Model A Key</span>
              <input v-model="form.qwenKey" type="password" autocomplete="off" />
            </label>
            <label class="field">
              <span>Model A Name</span>
              <input v-model="form.qwenModel" autocomplete="off" />
            </label>
            <label class="field">
              <span>Model B Base URL</span>
              <input v-model="form.minimaxBase" autocomplete="off" />
            </label>
            <label class="field">
              <span>Model B Key</span>
              <input v-model="form.minimaxKey" type="password" autocomplete="off" />
            </label>
            <label class="field">
              <span>Model B Name</span>
              <input v-model="form.minimaxModel" autocomplete="off" />
            </label>
          </div>

          <div class="button-column">
            <button class="button button-secondary" @click="handleSaveConfig">Save Config</button>
            <button class="button button-secondary" @click="handleClearConfig">Clear Config</button>
          </div>
        </section>

        <section class="panel-soft detail-panel">
          <div class="section-row">
            <div>
              <p class="eyebrow">Snapshot</p>
              <h3>Current Summary</h3>
            </div>
          </div>
          <div class="summary-list">
            <div v-for="item in configSummary" :key="item.label" class="summary-row">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>
        </section>
      </aside>
    </div>

    <RunDiagnosticsPanel
      :statuses="statuses"
      :traces="traces"
      :trace-error="traceError"
      :compact="true"
      empty-trace-message="Trace records appear here once the task starts running."
    />
  </div>
</template>