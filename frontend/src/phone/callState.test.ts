import { describe, expect, it } from 'vitest'

import type { Message } from '../api/conversations.ts'
import { type CallAction, callReducer, type CallState, initialCallState } from './callState.ts'

function message(id: number, role: Message['role'], text: string): Message {
  return {
    id,
    role,
    source: role === 'user' ? 'keyboard' : 'llm',
    text,
    created_at: '2026-11-04T12:00:00Z',
    timings_ms: null,
  }
}

function run(...actions: CallAction[]): CallState {
  return actions.reduce(callReducer, initialCallState)
}

const greeting = message(1, 'assistant', 'Hello')
const connected: CallAction[] = [
  { type: 'start' },
  { type: 'started', conversationId: 'c1', greeting, at: 1000 },
  { type: 'played' },
]

describe('callReducer', () => {
  it('is ready for the caller once the greeting has played', () => {
    const state = run(...connected)

    expect(state.phase).toBe('ready')
    expect(state.messages).toEqual([greeting])
    expect(state.startedAt).toBe(1000)
  })

  it('adds both sides of a turn and speaks the answer', () => {
    const state = run(
      ...connected,
      { type: 'sending' },
      {
        type: 'answered',
        user: message(2, 'user', 'Hi'),
        assistant: message(3, 'assistant', 'Hi there'),
      },
    )

    expect(state.phase).toBe('playing')
    expect(state.messages.map((m) => m.text)).toEqual(['Hello', 'Hi', 'Hi there'])
  })

  it('takes no input while an answer is pending or playing', () => {
    const waiting = run(...connected, { type: 'sending' })

    expect(callReducer(waiting, { type: 'recording' })).toBe(waiting)
    expect(callReducer(waiting, { type: 'sending' })).toBe(waiting)
  })

  it('goes back to ready with a notice when a turn fails', () => {
    const state = run(...connected, { type: 'sending' }, { type: 'failed', notice: 'No speech' })

    expect(state.phase).toBe('ready')
    expect(state.notice).toBe('No speech')
  })

  it('keeps the transcript after hanging up and ignores late answers', () => {
    const ended = run(...connected, { type: 'sending' }, { type: 'hungUp', at: 5000 })
    const late = callReducer(ended, {
      type: 'answered',
      user: message(2, 'user', 'Hi'),
      assistant: message(3, 'assistant', 'Hi there'),
    })

    expect(late).toBe(ended)
    expect(ended.phase).toBe('ended')
    expect(ended.messages).toEqual([greeting])
    expect(ended.endedAt).toBe(5000)
  })

  it('starts a fresh call after the last one ended', () => {
    const state = run(...connected, { type: 'hungUp', at: 5000 }, { type: 'start' })

    expect(state).toEqual({ ...initialCallState, phase: 'starting' })
  })
})
