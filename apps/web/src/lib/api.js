export async function callApi(base, path, options = {}, timeoutMs = 120000) {
  const normalizedBase = String(base || '').trim().replace(/\/$/, '')
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)

  const parseErrorPayload = async (response) => {
    const contentType = response.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
      try {
        const payload = await response.json()
        const message = payload?.error?.message || payload?.detail || payload?.message || JSON.stringify(payload)
        return message
      } catch {
        return `${response.status} ${response.statusText}`
      }
    }
    try {
      return await response.text()
    } catch {
      return `${response.status} ${response.statusText}`
    }
  }

  try {
    const response = await fetch(`${normalizedBase}${path}`, { ...options, signal: controller.signal })
    if (!response.ok) {
      const errText = await parseErrorPayload(response)
      throw new Error(`${response.status} ${response.statusText}: ${errText}`)
    }

    const contentType = response.headers.get('content-type') || ''
    if (!contentType.includes('application/json')) {
      return await response.text()
    }

    const payload = await response.json()

    // Unified envelope support: { success, data, error }
    if (payload && typeof payload === 'object' && Object.prototype.hasOwnProperty.call(payload, 'success')) {
      if (!payload.success) {
        const msg = payload?.error?.message || 'request failed'
        throw new Error(msg)
      }
      return payload.data
    }

    // Backward compatibility for non-enveloped JSON.
    return payload
  } catch (error) {
    if (error?.name === 'AbortError') throw new Error(`请求超时（${Math.floor(timeoutMs / 1000)} 秒）`)
    throw error
  } finally {
    window.clearTimeout(timer)
  }
}

export function isTimeoutError(error) {
  const message = error?.message ? String(error.message) : ''
  return message.includes('请求超时')
}
