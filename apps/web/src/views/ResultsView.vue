<script setup>
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import RunDiagnosticsPanel from '../components/RunDiagnosticsPanel.vue'
import { callApi } from '../lib/api'
import { buildModelConfig, loadLastResult, loadModelConfig } from '../lib/storage'
import { useTraceHistory } from '../composables/useTraceHistory'
import * as pdfjsLib from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

const STAGE_DEFAULT_MS = {
  analyze: 180000,
  review: 240000,
  finalize: 300000,
}
const STAGE_ORDER = ['analyze', 'review', 'finalize']

const CHAT_WIDTH_KEY = 'apc_report_chat_width_v1'
const CHAT_OPEN_KEY = 'apc_report_chat_open_v1'
const CHAT_LANG_KEY = 'apc_report_chat_lang_v1'
const CHAT_SLOT_KEY = 'apc_report_chat_slot_v1'
const CHAT_HISTORY_STORE_KEY = 'apc_report_chat_history_v1'
const CHAT_HISTORY_MAX_MESSAGES = 120

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

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
const pdfCanvasRef = ref(null)
const pdfDoc = ref(null)
const pdfLoading = ref(false)
const pdfError = ref('')
const pdfPage = ref(1)
const pdfPageCount = ref(0)
const loadedPdfKey = ref('')

const chatInput = ref('')
const chatLoading = ref(false)
const includeHistoryContext = ref(true)
const includePapersContext = ref(true)
const chatLanguage = ref(localStorage.getItem(CHAT_LANG_KEY) || 'zh')
const chatModelSlot = ref(localStorage.getItem(CHAT_SLOT_KEY) || 'primary')
const chatOpen = ref(localStorage.getItem(CHAT_OPEN_KEY) !== '0')
const chatWidth = ref(Number(localStorage.getItem(CHAT_WIDTH_KEY) || 380))
const chatListRef = ref(null)
const chatMessages = ref([])
const chatHistoryScope = ref('')
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
    content: '你好，我可以基于当前报告与你对话。请直接输入你的问题。',
  }
}

function resetChatSession() {
  chatMessages.value = [createStarterMessage()]
  chatInput.value = ''
}

resetChatSession()

function normalizeChatMessages(messages) {
  if (!Array.isArray(messages)) return [createStarterMessage()]
  const items = messages
    .filter((item) => item && (item.role === 'user' || item.role === 'assistant') && typeof item.content === 'string')
    .map((item) => ({ role: item.role, content: item.content }))
  if (!items.length) return [createStarterMessage()]
  return items.slice(-CHAT_HISTORY_MAX_MESSAGES)
}

function readChatHistoryStore() {
  try {
    const raw = localStorage.getItem(CHAT_HISTORY_STORE_KEY)
    const data = raw ? JSON.parse(raw) : {}
    return data && typeof data === 'object' ? data : {}
  } catch {
    return {}
  }
}

function writeChatHistoryStore(store) {
  localStorage.setItem(CHAT_HISTORY_STORE_KEY, JSON.stringify(store))
}

function loadChatHistoryForScope(scopeKey) {
  if (!scopeKey) {
    resetChatSession()
    return
  }
  const store = readChatHistoryStore()
  chatMessages.value = normalizeChatMessages(store[scopeKey])
}

function saveChatHistoryForScope(scopeKey, messages) {
  if (!scopeKey) return
  const store = readChatHistoryStore()
  store[scopeKey] = normalizeChatMessages(messages)
  writeChatHistoryStore(store)
}

function clearChatHistoryForScope(scopeKey) {
  if (!scopeKey) return
  const store = readChatHistoryStore()
  if (Object.prototype.hasOwnProperty.call(store, scopeKey)) {
    delete store[scopeKey]
    writeChatHistoryStore(store)
  }
}

function normalizeScopeToken(value) {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')
}

function buildChatScopeKey() {
  const base = String(apiBase.value || '').trim()
  if (!base) return ''

  const title = normalizeScopeToken(resolveDisplayTitle())
  if (title) return `${base}|title:${title}`

  // Fallback for records with missing title.
  if (paperId.value) return `${base}|paper:${paperId.value}`
  return ''
}


function addStatus(message) {
  const timestamp = new Date().toLocaleTimeString()
  statuses.value.unshift(`${timestamp} - ${message}`)
}

