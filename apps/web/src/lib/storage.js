export const STORAGE_KEY = 'apc_model_config_v1'
export const SESSION_SECRET_KEY = 'apc_model_secrets_session_v1'
export const LAST_RESULT_KEY = 'apc_last_result_v1'
export const TRACE_HISTORY_KEY = 'apc_trace_history_v1'

export const PROVIDER_PRESETS = {
  qwen: {
    label: '通义千问',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'qwen-plus'
  },
  minimax: {
    label: 'MiniMax',
    baseUrl: 'https://api.minimaxi.com/v1',
    model: 'MiniMax-M2.5'
  },
  openai_compatible: {
    label: 'OpenAI-compatible 自定义接口',
    baseUrl: '',
    model: ''
  }
}

export const defaultFormState = () => ({
  apiBase: window.__APC_DESKTOP_API_BASE__ || 'http://localhost:8000',
  paperUrl: '',
  runMode: 'deep',
  primaryProvider: 'qwen',
  secondaryProvider: 'minimax',
  cloudConsent: false,
  qwenBase: PROVIDER_PRESETS.qwen.baseUrl,
  qwenKey: '',
  qwenModel: PROVIDER_PRESETS.qwen.model,
  minimaxBase: PROVIDER_PRESETS.minimax.baseUrl,
  minimaxKey: '',
  minimaxModel: PROVIDER_PRESETS.minimax.model
})

function readJson(storage, key) {
  try {
    const raw = storage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function writeJson(storage, key, value) {
  storage.setItem(key, JSON.stringify(value))
}

function sanitizeConfig(config) {
  const next = JSON.parse(JSON.stringify(config || {}))
  for (const providerKey of ['primary', 'secondary', 'provider_a', 'provider_b', 'qwen', 'minimax']) {
    if (next?.[providerKey] && typeof next[providerKey] === 'object') {
      delete next[providerKey].api_key
    }
  }
  return next
}

function buildSessionSecrets(form) {
  return {
    qwenKey: String(form.qwenKey || '').trim(),
    minimaxKey: String(form.minimaxKey || '').trim(),
  }
}

export function buildModelConfig(form) {
  const primaryProvider = form.primaryProvider || 'qwen'
  const secondaryProvider = form.secondaryProvider || 'minimax'
  const modelA = {
    provider_id: primaryProvider,
    name: PROVIDER_PRESETS[primaryProvider]?.label || 'Model A',
    base_url: String(form.qwenBase || '').trim(),
    api_key: String(form.qwenKey || '').trim(),
    model: String(form.qwenModel || '').trim()
  }

  const modelB = {
    provider_id: secondaryProvider,
    name: PROVIDER_PRESETS[secondaryProvider]?.label || 'Model B',
    base_url: String(form.minimaxBase || '').trim() || 'https://api.minimaxi.com/v1',
    api_key: String(form.minimaxKey || '').trim(),
    model: String(form.minimaxModel || '').trim() || 'MiniMax-M2.5'
  }

  return {
    cloud_consent: Boolean(form.cloudConsent),
    primary: modelA,
    secondary: modelB,
    provider_a: modelA,
    provider_b: modelB,
    qwen: modelA,
    minimax: modelB
  }
}

export function applyModelConfigToForm(form, config) {
  const next = { ...defaultFormState(), ...form }
  const qwen = config?.primary || config?.provider_a || config?.qwen || {}
  const minimax = config?.secondary || config?.provider_b || config?.minimax || {}

  next.primaryProvider = qwen.provider_id || inferProviderId(qwen.base_url, 'qwen')
  next.secondaryProvider = minimax.provider_id || inferProviderId(minimax.base_url, 'minimax')
  next.cloudConsent = config?.cloud_consent === true
  next.qwenBase = qwen.base_url || next.qwenBase
  next.qwenKey = qwen.api_key || next.qwenKey || ''
  next.qwenModel = qwen.model || next.qwenModel
  next.minimaxBase = minimax.base_url || next.minimaxBase
  next.minimaxKey = minimax.api_key || next.minimaxKey || ''
  next.minimaxModel = minimax.model || next.minimaxModel

  if (next.minimaxBase === 'https://api.minimax.chat/v1') {
    next.minimaxBase = 'https://api.minimaxi.com/v1'
  }

  return next
}

function inferProviderId(baseUrl, fallback) {
  const value = String(baseUrl || '').toLowerCase()
  if (!value) return fallback
  if (value.includes('dashscope.aliyuncs.com')) return 'qwen'
  if (value.includes('minimaxi.com') || value.includes('minimax.chat')) return 'minimax'
  return 'openai_compatible'
}

export function applyProviderPreset(form, slot, providerId) {
  const preset = PROVIDER_PRESETS[providerId]
  if (!preset) return

  if (slot === 'primary') {
    form.primaryProvider = providerId
    form.qwenBase = preset.baseUrl
    form.qwenModel = preset.model
    return
  }

  form.secondaryProvider = providerId
  form.minimaxBase = preset.baseUrl
  form.minimaxModel = preset.model
}

// Security policy:
// - Non-sensitive config stored in localStorage
// - API keys stored only in sessionStorage (cleared when browser session ends)
export function saveModelConfig(form) {
  const full = buildModelConfig(form)
  writeJson(localStorage, STORAGE_KEY, sanitizeConfig(full))
  writeJson(sessionStorage, SESSION_SECRET_KEY, buildSessionSecrets(form))
}

export function loadModelConfig() {
  const base = defaultFormState()
  const savedConfig = readJson(localStorage, STORAGE_KEY)
  let next = savedConfig ? applyModelConfigToForm(base, savedConfig) : base

  const sessionSecrets = readJson(sessionStorage, SESSION_SECRET_KEY)
  if (sessionSecrets && typeof sessionSecrets === 'object') {
    next = {
      ...next,
      qwenKey: String(sessionSecrets.qwenKey || ''),
      minimaxKey: String(sessionSecrets.minimaxKey || ''),
    }
  }

  return next
}

export function clearModelConfig() {
  localStorage.removeItem(STORAGE_KEY)
  sessionStorage.removeItem(SESSION_SECRET_KEY)
  return defaultFormState()
}

export function saveLastResult(context) {
  localStorage.setItem(LAST_RESULT_KEY, JSON.stringify(context))
}

export function loadLastResult() {
  try {
    const raw = localStorage.getItem(LAST_RESULT_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function loadTraceHistory(paperId) {
  if (!paperId) return []

  try {
    const raw = localStorage.getItem(TRACE_HISTORY_KEY)
    if (!raw) return []

    const all = JSON.parse(raw)
    return Array.isArray(all[paperId]) ? all[paperId] : []
  } catch {
    return []
  }
}

export function saveTraceHistory(paperId, traces) {
  if (!paperId) return

  try {
    const raw = localStorage.getItem(TRACE_HISTORY_KEY)
    const all = raw ? JSON.parse(raw) : {}
    all[paperId] = Array.isArray(traces) ? traces.slice(-500) : []
    localStorage.setItem(TRACE_HISTORY_KEY, JSON.stringify(all))
  } catch {
    // Ignore storage errors in the browser sandbox.
  }
}
