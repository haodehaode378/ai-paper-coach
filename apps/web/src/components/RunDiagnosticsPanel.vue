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
    default: 'Waiting for a task to start.'
  },
  compact: {
    type: Boolean,
    default: false
  }
})

function previewText(value) {
  const text = String(value || '').trim()
  return text.length > 480 ? `${text.slice(0, 480)}\n...` : text
}
</script>

<template>
  <section class="console-shell" :class="{ 'console-shell-compact': compact }">
    <div class="console-tabs">
      <span class="console-tab console-tab-active">Log</span>
      <span class="console-tab">Trace</span>
      <span class="console-tab">Warning</span>
      <span class="console-tab">Error</span>
    </div>

    <div class="console-body">
      <div class="console-column">
        <div class="console-title-row">
          <h3>Run Log</h3>
          <span class="console-meta">{{ statuses.length }} items</span>
        </div>
        <ol class="status-list console-list">
          <li v-for="status in statuses" :key="status">{{ status }}</li>
          <li v-if="!statuses.length" class="console-empty">No runtime logs yet.</li>
        </ol>
      </div>

      <div class="console-column console-column-wide">
        <div class="console-title-row">
          <h3>Trace Panel</h3>
          <span class="console-meta">{{ traces.length }} items</span>
        </div>

        <div v-if="traceError" class="trace-error">
          Trace endpoint error: {{ traceError }}
        </div>

        <div v-else-if="!traces.length" class="console-empty">
          {{ emptyTraceMessage }}
        </div>

        <div v-else class="trace-list">
          <details
            v-for="(trace, index) in traces"
            :key="trace.id || `${trace.phase}-${trace.created_at}-${index}`"
            class="trace-item"
          >
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
    </div>
  </section>
</template>