<script setup>
const props = defineProps({ statuses: { type: Array, default: () => [] }, traces: { type: Array, default: () => [] }, traceError: { type: String, default: '' }, emptyTraceMessage: { type: String, default: '等待任务开始。' }, compact: { type: Boolean, default: false } })
function previewText(value) {
  const text = String(value || '').trim()
  return text.length > 480 ? `${text.slice(0, 480)}\n...` : text
}
</script>
<template>
  <section class="console-shell" :class="{ 'console-shell-compact': compact }">
    <div class="console-tabs"><span class="console-tab console-tab-active">日志</span><span class="console-tab">Trace</span><span class="console-tab">警告</span><span class="console-tab">错误</span></div>
    <div class="console-body">
      <div class="console-column"><div class="console-title-row"><h3>运行日志</h3><span class="console-meta">{{ statuses.length }} 条</span></div><ol class="status-list console-list"><li v-for="status in statuses" :key="status">{{ status }}</li><li v-if="!statuses.length" class="console-empty">当前还没有运行日志。</li></ol></div>
      <div class="console-column console-column-wide">
        <div class="console-title-row"><h3>Trace 面板</h3><span class="console-meta">{{ traces.length }} 条</span></div>
        <div v-if="traceError" class="trace-error">Trace 接口错误：{{ traceError }}</div>
        <div v-else-if="!traces.length" class="console-empty">{{ emptyTraceMessage }}</div>
        <div v-else class="trace-list">
          <details v-for="(trace, index) in traces" :key="trace.id || `${trace.phase}-${trace.created_at}-${index}`" class="trace-item">
            <summary>{{ index + 1 }}.<span v-if="trace.run_id">run={{ String(trace.run_id).slice(0, 8) }}</span>{{ trace.phase || '-' }} / {{ trace.provider_name || trace.provider_slot || '-' }} / {{ trace.model || '-' }}</summary>
            <div class="trace-content">
              <div><p class="trace-label">系统提示</p><pre>{{ previewText(trace.request_system || '-') }}</pre></div>
              <div><p class="trace-label">用户输入</p><pre>{{ previewText(trace.request_user || '-') }}</pre></div>
              <div><p class="trace-label">模型输出</p><pre>{{ previewText(trace.response_text || trace.error_text || '-') }}</pre></div>
            </div>
          </details>
        </div>
      </div>
    </div>
  </section>
</template>