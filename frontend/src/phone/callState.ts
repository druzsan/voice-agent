import type { ServerMessage } from '../api/callProtocol.ts'
import type { Role, Source } from '../api/conversations.ts'

// The backend decides the call's state; the page shows it. The caller can
// talk or type at any time: the backend queues what arrives during a turn,
// and talking over a reply interrupts it.
export type Phase =
  | 'idle' // no call yet
  | 'connecting' // dialing
  | 'listening' // waiting for the caller
  | 'thinking' // the backend works on an answer
  | 'speaking' // the answer is spoken
  | 'ended' // hung up; the transcript stays

export interface TranscriptEntry {
  id: number
  role: Role
  source: Source
  text: string
  interrupted: boolean
}

export interface CallState {
  phase: Phase
  conversationId: string | null
  messages: TranscriptEntry[]
  // The reply as the model writes it, until it's stored
  draft: { turn: number; text: string } | null
  callerSpeaking: boolean
  muted: boolean
  microphone: 'starting' | 'on' | 'unavailable'
  startedAt: number | null
  endedAt: number | null
  // Shown below the transcript, e.g. "Please wait for the answer."
  notice: string | null
}

export type CallAction =
  | { type: 'dial' }
  | { type: 'received'; message: ServerMessage; at: number }
  | { type: 'microphone'; available: boolean; notice?: string }
  | { type: 'muted'; muted: boolean }
  | { type: 'disconnected'; at: number }
  | { type: 'hungUp'; at: number }

export const initialCallState: CallState = {
  phase: 'idle',
  conversationId: null,
  messages: [],
  draft: null,
  callerSpeaking: false,
  muted: false,
  microphone: 'starting',
  startedAt: null,
  endedAt: null,
  notice: null,
}

export function isInCall(phase: Phase): boolean {
  return phase === 'listening' || phase === 'thinking' || phase === 'speaking'
}

const END_NOTICES: Partial<Record<string, string>> = {
  timeout: 'The call reached its time limit.',
  error: 'The call ended because of an error.',
}

function receive(state: CallState, message: ServerMessage, at: number): CallState {
  switch (message.type) {
    case 'call_started':
      return state.phase === 'connecting'
        ? { ...state, phase: 'thinking', conversationId: message.conversation_id, startedAt: at }
        : state
    case 'state':
      return { ...state, phase: message.state }
    case 'caller_speech':
      return { ...state, callerSpeaking: message.active }
    case 'user_message':
      return {
        ...state,
        notice: null,
        messages: [
          ...state.messages,
          {
            id: message.id,
            role: 'user',
            source: message.source,
            text: message.text,
            interrupted: false,
          },
        ],
      }
    case 'assistant_delta':
      return {
        ...state,
        draft:
          state.draft?.turn === message.turn
            ? { turn: message.turn, text: state.draft.text + message.text }
            : { turn: message.turn, text: message.text },
      }
    case 'assistant_message':
      return {
        ...state,
        draft: state.draft?.turn === message.turn ? null : state.draft,
        messages: [
          ...state.messages,
          {
            id: message.id,
            role: 'assistant',
            source: message.source,
            text: message.text,
            interrupted: message.interrupted,
          },
        ],
      }
    case 'error':
      return { ...state, notice: message.message }
    case 'call_ended':
      return {
        ...state,
        phase: 'ended',
        endedAt: at,
        draft: null,
        callerSpeaking: false,
        notice: END_NOTICES[message.reason] ?? null,
      }
    case 'audio':
    case 'interrupted':
    case 'turn_done':
      return state
  }
}

export function callReducer(state: CallState, action: CallAction): CallState {
  switch (action.type) {
    case 'dial':
      return state.phase === 'idle' || state.phase === 'ended'
        ? { ...initialCallState, phase: 'connecting' }
        : state
    case 'received':
      // Late messages of a call that's over change nothing
      return state.phase === 'connecting' || isInCall(state.phase)
        ? receive(state, action.message, action.at)
        : state
    case 'microphone':
      return state.phase === 'idle' || state.phase === 'ended'
        ? state
        : {
            ...state,
            microphone: action.available ? 'on' : 'unavailable',
            notice: action.notice ?? state.notice,
          }
    case 'muted':
      return {
        ...state,
        muted: action.muted,
        callerSpeaking: action.muted ? false : state.callerSpeaking,
      }
    case 'disconnected':
      if (state.phase === 'connecting') {
        return { ...initialCallState, notice: "Couldn't start the call. Please try again." }
      }
      return isInCall(state.phase)
        ? {
            ...state,
            phase: 'ended',
            endedAt: action.at,
            draft: null,
            notice: 'The connection was lost.',
          }
        : state
    case 'hungUp':
      return state.phase === 'connecting' || isInCall(state.phase)
        ? {
            ...state,
            phase: 'ended',
            endedAt: action.at,
            draft: null,
            callerSpeaking: false,
            notice: null,
          }
        : state
  }
}
