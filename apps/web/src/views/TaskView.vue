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

const JOB_POLL_INTERVAL_MS = 1500
const JOB_POLL_TIMEOUT_MS = 1800000

const router = useRouter()
const form = ref(loadModelConfig())
const statuses = ref([])
const currentPaperId = ref('')
const paperFile = ref(null)
const isRunning = ref(false)
const checkingApi = ref(false)
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
  { key: 'ingest', label: '导入', done: stageState.value.ingest },
  { key: 'analyze', label: '分析', done: stageState.value.analyze },
  { key: 'review', label: '审阅', done: stageState.value.review },
  { key: 'finalize', label: '整理', done: stageState.value.finalize }
])

function resetStageState() {
  stageState.value = { ingest: false, analyze: false, review: false, finalize: false }
}

async function loadHistoryRecords() {
  try {
    const data = await callApi(form.value.apiBase, '/history')
    historyRecords.value = Array.isArray(data.items) ? data.items : []
  } catch (error) {
    addStatus(`历史记录加载失败：${error.message}`)
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
  addStatus('模型配置已保存到本地。')
}

function handleClearConfig() {
  const next = clearModelConfig()
  form.value = { ...defaultFormState(), ...next, apiBase: form.value.apiBase }
  addStatus('模型配置已从本地清除。')
}

async function handleCheckApiConnection() {
  if (checkingApi.value) return
  checkingApi.value = true
  try {
    addStatus('开始验证 API 连通性...')
    const data = await callApi(form.value.apiBase, '/health')
    if (data?.ok) {
      addStatus(`API 连通正常：${data.service || '服务'} v${data.version || '-'}`)
    } else {
      addStatus('API 已响应，但返回状态异常。')
    }
  } catch (error) {
    addStatus(`API 连通验证失败：${error.message}`)
  } finally {
    checkingApi.value = false
  }
}

async function handleValidateConfig() {
  try {
    addStatus('开始校验模型接口配置...')
    const data = await callApi(form.value.apiBase, '/validate-models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_config: currentModelConfig() })
    })

    if (Array.isArray(data.results)) {
      for (const item of data.results) {
        if (item.ok) {
          addStatus(`校验通过：${item.display_name || item.provider}，${item.latency_ms} ms`)
        } else {
          addStatus(`校验失败：${item.display_name || item.provider} - ${item.error || '未知错误'}`)
        }
      }
    }

    addStatus(data.ok ? '模型接口校验完成，全部通过。' : '模型接口校验完成，存在失败项。')
  } catch (error) {
    addStatus(`模型接口校验请求失败：${error.message}`)
  }
}