const { traces, traceError, runStatus, startPolling, stopPolling, fetchTraces } = useTraceHistory({
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


function isPlaceholderTitle(value) {
  const t = String(value || '').trim().toLowerCase().replace(/_/g, ' ')
  if (!t) return true
  const n = t.replace(/\s+/g, ' ')
  return ['unknown title', 'unknowntitle', 'untitled', '?????', '????', '-'].includes(n)
}

function resolveDisplayTitle() {
  const reportTitle = report.value?.paper_meta?.title
  if (!isPlaceholderTitle(reportTitle)) return String(reportTitle).trim()
  const fallbackTitle = context.value?.title || report.value?.meta?.title
  if (!isPlaceholderTitle(fallbackTitle)) return String(fallbackTitle).trim()
  return paperId.value || '???'
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
    { key: 'three_minute_summary.problem', title: '摘要：论文问题与目标', min: 800, actual: textLen(summary.problem || '') },
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

const pdfPreviewUrl = computed(() => {
  if (!paperId.value || !apiBase.value) return ''
  const base = String(apiBase.value).trim().replace(/\/$/, '')
  return `${base}/papers/${encodeURIComponent(paperId.value)}/pdf#view=FitH`
})

const pdfPageLabel = computed(() => {
  if (!pdfPageCount.value) return '0 / 0'
  return `${pdfPage.value} / ${pdfPageCount.value}`
})

function traceTimeMs(item) {
  const ts = Date.parse(String(item?.created_at || ''))
  return Number.isFinite(ts) ? ts : null
}

function stageFromPhase(phase) {
  const p = String(phase || '').toLowerCase()
  if (p === 'analyze') return 'analyze'
  if (p === 'review') return 'review'
  if (p === 'finalize' || p === 'repair') return 'finalize'
  return null
}

const stageTraceTimes = computed(() => {
  const groups = { analyze: [], review: [], finalize: [] }
  for (const item of traces.value) {
    if (String(item?.provider_slot || '').toLowerCase() === 'orchestrator') continue
    const stage = stageFromPhase(item?.phase)
    if (!stage) continue
    const ts = traceTimeMs(item)
    if (ts !== null) groups[stage].push(ts)
  }
  for (const key of Object.keys(groups)) {
    groups[key].sort((a, b) => a - b)
  }
  return groups
})

const currentStageInfo = computed(() => {
  if (runStatus.value !== 'running') return { key: 'done', label: '完成' }
  const latest = [...traces.value]
    .reverse()
    .find((item) => String(item?.provider_slot || '').toLowerCase() !== 'orchestrator')
  const stage = stageFromPhase(latest?.phase)
  const key = stage || 'analyze'
  const labelMap = { analyze: '分析', review: '审阅', finalize: '整理', done: '完成' }
  return { key, label: labelMap[key] || key }
})

const stageDoneState = computed(() => {
  const has = (stage) => (stageTraceTimes.value[stage] || []).length > 0
  const done = {
    ingest: !!paperId.value,
    analyze: has('analyze'),
    review: has('review'),
    finalize: has('finalize') && runStatus.value !== 'running',
  }
  if (runStatus.value !== 'running' && has('finalize')) {
    done.finalize = true
  }
  return done
})

const progressPercent = computed(() => {
  const done = stageDoneState.value
  let completed = 0
  if (done.ingest) completed += 1
  if (done.analyze) completed += 1
  if (done.review) completed += 1
  if (done.finalize) completed += 1
  if (runStatus.value === 'running' && !done.finalize) completed += 0.35
  return Math.max(0, Math.min(100, Math.round((completed / 4) * 100)))
})

function estimatedStageMs(stage) {
  const times = stageTraceTimes.value[stage] || []
  if (times.length >= 2) return Math.max(times[times.length - 1] - times[0], 0)
  return STAGE_DEFAULT_MS[stage] || 0
}

function formatEta(ms) {
  if (!Number.isFinite(ms) || ms <= 0) return '约 0 秒'
  const sec = Math.ceil(ms / 1000)
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  const s = sec % 60
  if (h > 0) return `约 ${h}小时${m}分`
  if (m > 0) return `约 ${m}分${s}秒`
  return `约 ${s}秒`
}

const etaLabel = computed(() => {
  if (runStatus.value !== 'running') return '-'
  const current = currentStageInfo.value.key
  let remaining = 0
  for (const stage of STAGE_ORDER) {
    const times = stageTraceTimes.value[stage] || []
    if (times.length >= 2) continue
    if (stage === current && times.length === 1) {
      const elapsed = Math.max(Date.now() - times[0], 0)
      remaining += Math.max(estimatedStageMs(stage) - elapsed, 0)
    } else {
      remaining += estimatedStageMs(stage)
    }
  }
  return formatEta(remaining)
})

const currentModelLabel = computed(() => {
  const current = currentStageInfo.value.key
  const modelCfg = loadModelConfig()
  const phaseByStage = {
    analyze: ['analyze'],
    review: ['review'],
    finalize: ['finalize', 'repair'],
  }
  const phases = phaseByStage[current] || []
  if (phases.length > 0) {
    const latest = [...traces.value].reverse().find((item) => {
      const phase = String(item?.phase || '').toLowerCase()
      const slot = String(item?.provider_slot || '').toLowerCase()
      return phases.includes(phase) && slot !== 'orchestrator'
    })
    if (latest) {
      return `${latest.provider_name || latest.provider_slot || 'unknown'} · ${latest.model || '-'}`
    }
  }
  if (current === 'review') {
    return `${modelCfg.minimaxModel || 'Model B'}（优先） / ${modelCfg.qwenModel || 'Model A'}（回退）`
  }
  if (current === 'analyze' || current === 'finalize') {
    return `${modelCfg.qwenModel || 'Model A'}（优先） / ${modelCfg.minimaxModel || 'Model B'}（回退）`
  }
  return `${modelCfg.qwenModel || 'Model A'} / ${modelCfg.minimaxModel || 'Model B'}`
})

const reportStats = computed(() => [
  { label: '载入状态', value: report.value ? '已载入' : '未载入' },
  { label: '要求检查', value: requirementChecks.value.every((item) => item.ok) ? '通过' : '需补充' },
  { label: '阶段进度', value: `${progressPercent.value}%（${currentStageInfo.value.label}）` },
  { label: '预计剩余', value: etaLabel.value },
  { label: '当前模型', value: currentModelLabel.value },
  { label: 'Trace 数量', value: String(traces.value.length) },
  { label: '记录 ID', value: activeRecordId.value || '-' },
])

const chatContextSummary = computed(() => {
  const parts = ['当前报告']
  if (includeHistoryContext.value) parts.push('历史记录')
  if (includePapersContext.value) parts.push('论文库')
  parts.push(chatLanguage.value === 'en' ? 'English' : (chatLanguage.value === 'follow_user' ? '\u8ddf\u968f\u63d0\u95ee\u8bed\u8a00' : '\u4e2d\u6587'))
  parts.push(chatModelSlot.value === 'secondary' ? '\u6a21\u578bB' : '\u6a21\u578bA')
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
  clearChatHistoryForScope(chatHistoryScope.value)
  resetChatSession()
  addStatus('\u5df2\u6e05\u7a7a\u5f53\u524d\u62a5\u544a\u7684\u5bf9\u8bdd\u5386\u53f2\u3002')
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
    response_language: chatLanguage.value,
    model_slot: chatModelSlot.value,
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

async function renderPdfPage() {
  if (!pdfDoc.value || !pdfCanvasRef.value) return

  const safePage = Math.min(
    Math.max(Number(pdfPage.value) || 1, 1),
    Math.max(Number(pdfPageCount.value) || 1, 1),
  )
  if (safePage !== pdfPage.value) {
    pdfPage.value = safePage
  }

  try {
    const page = await pdfDoc.value.getPage(safePage)
    const viewport = page.getViewport({ scale: 1.2 })
    const canvas = pdfCanvasRef.value
    const context = canvas.getContext('2d')
    if (!context) {
      throw new Error('Canvas 2D context unavailable')
    }
    canvas.width = Math.floor(viewport.width)
    canvas.height = Math.floor(viewport.height)
    await page.render({ canvasContext: context, viewport }).promise
  } catch (error) {
    pdfError.value = error?.message || 'PDF 加载失败'
  }
}

async function loadPdfDocument(force = false) {
  const url = pdfPreviewUrl.value
  const key = `${apiBase.value}|${paperId.value}`

  if (!url) {
    pdfDoc.value = null
    pdfPage.value = 1
    pdfPageCount.value = 0
    pdfError.value = ''
    return
  }

  if (!force && loadedPdfKey.value === key && pdfDoc.value) {
    await nextTick()
    await renderPdfPage()
    return
  }

  pdfLoading.value = true
  pdfError.value = ''
  pdfDoc.value = null
  pdfPage.value = 1
  pdfPageCount.value = 0

  try {
    const response = await fetch(url)
    if (!response.ok) {
      throw new Error(extractErrorText(await response.text()) || `HTTP ${response.status}`)
    }
    const bytes = await response.arrayBuffer()
    const task = pdfjsLib.getDocument({ data: bytes })
    const doc = await task.promise
    pdfDoc.value = markRaw(doc)
    pdfPageCount.value = doc.numPages
    pdfPage.value = 1
    loadedPdfKey.value = key
  } catch (error) {
    pdfError.value = error?.message || 'PDF 加载失败'
  } finally {
    pdfLoading.value = false
  }

  if (!pdfError.value && pdfDoc.value) {
    await nextTick()
    await renderPdfPage()
  }
}

function prevPdfPage() {
  if (pdfPage.value <= 1) return
  pdfPage.value -= 1
}

function nextPdfPage() {
  if (pdfPage.value >= pdfPageCount.value) return
  pdfPage.value += 1
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
  chatHistoryScope.value = ""
  resetChatSession()
  pdfDoc.value = null
  pdfPage.value = 1
  pdfPageCount.value = 0
  pdfError.value = ''
  loadedPdfKey.value = ''

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
    chatHistoryScope.value = buildChatScopeKey()
    loadChatHistoryForScope(chatHistoryScope.value)
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
watch(chatMessages, (messages) => {
  saveChatHistoryForScope(chatHistoryScope.value, messages)
  nextTick(scrollChatToBottom)
}, { deep: true })
watch(chatLanguage, (value) => localStorage.setItem(CHAT_LANG_KEY, String(value || 'zh')))
watch(chatModelSlot, (value) => localStorage.setItem(CHAT_SLOT_KEY, String(value || 'primary')))
watch([activeTab, paperId, apiBase], async ([tab]) => {
  if (tab === 'paper') await loadPdfDocument()
})
watch(pdfPage, async () => {
  if (activeTab.value !== 'paper') return
  await nextTick()
  await renderPdfPage()
})
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
                  <button class="reader-tab" :class="{ 'reader-tab-active': activeTab === 'paper' }" @click="activeTab = 'paper'">论文原文</button>
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

                <section v-if="activeTab === 'qa'" class="qa-reader-layout qa-reader-layout-wide qa-reader-layout-horizontal">
                  <aside class="qa-nav qa-nav-horizontal">
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
 
                <section v-if="activeTab === 'paper'" class="report-section report-section-compact paper-preview-section">
                  <div class="section-row">
                    <h3>论文原文</h3>
                    <span class="sidebar-meta" v-if="paperId">paper_id={{ paperId }}</span>
                  </div>
                  <p v-if="!paperId" class="empty-state">缺少论文 ID，无法定位 PDF。</p>
                  <p v-else-if="!pdfPreviewUrl" class="empty-state">未生成 PDF 预览地址。</p>
                  <p v-else-if="pdfLoading" class="empty-state">正在加载 PDF...</p>
                  <p v-else-if="pdfError" class="error-text">{{ pdfError }}</p>
                  <div v-else class="pdf-viewer-shell">
                    <div class="pdf-viewer-toolbar">
                      <button class="button button-secondary" :disabled="pdfPage <= 1" @click="prevPdfPage">上一页</button>
                      <span class="sidebar-meta">页码 {{ pdfPageLabel }}</span>
                      <button class="button button-secondary" :disabled="pdfPage >= pdfPageCount" @click="nextPdfPage">下一页</button>
                    </div>
                    <div class="pdf-canvas-wrap">
                      <canvas ref="pdfCanvasRef" class="pdf-canvas" />
                    </div>
                  </div>
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
                <span>&#x5E26;&#x5165;&#x5386;&#x53F2;&#x8BB0;&#x5F55;</span>
              </label>
              <label class="chat-context-toggle">
                <input v-model="includePapersContext" type="checkbox" />
                <span>&#x5E26;&#x5165;&#x8BBA;&#x6587;&#x5E93;</span>
              </label>
              <label class="chat-context-toggle">
                <span>&#x56DE;&#x7B54;&#x8BED;&#x8A00;</span>
                <select v-model="chatLanguage" class="chat-context-select">
                  <option value="zh">&#x4E2D;&#x6587;</option>
                  <option value="en">English</option>
                  <option value="follow_user">&#x8DDF;&#x968F;&#x63D0;&#x95EE;&#x8BED;&#x8A00;</option>
                </select>
              </label>
              <label class="chat-context-toggle">
                <span>&#x6A21;&#x578B;&#x901A;&#x9053;</span>
                <select v-model="chatModelSlot" class="chat-context-select">
                  <option value="primary">&#x6A21;&#x578B; A (Primary)</option>
                  <option value="secondary">&#x6A21;&#x578B; B (Secondary)</option>
                </select>
              </label>
              <span class="sidebar-meta">&#x4E0A;&#x4E0B;&#x6587;&#xFF1A;{{ chatContextSummary }}</span>
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

