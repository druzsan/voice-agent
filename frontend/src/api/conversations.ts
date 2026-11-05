// The backend's REST API (backend/voice_agent/api/). Calls themselves run
// over the WebSocket in callProtocol.ts.

export type Role = 'user' | 'assistant'
export type Source = 'voice' | 'keyboard' | 'keypad' | 'llm' | 'template'
export type InputVia = 'keyboard' | 'keypad'
export type EndReason = 'hangup' | 'page_closed' | 'disconnect' | 'timeout' | 'error'

export interface Status {
  database: 'ok' | 'error'
  // Languages Carrie holds conversations in, e.g. ['en', 'de']
  languages: string[]
  llm: { provider: string; model: string | null; configured: boolean }
  // fallback_model: push-to-talk, and live calls when live recognition fails
  stt: { provider: string; model: string; fallback_model: string | null; max_recording_s: number }
  tts: { provider: string; model: string; speed: number | null }
}

export async function fetchStatus(signal?: AbortSignal): Promise<Status> {
  const response = await fetch('/api/status', signal ? { signal } : {})
  if (!response.ok) {
    throw new Error(`The server answered with status ${String(response.status)}.`)
  }
  // The backend's response model guarantees the shape
  return (await response.json()) as Status
}

export type FeedbackRating = 'up' | 'down'

// A stored call, as listed (newest first)
export interface ConversationSummary {
  id: string
  started_at: string
  ended_at: string | null
  end_reason: EndReason | null
  caller_phone: string | null
  language: string | null
  message_count: number
  // The caller's feedback on the call
  feedback_rating: FeedbackRating | null
  feedback_comment: string | null
}

// A tool Carrie used in a turn, as the transcript shows it
export interface ToolCallRecord {
  name: string
  status: 'ok' | 'refused' | 'failed'
  label: string
}

export interface StoredMessage {
  id: number
  role: Role
  source: Source
  text: string
  interrupted: boolean
  created_at: string
  tool_calls: ToolCallRecord[] | null
}

export interface ConversationDetail extends Omit<ConversationSummary, 'message_count'> {
  messages: StoredMessage[]
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, signal ? { signal } : {})
  if (!response.ok) {
    throw new Error(`The server answered with status ${String(response.status)}.`)
  }
  // The backend's response models guarantee the shape
  return (await response.json()) as T
}

export function fetchConversations(
  limit = 50,
  signal?: AbortSignal,
): Promise<ConversationSummary[]> {
  return getJson<ConversationSummary[]>(`/api/conversations?limit=${String(limit)}`, signal)
}

export function fetchConversation(id: string, signal?: AbortSignal): Promise<ConversationDetail> {
  return getJson<ConversationDetail>(`/api/conversations/${encodeURIComponent(id)}`, signal)
}

// Thumbs up or down on a call, with an optional comment; replaces earlier feedback
export async function sendFeedback(
  conversationId: string,
  rating: FeedbackRating,
  comment: string,
): Promise<void> {
  const response = await fetch(
    `/api/conversations/${encodeURIComponent(conversationId)}/feedback`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating, comment: comment.trim() || null }),
    },
  )
  if (!response.ok) {
    throw new Error(`The server answered with status ${String(response.status)}.`)
  }
}
