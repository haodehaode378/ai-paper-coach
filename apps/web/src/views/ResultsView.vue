<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import RunDiagnosticsPanel from '../components/RunDiagnosticsPanel.vue'
import { callApi } from '../lib/api'
import { buildModelConfig, loadLastResult, loadModelConfig } from '../lib/storage'
import { useTraceHistory } from '../composables/useTraceHistory'

const CHAT_WIDTH_KEY = 'apc_report_chat_width_v1'
const CHAT_OPEN_KEY = 'apc_report_chat_open_v1'

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
const activeTab = ref('checks')
const activeQuestionKey = ref('q1_problem_and_novelty')

const chatInput = ref('')
const chatLoading = ref(false)
const includeHistoryContext = ref(true)
const includePapersContext = ref(true)
const chatOpen = ref(localStorage.getItem(CHAT_OPEN_KEY) !== '0')
const chatWidth = ref(Number(localStorage.getItem(CHAT_WIDTH_KEY) || 380))
const chatListRef = ref(null)
const chatMessages = ref([])
let resizing = false

const questionMeta = [
  { key: 'q1_problem_and_novelty', title: '问题一', short: '问题与创新' },
  { key: 'q2_related_work_and_researchers', title: '问题二', short: '相关工作' },
  { key: 'q3_key_idea', title: '问题三', short: '核心思路' },
  { key: 'q4_experiment_design', title: '问题四', short: '实验设计' },
  { key: 'q5_dataset_and_code', title: '问题五', short: '数据与代码' },
  { key: 'q6_support_for_claims', title: '问题六', short: '结论支撑' },
  { key: 'q7_contribution_and_next_step', title: '问题七', short: '贡献与下一步' },
]

function createStarterMessage() {
  return {
    role: 'assistant',
    content: '你好，我可以基于当前报告与你对话。你可以让我总结创新点、整理复现步骤、检查缺项，或追问七问里的任何部分。',
  }
}

function resetChatSession() {
  chatMessages.value = [createStarterMessage()]
  chatInput.value = ''
}

resetChatSession()

function addStatus(message) {
  const timestamp = new Date().toLocaleTimeString()
  statuses.value.unshift(`${timestamp} - ${message}`)
}

const { traces, traceError, startPolling, stopPolling, fetchTraces } = useTraceHistory({
  paperIdRef: paperId,
  apiBaseRef: apiBase,
  addStatus,
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
  if (querySavedId && queryApiBase) return { saved_id: String(querySavedId), api_base: String(queryApiBase) }
  if (queryRecordId && queryApiBase) return { record_id: String(queryRecordId), api_base: String(queryApiBase) }
  if (queryPaperId && queryApiBase) return { paper_id: String(queryPaperId), api_base: String(queryApiBase) }
  return loadLastResult()
})

const paperMetaLine = computed(() => {
  if (!paperId.value) return '等待载入报告。'
  const title = report.value?.paper_meta?.title || '未命名论文'
  return `论文 ID：${paperId.value} | 标题：${title}`
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

  const checks = [
    { key: 'three_minute_summary.problem', title: '摘要：论文问题与目标', min: 1000, actual: textLen(summary.problem || '') },
    { key: 'reproduction_guide.total', title: '复现指导：整体内容', min: 1000, actual: reproductionTotal },
  ]

  questionMeta.forEach((item) => {
    checks.push({
      key: item.key,
      title: `七问：${item.short}`,
      min: 700,
      actual: textLen(readingQa[item.key] || ''),
    })
  })

  return checks.map((item) => ({ ...item, ok: item.actual >= item.min }))
})

const summaryBlocks = computed(() => {
  const summary = report.value?.three_minute_summary || {}
  return [
    { title: '论文问题与目标', type: 'text', value: summary.problem || '-' },
    { title: '方法要点', type: 'list', value: summary.method_points || [] },
    { title: '关键结果', type: 'list', value: summary.key_results || [] },
  ]
})

const reproductionBlocks = computed(() => {
  const reproduction = report.value?.reproduction_guide || {}
  return [
    { title: '环境要求', type: 'text', value: reproduction.environment || '-' },
    { title: '数据集', type: 'text', value: reproduction.dataset || '-' },
    { title: '执行命令', type: 'list', value: reproduction.commands || [] },
    { title: '关键超参数', type: 'list', value: reproduction.key_hyperparams || [] },
    { title: '结果范围', type: 'text', value: reproduction.expected_range || '-' },
    { title: '常见问题', type: 'list', value: reproduction.common_errors || [] },
  ]
})

