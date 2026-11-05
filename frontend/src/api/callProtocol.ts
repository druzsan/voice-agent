// The messages of a live call over WS /api/call, mirrored by hand from
// backend/voice_agent/conversation/protocol.py. Besides these JSON messages,
// the browser sends the microphone as binary frames: 16 kHz mono PCM16.

import type { EndReason, InputVia, Source } from './conversations.ts'

export type CallState = 'listening' | 'thinking' | 'speaking'

// Browser to server
export type ClientMessage =
  | { type: 'text'; text: string; via: InputVia }
  // A clip played to the end (or nearly: at least 90 % of it)
  | { type: 'played'; clip: number }
  | { type: 'mute'; muted: boolean }
  | { type: 'hangup' }

// Server to browser
export interface CallStarted {
  type: 'call_started'
  conversation_id: string
}

export interface StateChanged {
  type: 'state'
  state: CallState
}

export interface CallerSpeech {
  type: 'caller_speech'
  active: boolean
}

export interface UserMessage {
  type: 'user_message'
  id: number
  text: string
  source: Source
}

export interface AssistantDelta {
  type: 'assistant_delta'
  turn: number
  text: string
}

// More audio of a spoken sentence (clip); clips play in order of `clip`,
// their pieces in the order they arrive
export interface AudioPiece {
  type: 'audio'
  clip: number
  turn: number
  sample_rate: number
  // Mono 16-bit little-endian PCM
  pcm_base64: string
}

// The clip's last piece has been sent
export interface AudioEnd {
  type: 'audio_end'
  clip: number
  turn: number
  text: string
  duration_ms: number
}

export interface AssistantMessage {
  type: 'assistant_message'
  id: number
  turn: number
  text: string
  source: Source
  interrupted: boolean
}

export interface Interrupted {
  type: 'interrupted'
  turn: number
}

export type Service = 'stt' | 'llm' | 'tts'

// What one or more calls of one model consumed (backend/voice_agent/usage.py)
export interface Usage {
  service: Service
  model: string
  calls: number
  input_tokens: number
  output_tokens: number
  audio_in_s: number
  audio_out_s: number
  duration_ms: number
  // null when the model has no known price
  cost_usd: number | null
}

export interface TurnDone {
  type: 'turn_done'
  turn: number
  timings_ms: Record<string, number>
  usage: Usage[]
}

// Consumption outside of a turn, e.g. recognizing speech that was noise
export interface UsageReport {
  type: 'usage'
  usage: Usage[]
}

export interface CallError {
  type: 'error'
  code: 'invalid_message' | 'stt_failed' | 'busy'
  message: string
}

export interface CallEnded {
  type: 'call_ended'
  reason: EndReason
}

export type ServerMessage =
  | CallStarted
  | StateChanged
  | CallerSpeech
  | UserMessage
  | AssistantDelta
  | AudioPiece
  | AudioEnd
  | AssistantMessage
  | Interrupted
  | TurnDone
  | UsageReport
  | CallError
  | CallEnded

const SERVER_MESSAGE_TYPES: ReadonlySet<string> = new Set<ServerMessage['type']>([
  'call_started',
  'state',
  'caller_speech',
  'user_message',
  'assistant_delta',
  'audio',
  'audio_end',
  'assistant_message',
  'interrupted',
  'turn_done',
  'usage',
  'error',
  'call_ended',
])

// A message from the server, or null for anything this version doesn't know
export function parseServerMessage(data: string): ServerMessage | null {
  let parsed: unknown
  try {
    parsed = JSON.parse(data)
  } catch {
    return null
  }
  if (
    typeof parsed === 'object' &&
    parsed !== null &&
    'type' in parsed &&
    typeof parsed.type === 'string' &&
    SERVER_MESSAGE_TYPES.has(parsed.type)
  ) {
    // The backend's message models guarantee the rest of the shape
    return parsed as ServerMessage
  }
  return null
}

export function callUrl(location: Location = window.location): string {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${location.host}/api/call`
}
