<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

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
const apiBaseRef = computed(() => form.value.apiBase)

function addStatus(message) {
  const timestamp = new Date().toLocaleTimeString()
  statuses.value.unshift(`${timestamp} - ${message}`)
}

const {
  traces,
  traceError,
  startPolling,
  stopPolling
} = useTraceHistory({
  paperIdRef: currentPaperId,
  apiBaseRef,
  addStatus
})

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
  addStatus('模型配置已保存到浏览器本地。')
}

function handleClearConfig() {
  const next = clearModelConfig()
  form.value = { ...defaultFormState(), ...next, apiBase: form.value.apiBase }
  addStatus('本地模型配置已清空。')
}

async function handleValidateConfig() {
  try {
    addStatus('开始验证模型 API...')
    const data = await callApi(form.value.apiBase, '/validate-models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_config: currentModelConfig() })
    })

    if (Array.isArray(data.results)) {
      for (const item of data.results) {
        if (item.ok) {
          addStatus(`验证通过：${item.display_name || item.provider} (${item.latency_ms}ms) base=${item.base_url || '<empty>'} model=${item.model}`)
        } else {
          addStatus(`验证失败：${item.display_name || item.provider} - ${item.error || 'unknown error'}`)
        }
      }
    }

    addStatus(data.ok ? 'API 验证完成：全部通过。' : 'API 验证完成：存在失败，请检查 base_url / model / api_key。')
  } catch (error) {
    addStatus(`API 验证请求失败：${error.message}`)
  }
}

async function ingest() {
  const url = String(form.value.paperUrl || '').trim()
  if (!url && !paperFile.value) {
    throw new Error('请至少提供论文链接或 PDF 文件。')
  }

  addStatus('正在导入输入...')

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
    throw new Error('导入成功但后端未返回 paper_id。')
  }

  setPaperId(paperId)
  startPolling()
  addStatus(`导入完成，paper_id=${paperId}`)
  return paperId
}

function emitStageMessages(data, fallbackStage) {
  if (Array.isArray(data?.warnings)) {
    data.warnings.forEach((warning) => addStatus(`提示：${warning}`))
  }

  if (data?.stage_metrics) {
    const metrics = data.stage_metrics
    addStatus(`阶段指标：${metrics.stage || fallbackStage || '-'} 输入=${Number(metrics.input_chars || 0)} 输出=${Number(metrics.output_chars || 0)} 耗时=${Number(metrics.elapsed_ms || 0)}ms`)
  }
}

async function runAnalyze(paperId, mode, modelConfig) {
  addStatus(`开始分析阶段（${mode}）...`)
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
  addStatus('分析阶段完成。')
  emitStageMessages(data, 'analyze')
}

async function runReview(paperId, modelConfig) {
  addStatus('开始审稿阶段（Model B）...')
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
  addStatus('审稿阶段完成。')
  emitStageMessages(data, 'review')
}

async function runFinalize(paperId, mode, modelConfig) {
  addStatus('开始补丁收敛阶段...')
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
  addStatus('补丁收敛阶段完成。')
  emitStageMessages(data, 'finalize')
}

