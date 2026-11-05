// The backend's conversation API (backend/voice_agent/api/conversations.py)

export type Role = 'user' | 'assistant'
export type Source = 'voice' | 'keyboard' | 'keypad' | 'llm' | 'template'
export type InputVia = 'keyboard' | 'keypad'
export type EndReason = 'hangup' | 'page_closed'

export interface Message {
  id: number
  role: Role
  source: Source
  text: string
  created_at: string
  timings_ms: Record<string, number> | null
}

export interface Conversation {
  id: string
  started_at: string
  ended_at: string | null
}

export interface Audio {
  media_type: 'audio/wav'
  wav_base64: string
  duration_ms: number
}

export interface StartResponse {
  conversation: Conversation
  greeting: Message
  audio: Audio | null
}

export interface TurnResponse {
  user_message: Message
  assistant_message: Message
  audio: Audio | null
}

export interface Status {
  database: 'ok' | 'error'
  llm: { provider: string; model: string | null; configured: boolean }
  stt: { model: string; max_recording_s: number }
  tts: { model: string }
}

// An error the backend explains, e.g. code "no_speech"
export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

function errorDetail(body: unknown): { code: string; message: string } | null {
  if (typeof body !== 'object' || body === null || !('detail' in body)) {
    return null
  }
  const detail = body.detail
  if (
    typeof detail === 'object' &&
    detail !== null &&
    'code' in detail &&
    typeof detail.code === 'string' &&
    'message' in detail &&
    typeof detail.message === 'string'
  ) {
    return { code: detail.code, message: detail.message }
  }
  return null
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const detail = errorDetail(await response.json().catch(() => null))
    throw new ApiError(
      response.status,
      detail?.code ?? 'http_error',
      detail?.message ?? `The server answered with status ${String(response.status)}.`,
    )
  }
  if (response.status === 204) {
    return undefined as T
  }
  // The backend's response models guarantee the shape
  return (await response.json()) as T
}

const json = { 'content-type': 'application/json' }

export function fetchStatus(signal?: AbortSignal): Promise<Status> {
  return request('/api/status', signal ? { signal } : {})
}

export function startConversation(signal: AbortSignal): Promise<StartResponse> {
  return request('/api/conversations', { method: 'POST', signal })
}

export function sendText(
  conversationId: string,
  text: string,
  via: InputVia,
  signal: AbortSignal,
): Promise<TurnResponse> {
  return request(`/api/conversations/${conversationId}/turns/text`, {
    method: 'POST',
    headers: json,
    body: JSON.stringify({ text, via }),
    signal,
  })
}

export function sendRecording(
  conversationId: string,
  wav: Blob,
  signal: AbortSignal,
): Promise<TurnResponse> {
  return request(`/api/conversations/${conversationId}/turns/voice`, {
    method: 'POST',
    headers: { 'content-type': 'audio/wav' },
    body: wav,
    signal,
  })
}

// Keepalive lets the request finish even when the page is closing
export function endConversation(conversationId: string, reason: EndReason): Promise<void> {
  return request(`/api/conversations/${conversationId}/end`, {
    method: 'POST',
    headers: json,
    body: JSON.stringify({ reason }),
    keepalive: true,
  })
}