async function ingest() {
  const url = String(form.value.paperUrl || '').trim()
  if (!url && !paperFile.value) {
    throw new Error('请提供论文链接或上传 PDF 文件。')
  }

  addStatus('正在导入论文输入...')

  let payload
  if (paperFile.value) {
    const formData = new FormData()
    formData.append('file', paperFile.value)
    if (url) formData.append('url', url)
    payload = await callApi(form.value.apiBase, '/ingest', { method: 'POST', body: formData })
  } else {
    payload = await callApi(form.value.apiBase, '/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    })
  }

  const paperId = payload.paper_id || payload.id || payload.paperId
  if (!paperId) throw new Error('导入成功，但后端没有返回 paper_id。')

  setPaperId(paperId)
  stageState.value.ingest = true
  startPolling()
  addStatus(`导入完成：paper_id=${paperId}`)
  return paperId
}

function emitStageMessages(data, fallbackStage) {
  if (Array.isArray(data?.warnings)) data.warnings.forEach((warning) => addStatus(`提示：${warning}`))
  if (data?.stage_metrics) {
    const metrics = data.stage_metrics
    addStatus(`阶段指标：${metrics.stage || fallbackStage || '-'} 输入=${Number(metrics.input_chars || 0)} 输出=${Number(metrics.output_chars || 0)} 耗时=${Number(metrics.elapsed_ms || 0)} ms`)
  }
}

function sleep(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

function consumePipelineEvents(events, seenEventIds) {
  for (const event of Array.isArray(events) ? events : []) {
    const eventId = Number(event?.id || 0)
    if (eventId > 0 && seenEventIds.has(eventId)) continue
    if (eventId > 0) seenEventIds.add(eventId)

    const stage = event?.stage
    const message = event?.message
    if (message) addStatus(message)

    if (event?.type === 'stage_started' && stage) {
      addStatus(`\u9636\u6bb5\u5f00\u59cb\uff1a${stage}`)
    }

    if (event?.type === 'stage_completed' && stage) {
      if (Object.prototype.hasOwnProperty.call(stageState.value, stage)) {
        stageState.value[stage] = true
      }
      addStatus(`\u9636\u6bb5\u5b8c\u6210\uff1a${stage}`)
      emitStageMessages(event?.data || {}, stage)
    }

    if (event?.type === 'failed') {
      addStatus(`\u540e\u53f0\u4efb\u52a1\u5931\u8d25\uff1a${message || '\u672a\u77e5\u9519\u8bef'}`)
    }

    if (event?.type === 'completed') {
      addStatus('\u540e\u53f0\u4efb\u52a1\u6267\u884c\u5b8c\u6210\u3002')
    }
  }
}

async function startPipelineJob(paperId, mode, modelConfig) {
  addStatus('\u6b63\u5728\u63d0\u4ea4\u540e\u53f0\u5f02\u6b65\u4efb\u52a1...')
  const data = await callApi(form.value.apiBase, '/pipeline/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      paper_id: paperId,
      mode,
      strict: mode === 'strict',
      model_config: modelConfig
    })
  })

  const jobId = data?.job_id
  if (!jobId) throw new Error('\u4efb\u52a1\u63d0\u4ea4\u6210\u529f\uff0c\u4f46\u540e\u7aef\u672a\u8fd4\u56de job_id\u3002')

  addStatus(`\u4efb\u52a1\u5df2\u63d0\u4ea4\uff1ajob_id=${jobId}`)
  return jobId
}

async function waitPipelineJob(jobId) {
  const startAt = Date.now()
  const seenEventIds = new Set()
  let warnedRetry = false

  while (true) {
    if (Date.now() - startAt > JOB_POLL_TIMEOUT_MS) {
      throw new Error(`\u540e\u53f0\u4efb\u52a1\u7b49\u5f85\u8d85\u65f6\uff08${Math.floor(JOB_POLL_TIMEOUT_MS / 1000)} \u79d2\uff09`)
    }

    let snapshot
    try {
      snapshot = await callApi(
        form.value.apiBase,
        `/pipeline/jobs/${encodeURIComponent(jobId)}`,
        {},
        30000
      )
      warnedRetry = false
    } catch (error) {
      if (isTimeoutError(error)) {
        if (!warnedRetry) {
          addStatus('\u4efb\u52a1\u72b6\u6001\u62c9\u53d6\u8d85\u65f6\uff0c\u6b63\u5728\u81ea\u52a8\u91cd\u8bd5...')
          warnedRetry = true
        }
        await sleep(1000)
        continue
      }
      throw error
    }

    consumePipelineEvents(snapshot?.events, seenEventIds)

    if (snapshot?.status === 'completed') {
      return snapshot?.result || null
    }

    if (snapshot?.status === 'failed') {
      throw new Error(snapshot?.error || '\u540e\u53f0\u4efb\u52a1\u6267\u884c\u5931\u8d25')
    }

    await sleep(JOB_POLL_INTERVAL_MS)
  }
}

