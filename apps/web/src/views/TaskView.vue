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

async function runAnalyze(paperId, mode, modelConfig) {
  addStatus(`开始执行分析阶段（${mode}）...`)
  const data = await callApi(form.value.apiBase, '/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper_id: paperId, mode, model_config: modelConfig })
  }, TIMEOUT_ANALYZE_MS)
  stageState.value.analyze = true
  addStatus('分析阶段完成。')
  emitStageMessages(data, 'analyze')
}

async function runReview(paperId, modelConfig) {
  addStatus('开始执行审阅阶段...')
  const data = await callApi(form.value.apiBase, '/review', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper_id: paperId, model_config: modelConfig })
  }, TIMEOUT_REVIEW_MS)
  stageState.value.review = true
  addStatus('审阅阶段完成。')
  emitStageMessages(data, 'review')
}

async function runFinalize(paperId, mode, modelConfig) {
  addStatus('开始执行整理阶段...')
  const data = await callApi(form.value.apiBase, '/finalize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper_id: paperId, strict: mode === 'strict', model_config: modelConfig })
  }, TIMEOUT_FINALIZE_MS)
  stageState.value.finalize = true
  addStatus('整理阶段完成。')
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
    addStatus(`本次配置：模型 A=${modelConfig.primary.model} | 模型 B=${modelConfig.secondary.model} | 模式=${mode}`)

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
      addStatus('后端可能仍在处理中，正在跳转到结果页继续查看。')
      saveLastResult({ paper_id: currentPaperId.value, api_base: form.value.apiBase })
      await router.push({ name: 'results', query: { paper_id: currentPaperId.value, api_base: form.value.apiBase } })
      return
    }
    stopPolling()
    addStatus(`错误：${error.message}`)
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
        <p class="eyebrow">鐮旂┒杩愯鎺у埗鍙</p>
        <h1>AI 璁烘枃鏁欑粌</h1>
      </div>
      <div class="topbar-search">鎼滅储璁烘枃銆佸巻鍙茶褰曞拰鏈湴鏂囦欢璧勬簮</div>
      <div class="topbar-actions">
        <span class="status-pill" :class="isRunning ? 'status-pill-live' : 'status-pill-idle'">
          {{ isRunning ? '运行中...' : '开始运行' }}
        </span>
        <button class="button button-secondary" :disabled="checkingApi" @click="handleCheckApiConnection">{{ checkingApi ? '验证中...' : '验证 API 连通' }}</button>
        <button class="button button-secondary" @click="handleValidateConfig">检测模型接口</button>
        <button class="button button-primary" :disabled="isRunning" @click="runPipeline">
          {{ isRunning ? '运行中...' : '开始运行' }}
        </button>
      </div>
    </header>

    <div class="workspace-grid">
      <aside class="workspace-sidebar">
        <section class="sidebar-section">
          <p class="sidebar-title">瀵艰埅</p>
          <div class="nav-list">
            <RouterLink class="nav-item nav-item-active" :to="{ name: 'task' }">鎺у埗鍙</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'history', query: { api_base: form.apiBase } }">鍘嗗彶璁板綍</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'saved', query: { api_base: form.apiBase } }">宸蹭繚瀛樻姤鍛</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'uploads', query: { api_base: form.apiBase } }">涓婁紶鏂囦欢</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'cache', query: { api_base: form.apiBase } }">缂撳瓨璧勬簮</RouterLink>
          </div>
        </section>

        <section class="sidebar-section">
          <div class="section-row">
            <p class="sidebar-title">鏈€杩戝巻鍙</p>
            <span class="sidebar-meta">{{ historyRecords.length }} 鏉</span>
          </div>
          <div class="history-list">
            <button v-for="item in historyRecords" :key="item.record_id" class="history-item button-plain" @click="openHistoryRecord(item.record_id)">
              <div>
                <strong>{{ item.title }}</strong>
                <p>{{ item.saved_at || item.status || '-' }}</p>
              </div>
              <span class="history-dot"></span>
            </button>
            <div v-if="!historyRecords.length" class="history-empty">杩樻病鏈夊巻鍙茶褰曘€</div>
          </div>
        </section>
      </aside>

      <main class="workspace-main">
        <section class="hero-panel panel-soft">
          <div>
            <p class="eyebrow">褰撳墠浼氳瘽</p>
            <h2>璁烘枃鎺у埗鍙</h2>
            <p class="panel-subtitle">瀵煎叆璁烘枃銆侀厤缃弻妯″瀷銆佹墽琛屽畬鏁存祦姘寸嚎锛屽苟鎶婃瘡娆＄粨鏋滀繚瀛樺埌鏈湴鍘嗗彶涓€</p>
          </div>
          <div class="hero-meta-grid">
            <div>
              <span class="meta-label">褰撳墠璁烘枃 ID</span>
              <strong>{{ currentPaperId || '-' }}</strong>
            </div>
            <div>
              <span class="meta-label">杩愯妯″紡</span>
              <strong>{{ form.runMode || 'deep' }}</strong>
            </div>
            <div>
              <span class="meta-label">杈撳叆鏉ユ簮</span>
              <strong>{{ paperFile ? '涓婁紶 PDF' : (form.paperUrl ? '杩滅▼閾炬帴' : '鏈€夋嫨') }}</strong>
            </div>
          </div>
        </section>

        <section class="panel-soft">
          <div class="section-row">
            <div>
              <p class="eyebrow">娴佹按绾</p>
              <h3>闃舵杩涘害</h3>
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
              <p class="eyebrow">浠诲姟杈撳叆</p>
              <h3>杩愯鍙傛暟</h3>
            </div>
          </div>
          <div class="form-grid control-grid">
            <label class="field span-two">
              <span>鍚庣鎺ュ彛鍦板潃</span>
              <input v-model="form.apiBase" autocomplete="off" />
            </label>
            <label class="field span-two">
              <span>璁烘枃閾炬帴</span>
              <input v-model="form.paperUrl" placeholder="arXiv 閾炬帴鎴栫洿鎺?PDF 閾炬帴" autocomplete="off" />
            </label>
            <label class="field">
              <span>涓婁紶 PDF</span>
              <input type="file" accept="application/pdf" @change="onFileChange" />
            </label>
            <label class="field">
              <span>杩愯妯″紡</span>
              <select v-model="form.runMode">
                <option value="deep">绮捐妯″紡</option>
                <option value="full">鍏ㄩ噺妯″紡</option>
                <option value="fast">蹇€熸ā寮</option>
              </select>
            </label>
          </div>
        </section>
      </main>

      <aside class="workspace-detail">
        <section class="panel-soft detail-panel">
          <div class="section-row">
            <div>
              <p class="eyebrow">杩愯閰嶇疆</p>
              <h3>妯″瀷涓庡瘑閽</h3>
            </div>
          </div>
          <div class="detail-stack">
            <label class="field">
              <span>妯″瀷 A 鎺ュ彛鍦板潃</span>
              <input v-model="form.qwenBase" autocomplete="off" />
            </label>
            <label class="field">
              <span>妯″瀷 A 瀵嗛挜</span>
              <input v-model="form.qwenKey" type="password" autocomplete="off" />
            </label>
            <label class="field">
              <span>妯″瀷 A 鍚嶇О</span>
              <input v-model="form.qwenModel" autocomplete="off" />
            </label>
            <label class="field">
              <span>妯″瀷 B 鎺ュ彛鍦板潃</span>
              <input v-model="form.minimaxBase" autocomplete="off" />
            </label>
            <label class="field">
              <span>妯″瀷 B 瀵嗛挜</span>
              <input v-model="form.minimaxKey" type="password" autocomplete="off" />
            </label>
            <label class="field">
              <span>妯″瀷 B 鍚嶇О</span>
              <input v-model="form.minimaxModel" autocomplete="off" />
            </label>
          </div>
          <div class="button-column">
            <button class="button button-secondary" @click="handleSaveConfig">淇濆瓨閰嶇疆</button>
            <button class="button button-secondary" @click="handleClearConfig">娓呯┖閰嶇疆</button>
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










