export async function callApi(base, path, options = {}, timeoutMs = 120000) {
  const normalizedBase = String(base || '').trim().replace(/\/$/, '')
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)

  try {
    const response = await fetch(`${normalizedBase}${path}`, {
      ...options,
      signal: controller.signal
    })

    if (!response.ok) {
      const text = await response.text()
      throw new Error(`${response.status} ${response.statusText}: ${text}`)
    }

    const contentType = response.headers.get('content-type') || ''
    if (contentType.includes('application/json')) {
      return await response.json()
    }

    return await response.text()
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new Error(`Request timed out (${Math.floor(timeoutMs / 1000)}s)`)
    }

    throw error
  } finally {
    window.clearTimeout(timer)
  }
}

export function isTimeoutError(error) {
  const message = error?.message ? String(error.message) : ''
  return message.includes('Request timed out')
}