async function runPipeline() {
  try {
    isRunning.value = true
    statuses.value = []
    stopPolling()

    const mode = form.value.runMode || 'deep'
    const modelConfig = currentModelConfig()
    addStatus(`本次路由：Model A=${modelConfig.primary.base_url} (${modelConfig.primary.model}) | Model B=${modelConfig.secondary.base_url} (${modelConfig.secondary.model}) | 模式=${mode}`)

    const paperId = await ingest()
    await runAnalyze(paperId, mode, modelConfig)

    if (mode !== 'fast') {
      await runReview(paperId, modelConfig)
      await runFinalize(paperId, mode, modelConfig)
    }

    stopPolling()
    saveLastResult({ paper_id: paperId, api_base: form.value.apiBase })
    await router.push({ name: 'results', query: { paper_id: paperId, api_base: form.value.apiBase } })
  } catch (error) {
    if (isTimeoutError(error) && currentPaperId.value) {
      addStatus(`提示：${error.message}`)
      addStatus('提示：后端可能仍在处理中，自动跳转结果页继续观察实时讯息。')
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

addStatus('页面已就绪。提交任务后会跳转到结果页。')
</script>

<template>
  <div class="page-shell">
    <header class="page-header">
      <div>
        <p class="eyebrow">Student-Oriented Reading Agent</p>
        <h1>AI Paper Coach</h1>
      </div>
      <p class="header-note">Vue 单页版前端，保留现有 API 协议与链路。</p>
    </header>

    <main class="page-main">
      <section class="panel">
        <div class="panel-heading">
          <div>
            <h2>任务输入</h2>
            <p class="panel-subtitle">提交论文、设置 API、选择运行模式。</p>
          </div>
        </div>

        <div class="form-grid two-column">
          <label class="field">
            <span>后端 API 地址</span>
            <input v-model="form.apiBase" autocomplete="off" />
          </label>

          <label class="field field-readonly">
            <span>链路说明</span>
            <div class="static-value">精读模式（Model A -> Model B -> Model A）</div>
          </label>

          <label class="field">
            <span>论文链接（可选）</span>
            <input v-model="form.paperUrl" placeholder="arXiv / PDF URL" autocomplete="off" />
          </label>

          <label class="field">
            <span>上传论文 PDF（可选）</span>
            <input type="file" accept="application/pdf" @change="onFileChange" />
          </label>
        </div>

        <div class="button-row split-row">
          <button class="button button-primary" :disabled="isRunning" @click="runPipeline">
            {{ isRunning ? '运行中...' : '运行整条流程' }}
          </button>
          <div class="hint-card">运行完成后会自动跳转到结果页。</div>
        </div>

        <div class="meta-card">
          <span class="field-label">当前 Paper ID</span>
          <strong>{{ currentPaperId || '-' }}</strong>
        </div>
      </section>

      <section class="panel">
        <div class="panel-heading">
          <div>
            <h2>模型配置</h2>
            <p class="panel-subtitle">这里保留现有配置字段，但结构已经拆到 Vue 状态里。</p>
          </div>
        </div>

        <div class="form-grid two-column">
          <div class="sub-card">
            <h3>Model A</h3>
            <label class="field">
              <span>Base URL</span>
              <input v-model="form.qwenBase" autocomplete="off" />
            </label>
            <label class="field">
              <span>API Key</span>
              <input v-model="form.qwenKey" type="password" autocomplete="off" />
            </label>
            <label class="field">
              <span>Model</span>
              <input v-model="form.qwenModel" autocomplete="off" />
            </label>
          </div>

          <div class="sub-card">
            <h3>Model B</h3>
            <label class="field">
              <span>Base URL</span>
              <input v-model="form.minimaxBase" autocomplete="off" />
            </label>
            <label class="field">
              <span>API Key</span>
              <input v-model="form.minimaxKey" type="password" autocomplete="off" />
            </label>
            <label class="field">
              <span>Model</span>
              <input v-model="form.minimaxModel" autocomplete="off" />
            </label>
          </div>
        </div>

        <div class="button-row">
          <button class="button button-secondary" @click="handleSaveConfig">保存模型配置到本地</button>
          <button class="button button-secondary" @click="handleClearConfig">清空本地模型配置</button>
          <button class="button button-secondary" @click="handleValidateConfig">验证 API 连通性</button>
        </div>

        <label class="field field-compact">
          <span>运行模式</span>
          <select v-model="form.runMode">
            <option value="deep">精读模式（默认）</option>
            <option value="full">全论文切片模式</option>
            <option value="fast">快速模式</option>
          </select>
        </label>
      </section>

      <RunDiagnosticsPanel
        :statuses="statuses"
        :traces="traces"
        :trace-error="traceError"
        empty-trace-message="等待任务开始，导入论文后会显示模型往返记录。"
      />
    </main>
  </div>
</template>