const activeQuestion = computed(() => {
  const readingQa = report.value?.reading_qa || {}
  const meta = questionMeta.find((item) => item.key === activeQuestionKey.value) || questionMeta[0]
  return { ...meta, value: readingQa[meta.key] || '-' }
})

const reportStats = computed(() => [
  { label: '载入状态', value: report.value ? '已载入' : '未载入' },
  { label: '要求检查', value: requirementChecks.value.every((item) => item.ok) ? '通过' : '需补充' },
  { label: 'Trace 数量', value: `${traces.value.length}` },
  { label: '记录 ID', value: activeRecordId.value || '-' },
])

const chatContextSummary = computed(() => {
  const parts = ['当前报告']
  if (includeHistoryContext.value) parts.push('历史记录')
  if (includePapersContext.value) parts.push('论文库')
  return parts.join(' + ')
})

function toggleChat() {
  chatOpen.value = !chatOpen.value
  localStorage.setItem(CHAT_OPEN_KEY, chatOpen.value ? '1' : '0')
  if (chatOpen.value) nextTick(scrollChatToBottom)
}

function openChat() {
  if (chatOpen.value) return
  chatOpen.value = true
  localStorage.setItem(CHAT_OPEN_KEY, '1')
  nextTick(scrollChatToBottom)
}

function clearChat() {
  resetChatSession()
}

function startResize(event) {
  resizing = true
  document.body.style.cursor = 'col-resize'
  window.addEventListener('pointermove', onResize)
  window.addEventListener('pointerup', stopResize)
  event.preventDefault()
}

function onResize(event) {
  if (!resizing) return
  const width = Math.min(Math.max(window.innerWidth - event.clientX - 24, 320), 620)
  chatWidth.value = width
  localStorage.setItem(CHAT_WIDTH_KEY, String(width))
}

function stopResize() {
  resizing = false
  document.body.style.cursor = ''
  window.removeEventListener('pointermove', onResize)
  window.removeEventListener('pointerup', stopResize)
}

function fillPrompt(text) {
  chatInput.value = text
}

function scrollChatToBottom() {
  const node = chatListRef.value
  if (!node) return
  node.scrollTop = node.scrollHeight
}

function buildChatPayload(messages) {
  const formState = loadModelConfig()
  return {
    report: report.value,
    messages,
    include_history: includeHistoryContext.value,
    include_papers: includePapersContext.value,
    model_config: buildModelConfig(formState),
  }
}

function extractErrorText(text) {
  try {
    const parsed = JSON.parse(text)
    return parsed?.detail || parsed?.error || text
  } catch {
    return text
  }
}

