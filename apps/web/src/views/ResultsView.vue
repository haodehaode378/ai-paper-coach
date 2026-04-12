<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import RunDiagnosticsPanel from '../components/RunDiagnosticsPanel.vue'
import { callApi } from '../lib/api'
import { loadLastResult } from '../lib/storage'
import { useTraceHistory } from '../composables/useTraceHistory'

const route = useRoute()
const statuses = ref([])
const report = ref(null)
const reportError = ref('')
const loading = ref(false)
const paperId = ref('')
const apiBase = ref('')

function addStatus(message) {
  const timestamp = new Date().toLocaleTimeString()
  statuses.value.unshift(`${timestamp} - ${message}`)
}

const {
  traces,
  traceError,
  startPolling,
  stopPolling,
  fetchTraces
} = useTraceHistory({
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
  const queryPaperId = route.query.paper_id
  const queryApiBase = route.query.api_base
  if (queryPaperId && queryApiBase) {
    return {
      paper_id: String(queryPaperId),
      api_base: String(queryApiBase)
    }
  }
  return loadLastResult()
})

const paperMetaLine = computed(() => {
  if (!paperId.value) return '等待载入报告。'
  const title = report.value?.paper_meta?.title || '未命名论文'
  return `Paper ID: ${paperId.value}  标题: ${title}`
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
    {
      key: 'three_minute_summary.problem',
      min: 1000,
      actual: textLen(summary.problem || '')
    },
    {
      key: 'reproduction_guide.total',
      min: 1000,
      actual: reproductionTotal
    }
  ]

  qaKeys.forEach((key) => {
    checks.push({
      key: `reading_qa.${key}`,
      min: 700,
      actual: textLen(readingQa[key] || '')
    })
  })

  return checks.map((item) => ({
    ...item,
    ok: item.actual >= item.min
  }))
})

const reportSections = computed(() => {
  if (!report.value) return []

  const summary = report.value.three_minute_summary || {}
  const reproduction = report.value.reproduction_guide || {}
  const readingQa = report.value.reading_qa || {}

  return [
    {
      title: '论文分析（>=1000字）',
      blocks: [
        { label: '正文', type: 'text', value: summary.problem || '-' },
        { label: '方法要点', type: 'list', value: summary.method_points || [] },
        { label: '关键结果', type: 'list', value: summary.key_results || [] },
        { label: '局限性', type: 'list', value: summary.limitations || [] },
        { label: '适合谁读', type: 'text', value: summary.who_should_read || '-' }
      ]
    },
    {
      title: '复现指导（>=1000字）',
      blocks: [
        { label: '环境', type: 'text', value: reproduction.environment || '-' },
        { label: '数据集', type: 'text', value: reproduction.dataset || '-' },
        { label: '命令', type: 'list', value: reproduction.commands || [] },
        { label: '关键超参数', type: 'list', value: reproduction.key_hyperparams || [] },
        { label: '预期结果范围', type: 'text', value: reproduction.expected_range || '-' },
        { label: '常见错误', type: 'list', value: reproduction.common_errors || [] }
      ]
    },
    {
      title: '七个核心问题（每题>=700字）',
      blocks: [
        { label: '1. 论文试图解决什么问题？这是否是一个新的问题？', type: 'text', value: readingQa.q1_problem_and_novelty || '-' },
        { label: '2. 有哪些相关研究？如何归类？谁是这一课题在领域内值得关注的研究者（公司）？', type: 'text', value: readingQa.q2_related_work_and_researchers || '-' },
        { label: '3. 论文中提到的解决方案之关键是什么？', type: 'text', value: readingQa.q3_key_idea || '-' },
        { label: '4. 论文中的实验是如何设计的？', type: 'text', value: readingQa.q4_experiment_design || '-' },
        { label: '5. 用于定量评估的数据集是什么？代码有没有开源？', type: 'text', value: readingQa.q5_dataset_and_code || '-' },
        { label: '6. 文中的实验及结果有没有很好地支持需要验证的科学假设/提出方案？', type: 'text', value: readingQa.q6_support_for_claims || '-' },
        { label: '7. 这篇论文到底有什么贡献？下一步呢？有什么工作可以继续深入？', type: 'text', value: readingQa.q7_contribution_and_next_step || '-' }
      ]
    }
  ]
})