async function runPipeline() {
  try {
    isRunning.value = true
    statuses.value = []
    resetStageState()
    stopPolling()

    const mode = form.value.runMode || 'deep'
    const modelConfig = currentModelConfig()
    addStatus(`\u672c\u6b21\u914d\u7f6e\uff1a\u6a21\u578b A=${modelConfig.primary.model} | \u6a21\u578b B=${modelConfig.secondary.model} | \u6a21\u5f0f=${mode}`)

    const paperId = await ingest()
    const jobId = await startPipelineJob(paperId, mode, modelConfig)
    const result = await waitPipelineJob(jobId)

    if (mode === 'fast' && stageState.value.analyze) {
      stageState.value.review = false
      stageState.value.finalize = false
    }

    stopPolling()
    await loadHistoryRecords()

    const resultPaperId = result?.paper_id || paperId
    saveLastResult({ paper_id: resultPaperId, api_base: form.value.apiBase })
    await router.push({ name: 'results', query: { paper_id: resultPaperId, api_base: form.value.apiBase } })
  } catch (error) {
    if (currentPaperId.value) {
      addStatus(`\u9519\u8bef\uff1a${error.message}`)
      addStatus('\u53ef\u4ee5\u7a0d\u540e\u5728\u5386\u53f2\u8bb0\u5f55\u6216\u7ed3\u679c\u9875\u7ee7\u7eed\u67e5\u770b\u4efb\u52a1\u72b6\u6001\u3002')
      saveLastResult({ paper_id: currentPaperId.value, api_base: form.value.apiBase })
    } else {
      addStatus(`\u9519\u8bef\uff1a${error.message}`)
    }
    stopPolling()
  } finally {
    isRunning.value = false
  }
}

onMounted(() => {
  loadHistoryRecords()
  addStatus('控制台已就绪，可以开始新任务或打开历史记录。')
})
</script>

