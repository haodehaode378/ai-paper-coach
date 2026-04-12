<script setup>
const props = defineProps({
  statuses: {
    type: Array,
    default: () => []
  },
  traces: {
    type: Array,
    default: () => []
  },
  traceError: {
    type: String,
    default: ''
  },
  emptyTraceMessage: {
    type: String,
    default: '等待任务开始。'
  }
})

function previewText(value) {
  const text = String(value || '').trim()
  return text.length > 600 ? `${text.slice(0, 600)}\n...` : text
}
</script>

<template>
  <section class="panel diagnostics-panel">
    <div class="panel-heading">
      <div>
        <h2>运行状态</h2>
        <p class="panel-subtitle">实时讯息面板已启用（trace-v1）</p>
      </div>
    </div>

    <ol class="status-list">
      <li v-for="status in props.statuses" :key="status">{{ status }}</li>
    </ol>

    <div class="trace-block">
      <h3>实时讯息</h3>

      <div v-if="props.traceError" class="trace-error">
        trace 接口错误：{{ props.traceError }}
      </div>

      <div v-else-if="!props.traces.length" class="trace-empty">
        {{ props.emptyTraceMessage }}
      </div>

      <div v-else class="trace-list">
        <details v-for="(trace, index) in props.traces" :key="trace.id || `${trace.phase}-${trace.created_at}-${index}`" class="trace-item">
          <summary>
            {{ index + 1 }}.
            <span v-if="trace.run_id">run={{ String(trace.run_id).slice(0, 8) }}</span>
            {{ trace.phase || '-' }} / {{ trace.provider_name || trace.provider_slot || '-' }} / {{ trace.model || '-' }}
          </summary>
          <div class="trace-content">
            <div>
              <p class="trace-label">System</p>
              <pre>{{ previewText(trace.request_system || '-') }}</pre>
            </div>
            <div>
              <p class="trace-label">User</p>
              <pre>{{ previewText(trace.request_user || '-') }}</pre>
            </div>
            <div>
              <p class="trace-label">Response</p>
              <pre>{{ previewText(trace.response_text || trace.error_text || '-') }}</pre>
            </div>
          </div>
        </details>
      </div>
    </div>
  </section>
</template>