async function streamChatReply(base, payload, userTurns) {
  const response = await fetch(`${String(base || '').trim().replace(/\/$/, '')}/chat/report/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!response.ok) {
    const text = await response.text()
    throw new Error(extractErrorText(text) || `${response.status} ${response.statusText}`)
  }
  if (!response.body) {
    throw new Error('浏览器不支持流式响应。')
  }

  const assistantMessage = { role: 'assistant', content: '' }
  chatMessages.value = [...userTurns, assistantMessage]
  await nextTick()
  scrollChatToBottom()

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const applyEvent = (raw) => {
    const line = raw.trim()
    if (!line.startsWith('data:')) return
    const data = line.slice(5).trim()
    if (!data || data === '[DONE]') return
    const payloadObj = JSON.parse(data)
    if (payloadObj.error) throw new Error(payloadObj.error)
    const delta = String(payloadObj.delta || '')
    if (!delta) return
    assistantMessage.content += delta
    chatMessages.value = [...userTurns, { ...assistantMessage }]
  }

  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''
    for (const part of parts) applyEvent(part)
    await nextTick()
    scrollChatToBottom()
    if (done) break
  }

  if (buffer.trim()) applyEvent(buffer)
  if (!assistantMessage.content.trim()) throw new Error('助手没有返回内容。')
  chatMessages.value = [...userTurns, { ...assistantMessage }]
}

async function sendChat() {
  const message = chatInput.value.trim()
  if (!message || chatLoading.value || !report.value) return

  const userTurns = [...chatMessages.value, { role: 'user', content: message }]
  chatMessages.value = userTurns
  chatInput.value = ''
  chatLoading.value = true
  await nextTick()
  scrollChatToBottom()

  try {
    await streamChatReply(apiBase.value, buildChatPayload(userTurns), userTurns)
  } catch (streamError) {
    try {
      const data = await callApi(apiBase.value, '/chat/report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildChatPayload(userTurns)),
      }, 240000)
      const reply = data?.message?.content || '助手没有返回内容。'
      chatMessages.value = [...userTurns, { role: 'assistant', content: reply }]
    } catch (error) {
      const detail = error?.message || streamError?.message || '请求失败'
      chatMessages.value = [...userTurns, { role: 'assistant', content: `请求失败：${detail}` }]
    }
  } finally {
    chatLoading.value = false
    await nextTick()
    scrollChatToBottom()
  }
}

async function loadHistoryRecords() {
  try {
    const base = apiBase.value || context.value?.api_base || 'http://localhost:8000'
    const data = await callApi(base, '/history')
    historyRecords.value = Array.isArray(data.items) ? data.items : []
  } catch (error) {
    addStatus(`历史记录加载失败：${error.message}`)
  }
}

function openHistoryRecord(recordId) {
  router.push({
    name: 'results',
    query: { record_id: recordId, api_base: apiBase.value || context.value?.api_base || 'http://localhost:8000' },
  })
}

async function saveCurrentReport() {
  if (!activeRecordId.value) {
    addStatus('当前没有可保存的记录。')
    return
  }
  try {
    await callApi(apiBase.value, `/saved/${encodeURIComponent(activeRecordId.value)}`, { method: 'POST' })
    addStatus(`已保存报告：${activeRecordId.value}`)
  } catch (error) {
    addStatus(`保存失败：${error.message}`)
  }
}

async function loadReport() {
  reportError.value = ''
  report.value = null
  stopPolling()
  resetChatSession()

  if (!context.value?.api_base) {
    addStatus('没有可用的接口地址，请先回到控制台运行一次任务。')
    return
  }

  apiBase.value = context.value.api_base
  loading.value = true

  try {
    if (context.value.saved_id) {
      activeRecordId.value = context.value.saved_id
      addStatus(`正在载入已保存报告：${context.value.saved_id} ...`)
      const detail = await callApi(apiBase.value, `/saved/${encodeURIComponent(context.value.saved_id)}`)
      report.value = detail.report || null
      paperId.value = detail.paper_id || detail.meta?.paper_id || ''
      addStatus('已保存报告载入完成。')
    } else if (context.value.record_id) {
      activeRecordId.value = context.value.record_id
      addStatus(`正在载入历史记录：${context.value.record_id} ...`)
      const detail = await callApi(apiBase.value, `/history/${encodeURIComponent(context.value.record_id)}`)
      report.value = detail.report || null
      paperId.value = detail.paper_id || detail.meta?.paper_id || ''
      addStatus('历史记录载入完成。')
    } else if (context.value.paper_id) {
      paperId.value = context.value.paper_id
      activeRecordId.value = ''
      addStatus(`正在载入最新报告：paper_id=${paperId.value} ...`)
      startPolling()
      await fetchTraces()
      report.value = await callApi(apiBase.value, `/report/${encodeURIComponent(paperId.value)}`)
      addStatus('最新报告载入完成。')
    } else {
      addStatus('没有找到论文或记录上下文。')
    }
  } catch (error) {
    reportError.value = error.message
    addStatus(`错误：${error.message}`)
  } finally {
    loading.value = false
    await nextTick()
    scrollChatToBottom()
  }
}

onMounted(() => {
  loadHistoryRecords()
  nextTick(scrollChatToBottom)
})

onBeforeUnmount(() => {
  stopResize()
})

watch(() => route.fullPath, loadReport, { immediate: true })
watch(chatMessages, () => nextTick(scrollChatToBottom), { deep: true })
</script>

<template>
  <div class="workspace-shell">
    <header class="topbar">
      <div class="brand-block">
        <p class="eyebrow">研究运行控制台</p>
        <h1>AI 论文教练</h1>
      </div>
      <div class="topbar-search">历史记录与已保存报告阅读器</div>
      <div class="topbar-actions">
        <span class="status-pill status-pill-live">结果阅读</span>
        <button class="button button-secondary" @click="toggleChat">{{ chatOpen ? '收起助手' : '打开助手' }}</button>
        <RouterLink class="button button-secondary" :to="{ name: 'task' }">返回控制台</RouterLink>
      </div>
    </header>

    <div class="workspace-grid">
      <aside class="workspace-sidebar">
        <section class="sidebar-section">
          <p class="sidebar-title">导航</p>
          <div class="nav-list">
            <RouterLink class="nav-item" :to="{ name: 'task' }">控制台</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'history' }">历史记录</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'saved' }">已保存报告</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'uploads' }">上传文件</RouterLink>
            <RouterLink class="nav-item" :to="{ name: 'cache' }">缓存资源</RouterLink>
          </div>
        </section>

        <section class="sidebar-section">
          <div class="section-row">
            <p class="sidebar-title">本地历史</p>
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

      <main class="workspace-main workspace-main-span-two">
        <div class="result-split-shell">
          <section class="result-report-pane">
            <section class="hero-panel panel-soft hero-panel-single">
              <div>
                <p class="eyebrow">记录详情</p>
                <h2>报告阅读器</h2>
                <p class="panel-subtitle">{{ paperMetaLine }}</p>
              </div>
              <div class="hero-meta-grid report-meta-grid">
                <div v-for="item in reportStats" :key="item.label">
                  <span class="meta-label">{{ item.label }}</span>
                  <strong>{{ item.value }}</strong>
                </div>
              </div>
              <div class="section-actions">
                <button class="button button-secondary" @click="saveCurrentReport">保存报告</button>
              </div>
            </section>

            <section class="panel-soft">
              <div class="section-row">
                <div>
                  <p class="eyebrow">阅读视图</p>
                  <h3>报告内容</h3>
                </div>
                <div class="reader-tabs">
                  <button class="reader-tab" :class="{ 'reader-tab-active': activeTab === 'checks' }" @click="activeTab = 'checks'">内容要求检查</button>
                  <button class="reader-tab" :class="{ 'reader-tab-active': activeTab === 'summary' }" @click="activeTab = 'summary'">摘要</button>
                  <button class="reader-tab" :class="{ 'reader-tab-active': activeTab === 'reproduction' }" @click="activeTab = 'reproduction'">复现指导</button>
                  <button class="reader-tab" :class="{ 'reader-tab-active': activeTab === 'qa' }" @click="activeTab = 'qa'">七问回答</button>
                </div>
              </div>

              <p v-if="loading" class="empty-state">正在载入报告...</p>
              <p v-else-if="reportError" class="error-text">{{ reportError }}</p>
              <p v-else-if="!report" class="empty-state">当前没有可显示的报告。</p>

              <div v-else>
                <section v-if="activeTab === 'checks'" class="report-section report-section-compact">
                  <div class="section-row">
                    <h3>内容要求检查</h3>
                    <p :class="requirementChecks.every((item) => item.ok) ? 'success-text' : 'error-text'">
                      {{ requirementChecks.every((item) => item.ok) ? '全部通过' : '仍有缺项' }}
                    </p>
                  </div>
                  <div class="checks-grid">
                    <div v-for="item in requirementChecks" :key="item.key" class="check-card">
                      <strong>{{ item.title }}</strong>
                      <p class="check-card-status" :class="item.ok ? 'success-text' : 'error-text'">{{ item.ok ? '通过' : '未达标' }}</p>
                      <p>{{ item.actual }} / {{ item.min }}</p>
                    </div>
                  </div>
                </section>

                <section v-if="activeTab === 'summary'" class="reader-stack">
                  <article v-for="block in summaryBlocks" :key="block.title" class="report-section report-section-compact">
                    <h3>{{ block.title }}</h3>
                    <pre v-if="block.type === 'text'">{{ block.value }}</pre>
                    <ul v-else class="bullet-list">
                      <li v-for="item in asArray(block.value)" :key="String(item)">{{ item }}</li>
                    </ul>
                  </article>
                </section>

                <section v-if="activeTab === 'reproduction'" class="reader-stack">
                  <article v-for="block in reproductionBlocks" :key="block.title" class="report-section report-section-compact">
                    <h3>{{ block.title }}</h3>
                    <pre v-if="block.type === 'text'">{{ block.value }}</pre>
                    <ul v-else class="bullet-list">
                      <li v-for="item in asArray(block.value)" :key="String(item)">{{ item }}</li>
                    </ul>
                  </article>
                </section>

                <section v-if="activeTab === 'qa'" class="qa-reader-layout qa-reader-layout-wide">
                  <aside class="qa-nav">
                    <button v-for="item in questionMeta" :key="item.key" class="qa-nav-item" :class="{ 'qa-nav-item-active': activeQuestionKey === item.key }" @click="activeQuestionKey = item.key">
                      <strong>{{ item.title }}</strong>
                      <span>{{ item.short }}</span>
                    </button>
                  </aside>
                  <article class="report-section report-section-compact qa-content-card">
                    <h3>{{ activeQuestion.title }}：{{ activeQuestion.short }}</h3>
                    <pre>{{ activeQuestion.value }}</pre>
                  </article>
                </section>
              </div>
            </section>
          </section>

          <div v-if="chatOpen" class="result-chat-resizer" @pointerdown="startResize"></div>

          <aside v-if="chatOpen" class="result-chat-pane panel-soft" :style="{ width: `${chatWidth}px` }">
            <div class="chat-header">
              <div>
                <p class="eyebrow">AI 助手</p>
                <h3>报告对话</h3>
              </div>
              <div class="chat-header-actions">
                <button class="button button-secondary" @click="clearChat">清空会话</button>
                <button class="button button-secondary" @click="toggleChat">收起</button>
              </div>
            </div>

            <div class="chat-context-strip">
              <label class="chat-context-toggle">
                <input v-model="includeHistoryContext" type="checkbox" />
                <span>带入历史记录</span>
              </label>
              <label class="chat-context-toggle">
                <input v-model="includePapersContext" type="checkbox" />
                <span>带入论文库</span>
              </label>
              <span class="sidebar-meta">上下文：{{ chatContextSummary }}</span>
            </div>

            <div class="chat-quick-actions">
              <button class="chat-quick-button" @click="fillPrompt('请总结这篇论文最重要的创新点。')">总结创新点</button>
              <button class="chat-quick-button" @click="fillPrompt('请把复现指导整理成执行步骤。')">整理复现步骤</button>
              <button class="chat-quick-button" @click="fillPrompt('请指出当前报告还缺哪些关键信息。')">指出缺项</button>
              <button class="chat-quick-button" @click="fillPrompt('请结合历史记录和论文库，告诉我这篇论文和过去记录最接近的方向与差异。')">结合历史与论文库</button>
            </div>

            <div ref="chatListRef" class="chat-message-list">
              <div v-for="(message, index) in chatMessages" :key="`${message.role}-${index}`" class="chat-message" :class="message.role === 'user' ? 'chat-message-user' : 'chat-message-assistant'">
                <p class="chat-role">{{ message.role === 'user' ? '我' : 'AI 助手' }}</p>
                <div class="chat-bubble">
                  <pre>{{ message.content }}</pre>
                </div>
              </div>
            </div>

            <div class="chat-input-area">
              <textarea v-model="chatInput" class="chat-textarea" rows="5" placeholder="基于当前报告向 AI 提问..." @keydown.ctrl.enter.prevent="sendChat" />
              <div class="chat-input-actions">
                <span class="sidebar-meta">{{ chatLoading ? '正在流式生成回答...' : `Ctrl + Enter 发送 · ${chatContextSummary}` }}</span>
                <button class="button button-primary" :disabled="chatLoading || !report" @click="sendChat">发送</button>
              </div>
            </div>
          </aside>
        </div>
      </main>
    </div>

    <button v-if="!chatOpen" class="chat-collapsed-handle" @click="openChat">打开 AI 助手</button>

    <RunDiagnosticsPanel :statuses="statuses" :traces="traces" :trace-error="traceError" :compact="true" empty-trace-message="有可用 trace 时，会显示在这里。" />
  </div>
</template>