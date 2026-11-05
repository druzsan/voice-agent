import type { Message } from '../api/conversations.ts'

// Strictly one thing at a time: the caller talks or types only when the
// call is `ready`, never while an answer is pending or playing.
export type Phase =
  | 'idle' // no call yet
  | 'starting' // dialing
  | 'ready' // waiting for the caller
  | 'recording' // the caller talks
  | 'waiting' // the backend answers
  | 'playing' // the answer is spoken
  | 'ended' // hung up; the transcript stays

export interface CallState {
  phase: Phase
  conversationId: string | null
  messages: Message[]
  startedAt: number | null
  endedAt: number | null
  // Shown below the transcript, e.g. "Sorry, I didn't catch that."
  notice: string | null
}

export type CallAction =
  | { type: 'start' }
  | { type: 'started'; conversationId: string; greeting: Message; at: number }
  | { type: 'startFailed'; notice: string }
  | { type: 'recording' }
  | { type: 'sending' }
  | { type: 'answered'; user: Message; assistant: Message }
  | { type: 'failed'; notice: string }
  | { type: 'played' }
  | { type: 'hungUp'; at: number }

export const initialCallState: CallState = {
  phase: 'idle',
  conversationId: null,
  messages: [],
  startedAt: null,
  endedAt: null,
  notice: null,
}

export function isInCall(phase: Phase): boolean {
  return phase !== 'idle' && phase !== 'starting' && phase !== 'ended'
}

export function callReducer(state: CallState, action: CallAction): CallState {
  switch (action.type) {
    case 'start':
      return state.phase === 'idle' || state.phase === 'ended'
        ? { ...initialCallState, phase: 'starting' }
        : state
    case 'started':
      return state.phase === 'starting'
        ? {
            ...state,
            phase: 'playing',
            conversationId: action.conversationId,
            messages: [action.greeting],
            startedAt: action.at,
          }
        : state
    case 'startFailed':
      return state.phase === 'starting' ? { ...initialCallState, notice: action.notice } : state
    case 'recording':
      return state.phase === 'ready' ? { ...state, phase: 'recording', notice: null } : state
    case 'sending':
      return state.phase === 'ready' || state.phase === 'recording'
        ? { ...state, phase: 'waiting', notice: null }
        : state
    case 'answered':
      return state.phase === 'waiting'
        ? {
            ...state,
            phase: 'playing',
            messages: [...state.messages, action.user, action.assistant],
          }
        : state
    case 'failed':
      return isInCall(state.phase) ? { ...state, phase: 'ready', notice: action.notice } : state
    case 'played':
      return state.phase === 'playing' ? { ...state, phase: 'ready' } : state
    case 'hungUp':
      return isInCall(state.phase) || state.phase === 'starting'
        ? { ...state, phase: 'ended', endedAt: action.at, notice: null }
        : state
  }
}
