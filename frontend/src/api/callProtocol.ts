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

export interface AudioClip {
  type: 'audio'
  clip: number
  turn: number
  text: string
  duration_ms: number
  wav_base64: string
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

export interface TurnDone {
  type: 'turn_done'
  turn: number
  timings_ms: Record<string, number>
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
  | AudioClip
  | AssistantMessage
  | Interrupted
  | TurnDone
  | CallError
  | CallEnded

const SERVER_MESSAGE_TYPES: ReadonlySet<string> = new Set<ServerMessage['type']>([
  'call_started',
  'state',
  'caller_speech',
  'user_message',
  'assistant_delta',
  'audio',
  'assistant_message',
  'interrupted',
  'turn_done',
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
