export interface Health {
  status: 'ok'
  version: string
}

function isHealth(value: unknown): value is Health {
  return (
    typeof value === 'object' &&
    value !== null &&
    'status' in value &&
    value.status === 'ok' &&
    'version' in value &&
    typeof value.version === 'string'
  )
}

export async function fetchHealth(signal: AbortSignal): Promise<Health> {
  const response = await fetch('/api/health', { signal })
  if (!response.ok) {
    throw new Error(`Health check failed with status ${String(response.status)}`)
  }
  const body: unknown = await response.json()
  if (!isHealth(body)) {
    throw new Error('Health check returned an unexpected body')
  }
  return body
}
