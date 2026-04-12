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
    textLen(reproduction.environment || '') + textLen(reproduction.dataset || '') + textLen(reproduction.commands || []) +
    textLen(reproduction.key_hyperparams || []) + textLen(reproduction.expected_range || '') + textLen(reproduction.common_errors || [])

  const qaKeys = ['q1_problem_and_novelty','q2_related_work_and_researchers','q3_key_idea','q4_experiment_design','q5_dataset_and_code','q6_support_for_claims','q7_contribution_and_next_step']
  const checks = [
    { key: 'three_minute_summary.problem', min: 1000, actual: textLen(summary.problem || '') },
    { key: 'reproduction_guide.total', min: 1000, actual: reproductionTotal }
  ]
  qaKeys.forEach((key) => checks.push({ key: `reading_qa.${key}`, min: 700, actual: textLen(readingQa[key] || '') }))
  return checks.map((item) => ({ ...item, ok: item.actual >= item.min }))
})

const reportSections = computed(() => {
  if (!report.value) return []
  const summary = report.value.three_minute_summary || {}
  const reproduction = report.value.reproduction_guide || {}
  const readingQa = report.value.reading_qa || {}
  return [
    { title: '摘要', blocks: [
      { label: '论文问题与目标', type: 'text', value: summary.problem || '-' },
      { label: '方法要点', type: 'list', value: summary.method_points || [] },
      { label: '关键结果', type: 'list', value: summary.key_results || [] }
    ]},
    { title: '复现指导', blocks: [
      { label: '环境要求', type: 'text', value: reproduction.environment || '-' },
      { label: '数据集', type: 'text', value: reproduction.dataset || '-' },
      { label: '执行命令', type: 'list', value: reproduction.commands || [] },
      { label: '关键超参数', type: 'list', value: reproduction.key_hyperparams || [] }
    ]},
    { title: '七个问题', blocks: [
      { label: '问题一', type: 'text', value: readingQa.q1_problem_and_novelty || '-' },
      { label: '问题二', type: 'text', value: readingQa.q2_related_work_and_researchers || '-' },
      { label: '问题三', type: 'text', value: readingQa.q3_key_idea || '-' },
      { label: '问题四', type: 'text', value: readingQa.q4_experiment_design || '-' },
      { label: '问题五', type: 'text', value: readingQa.q5_dataset_and_code || '-' },
      { label: '问题六', type: 'text', value: readingQa.q6_support_for_claims || '-' },
      { label: '问题七', type: 'text', value: readingQa.q7_contribution_and_next_step || '-' }
    ]}
  ]
})

const reportStats = computed(() => [
  { label: '载入状态', value: report.value ? '已载入' : '未载入' },
  { label: '要求检查', value: requirementChecks.value.every((item) => item.ok) ? '通过' : '需补充' },
  { label: 'Trace 数量', value: `${traces.value.length}` },
  { label: '记录 ID', value: activeRecordId.value || '-' }
])

async function loadHistoryRecords() {
  try {
    const data = await callApi(apiBase.value || context.value?.api_base || 'http://localhost:8000', '/history')
    historyRecords.value = Array.isArray(data.items) ? data.items : []
  } catch (error) {
    addStatus(`历史记录加载失败：${error.message}`)
  }
}

function openHistoryRecord(recordId) {
  router.push({ name: 'results', query: { record_id: recordId, api_base: apiBase.value || context.value?.api_base || 'http://localhost:8000' } })
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
  }
}

onMounted(() => { loadHistoryRecords() })
watch(() => route.fullPath, loadReport, { immediate: true })
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

      <main class="workspace-main">
        <section class="hero-panel panel-soft">
          <div>
            <p class="eyebrow">记录详情</p>
            <h2>报告阅读器</h2>
            <p class="panel-subtitle">{{ paperMetaLine }}</p>
          </div>
          <div class="hero-meta-grid">
            <div><span class="meta-label">论文 ID</span><strong>{{ paperId || '-' }}</strong></div>
            <div><span class="meta-label">状态</span><strong>{{ loading ? '载入中' : (report ? '已就绪' : '缺失') }}</strong></div>
            <div><span class="meta-label">记录 ID</span><strong>{{ activeRecordId || '-' }}</strong></div>
          </div>
        </section>

        <section class="panel-soft">
          <div class="section-row">
            <div><p class="eyebrow">工作区标签</p><h3>内容阅读</h3></div>
            <div class="tab-strip">
              <span class="tab-pill tab-pill-active">摘要</span>
              <span class="tab-pill">复现指导</span>
              <span class="tab-pill">七问回答</span>
              <span class="tab-pill">Trace</span>
            </div>
          </div>

          <p v-if="loading" class="empty-state">正在载入报告...</p>
          <p v-else-if="reportError" class="error-text">{{ reportError }}</p>
          <p v-else-if="!report" class="empty-state">当前没有可显示的报告。</p>

          <div v-else class="report-layout">
            <section class="report-section report-section-compact">
              <div class="section-header">
                <h3>内容要求检查</h3>
                <p :class="requirementChecks.every((item) => item.ok) ? 'success-text' : 'error-text'">{{ requirementChecks.every((item) => item.ok) ? '全部通过' : '仍有缺项' }}</p>
              </div>
              <ul class="check-list">
                <li v-for="item in requirementChecks" :key="item.key">
                  <strong>{{ item.key }}</strong>
                  <span :class="item.ok ? 'success-text' : 'error-text'">{{ item.ok ? '通过' : '未达标' }}</span>
                  <span>（{{ item.actual }}/{{ item.min }}）</span>
                </li>
              </ul>
            </section>

            <section v-for="section in reportSections" :key="section.title" class="report-section report-section-compact">
              <h3>{{ section.title }}</h3>
              <div class="report-blocks">
                <article v-for="block in section.blocks" :key="block.label" class="report-block">
                  <h4>{{ block.label }}</h4>
                  <pre v-if="block.type === 'text'">{{ block.value }}</pre>
                  <ul v-else class="bullet-list"><li v-for="item in asArray(block.value)" :key="String(item)">{{ item }}</li></ul>
                </article>
              </div>
            </section>
          </div>
        </section>
      </main>

      <aside class="workspace-detail">
        <section class="panel-soft detail-panel">
          <div class="section-row"><div><p class="eyebrow">记录快照</p><h3>摘要信息</h3></div></div>
          <div class="summary-list"><div v-for="item in reportStats" :key="item.label" class="summary-row"><span>{{ item.label }}</span><strong>{{ item.value }}</strong></div></div>
          <div class="button-column" style="margin-top: 12px;"><button class="button button-secondary" @click="saveCurrentReport">保存报告</button></div>
        </section>
      </aside>
    </div>

    <RunDiagnosticsPanel :statuses="statuses" :traces="traces" :trace-error="traceError" :compact="true" empty-trace-message="有可用 trace 时，会显示在这里。" />
  </div>
</template>