<template>
  <div class="workspace-shell">
    <header class="topbar">
      <div class="brand-block">
        <p class="eyebrow">研究运行控制台</p>
        <h1>AI 论文教练</h1>
      </div>
      <div class="topbar-search">搜索论文、历史记录和本地文件资源</div>
      <div class="topbar-actions">
        <span class="status-pill" :class="isRunning ? 'status-pill-live' : 'status-pill-idle'">
          {{ isRunning ? '任务运行中' : '系统待命' }}
        </span>
        <button class="button button-secondary" :disabled="checkingApi" @click="handleCheckApiConnection">
          {{ checkingApi ? '验证中...' : '验证 API 连通' }}
        </button>
        <button class="button button-secondary" @click="handleValidateConfig">检测模型接口</button>
        <button class="button button-primary" :disabled="isRunning" @click="runPipeline">
          {{ isRunning ? '运行中...' : '开始运行' }}
        </button>
      </div>
    </header>

    <div class="workspace-grid">
      <aside class="workspace-sidebar">
        <section class="sidebar-section">
          <p class="sidebar-title">导航</p>
          <div class="nav-list">
            <RouterLink class="nav-item nav-item-active" :to="{ name: 'task' }">控制台</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'history', query: { api_base: form.apiBase } }">历史记录</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'saved', query: { api_base: form.apiBase } }">已保存报告</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'uploads', query: { api_base: form.apiBase } }">上传文件</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'cache', query: { api_base: form.apiBase } }">缓存资源</RouterLink>
          </div>
        </section>

        <section class="sidebar-section">
          <div class="section-row">
            <p class="sidebar-title">最近历史</p>
            <span class="sidebar-meta">{{ historyRecords.length }} 条</span>
          </div>
          <div class="history-list">
            <button v-for="item in historyRecords" :key="item.record_id" class="history-item button-plain" @click="openHistoryRecord(item.record_id)">
              <div>
                <strong>{{ item.title }}</strong>
                <p>{{ item.saved_at || item.status || '-' }}</p>
              </div>
              <span class="history-dot"></span>
            </button>
            <div v-if="!historyRecords.length" class="history-empty">还没有历史记录。</div>
          </div>
        </section>
      </aside>

      <main class="workspace-main">
        <section class="hero-panel panel-soft">
          <div>
            <p class="eyebrow">当前会话</p>
            <h2>论文控制台</h2>
            <p class="panel-subtitle">导入论文、配置双模型、执行完整流水线，并把每次结果保存到本地历史中。</p>
          </div>
          <div class="hero-meta-grid">
            <div>
              <span class="meta-label">当前论文 ID</span>
              <strong>{{ currentPaperId || '-' }}</strong>
            </div>
            <div>
              <span class="meta-label">运行模式</span>
              <strong>{{ form.runMode || 'deep' }}</strong>
            </div>
            <div>
              <span class="meta-label">输入来源</span>
              <strong>{{ paperFile ? '上传 PDF' : (form.paperUrl ? '远程链接' : '未选择') }}</strong>
            </div>
          </div>
        </section>

        <section class="panel-soft">
          <div class="section-row">
            <div>
              <p class="eyebrow">流水线</p>
              <h3>阶段进度</h3>
            </div>
          </div>
          <div class="pipeline-row">
            <div v-for="step in pipelineSteps" :key="step.key" class="pipeline-step" :class="{ 'pipeline-step-done': step.done }">
              <span class="pipeline-badge">{{ step.done ? '已完成' : '待执行' }}</span>
              <strong>{{ step.label }}</strong>
            </div>
          </div>
        </section>

        <section class="panel-soft">
          <div class="section-row">
            <div>
              <p class="eyebrow">任务输入</p>
              <h3>运行参数</h3>
            </div>
          </div>
          <div class="form-grid control-grid">
            <label class="field span-two">
              <span>后端接口地址</span>
              <input v-model="form.apiBase" autocomplete="off" />
            </label>
            <label class="field span-two">
              <span>论文链接</span>
              <input v-model="form.paperUrl" placeholder="arXiv 链接或直接 PDF 链接" autocomplete="off" />
            </label>
            <label class="field">
              <span>上传 PDF</span>
              <input type="file" accept="application/pdf" @change="onFileChange" />
            </label>
            <label class="field">
              <span>运行模式</span>
              <select v-model="form.runMode">
                <option value="deep">精读模式</option>
                <option value="full">全量模式</option>
                <option value="fast">快速模式</option>
              </select>
            </label>
          </div>
        </section>
      </main>

      <aside class="workspace-detail">
        <section class="panel-soft detail-panel">
          <div class="section-row">
            <div>
              <p class="eyebrow">运行配置</p>
              <h3>模型与密钥</h3>
            </div>
          </div>
          <div class="detail-stack">
            <label class="field">
              <span>模型 A 接口地址</span>
              <input v-model="form.qwenBase" autocomplete="off" />
            </label>
            <label class="field">
              <span>模型 A 密钥</span>
              <input v-model="form.qwenKey" type="password" autocomplete="off" />
            </label>
            <label class="field">
              <span>模型 A 名称</span>
              <input v-model="form.qwenModel" autocomplete="off" />
            </label>
            <label class="field">
              <span>模型 B 接口地址</span>
              <input v-model="form.minimaxBase" autocomplete="off" />
            </label>
            <label class="field">
              <span>模型 B 密钥</span>
              <input v-model="form.minimaxKey" type="password" autocomplete="off" />
            </label>
            <label class="field">
              <span>模型 B 名称</span>
              <input v-model="form.minimaxModel" autocomplete="off" />
            </label>
          </div>
          <div class="button-column">
            <button class="button button-secondary" @click="handleSaveConfig">保存配置</button>
            <button class="button button-secondary" @click="handleClearConfig">清空配置</button>
          </div>
        </section>
      </aside>
    </div>

    <div class="workspace-wide-panel">
      <RunDiagnosticsPanel
        :statuses="statuses"
        :traces="traces"
        :trace-error="traceError"
        :compact="true"
        empty-trace-message="任务开始后，这里会显示调用轨迹和日志。"
      />
    </div>
  </div>
</template>