const reportLooksEmpty = computed(() => {
  const summary = report.value?.three_minute_summary || {}
  const reproduction = report.value?.reproduction_guide || {}
  const majorContent =
    textLen(summary.problem || '') +
    textLen(reproduction.environment || '') +
    textLen(reproduction.dataset || '')
  return majorContent <= 5
})

async function loadReport() {
  reportError.value = ''
  report.value = null
  stopPolling()

  if (!context.value?.paper_id || !context.value?.api_base) {
    addStatus('未找到可用的 paper_id 或 API 地址，请返回任务页重新提交。')
    return
  }

  paperId.value = context.value.paper_id
  apiBase.value = context.value.api_base
  loading.value = true
  addStatus(`正在拉取 paper_id=${paperId.value} 的报告...`)

  try {
    startPolling()
    await fetchTraces()
    report.value = await callApi(apiBase.value, `/report/${encodeURIComponent(paperId.value)}`)
    addStatus('报告加载完成。')
  } catch (error) {
    reportError.value = error.message
    addStatus(`错误：${error.message}`)
  } finally {
    loading.value = false
  }
}

watch(
  () => route.fullPath,
  () => {
    loadReport()
  },
  { immediate: true }
)
</script>

<template>
  <div class="page-shell">
    <header class="page-header page-header-compact">
      <div>
        <p class="eyebrow">Rendered Report</p>
        <h1>AI Paper Coach</h1>
        <p class="header-note">{{ paperMetaLine }}</p>
      </div>
      <RouterLink class="button button-secondary" :to="{ name: 'task' }">返回任务页</RouterLink>
    </header>

    <main class="page-main">
      <section class="panel">
        <div class="panel-heading">
          <div>
            <h2>结果渲染</h2>
            <p class="panel-subtitle">报告按结构化字段渲染，不再依赖大块 innerHTML 拼接。</p>
          </div>
        </div>

        <p v-if="loading" class="empty-state">正在加载报告与 trace 记录...</p>
        <p v-else-if="reportError" class="error-text">{{ reportError }}</p>
        <p v-else-if="!report" class="empty-state">还没有可展示的报告。</p>

        <div v-else class="report-layout">
          <section class="report-section">
            <div class="section-header">
              <h3>字数校验</h3>
              <p :class="requirementChecks.every((item) => item.ok) ? 'success-text' : 'error-text'">
                {{ requirementChecks.every((item) => item.ok) ? '全部达标' : '存在不达标字段' }}
              </p>
            </div>
            <ul class="check-list">
              <li v-for="item in requirementChecks" :key="item.key">
                <strong>{{ item.key }}</strong>
                <span :class="item.ok ? 'success-text' : 'error-text'">{{ item.ok ? '达标' : '不达标' }}</span>
                <span>({{ item.actual }}/{{ item.min }})</span>
              </li>
            </ul>
          </section>

          <section v-if="reportLooksEmpty" class="report-section report-warning">
            <h3>提示</h3>
            <p>当前结果正文为空，通常是模型未配置或调用失败。请先在任务页配置可用模型后重跑流程。</p>
            <div>
              <strong>最近日志：</strong>
              <ul class="bullet-list compact-list">
                <li v-for="status in asArray(statuses.slice(0, 3))" :key="status">{{ status }}</li>
              </ul>
            </div>
          </section>

          <section v-for="section in reportSections" :key="section.title" class="report-section">
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

      <RunDiagnosticsPanel
        :statuses="statuses"
        :traces="traces"
        :trace-error="traceError"
        empty-trace-message="等待加载实时讯息。"
      />
    </main>
  </div>
</template>
