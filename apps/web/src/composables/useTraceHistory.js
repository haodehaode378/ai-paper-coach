import { onUnmounted, ref, watch } from 'vue'

import { callApi } from '../lib/api'
import { loadTraceHistory, saveTraceHistory } from '../lib/storage'

function traceItemKey(item, fallbackIndex = 0) {
  if (item?.id) return String(item.id)
  const phase = item?.phase || '-'
  const model = item?.model || '-'
  const created = item?.created_at || '-'
  return `${phase}|${model}|${created}|${fallbackIndex}`
}

export function useTraceHistory({ paperIdRef, apiBaseRef, addStatus }) {
  const traces = ref([])
  const traceError = ref('')
  const runStatus = ref('idle')
  const runId = ref(null)

  let activeRunId = null
  let lastTraceCount = -1
  let lastTraceError = ''
  let traceSeen = new Set()
  let traceTimer = null

  function resetState() {
    activeRunId = null
    lastTraceCount = -1
    lastTraceError = ''
    traceError.value = ''
    traces.value = []
    runStatus.value = 'idle'
    runId.value = null
    traceSeen = new Set()
  }

  function hydrateTraceState(paperId) {
    const history = loadTraceHistory(paperId)
    traces.value = history
    traceSeen = new Set(history.map((item, index) => traceItemKey(item, index)))
    lastTraceCount = history.length
  }

  async function fetchTraces() {
    if (!paperIdRef.value || !apiBaseRef.value) return

    try {
      const data = await callApi(
        apiBaseRef.value,
        `/trace/${encodeURIComponent(paperIdRef.value)}`,
        {},
        30000
      )
      const incoming = Array.isArray(data.traces) ? data.traces : []
      const runId = data.run_id || null
      runStatus.value = data.status || 'idle'
      runId.value = runId
      let changed = false

      traceError.value = ''
      lastTraceError = ''

      for (let index = 0; index < incoming.length; index += 1) {
        const item = {
          ...incoming[index],
          run_id: runId || incoming[index].run_id || null
        }
        const key = traceItemKey(item, index)
        if (!traceSeen.has(key)) {
          traceSeen.add(key)
          traces.value.push(item)
          changed = true
        }
      }

      if (runId !== activeRunId) {
        activeRunId = runId
        changed = true
      }

      if (changed || traces.value.length !== lastTraceCount) {
        lastTraceCount = traces.value.length
        saveTraceHistory(paperIdRef.value, traces.value)
      }

      if (data.status && data.status !== 'running') {
        stopPolling()
      }
    } catch (error) {
      const message = error?.message || 'unknown error'
      const isNoRunFound =
        (/404/.test(message) && /no run found/i.test(message)) ||
        /"detail"\s*:\s*"no run found"/i.test(message)

      if (isNoRunFound) {
        if (lastTraceError !== 'no_run_found') {
          addStatus('trace 暂无运行记录，已保留历史讯息。')
          lastTraceError = 'no_run_found'
        }
        return
      }

      if (message !== lastTraceError) {
        traceError.value = message
        lastTraceError = message
      }
    }
  }

  function stopPolling() {
    if (traceTimer) {
      window.clearInterval(traceTimer)
      traceTimer = null
    }
  }

  function startPolling() {
    stopPolling()
    traceTimer = window.setInterval(fetchTraces, 3000)
    fetchTraces()
  }

  watch(
    () => paperIdRef.value,
    (paperId) => {
      resetState()
      if (paperId) {
        hydrateTraceState(paperId)
      }
    },
    { immediate: true }
  )

  onUnmounted(() => {
    stopPolling()
  })

  return {
    traces,
    traceError,
    runStatus,
    runId,
    fetchTraces,
    startPolling,
    stopPolling,
    resetTraceState: resetState
  }
}
