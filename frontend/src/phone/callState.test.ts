import { describe, expect, it } from 'vitest'

import type { ServerMessage } from '../api/callProtocol.ts'
import { type CallAction, callReducer, type CallState, initialCallState } from './callState.ts'

function received(message: ServerMessage, at = 1000): CallAction {
  return { type: 'received', message, at }
}

function run(...actions: CallAction[]): CallState {
  return actions.reduce(callReducer, initialCallState)
}

const connected: CallAction[] = [
  { type: 'dial' },
  received({
    type: 'call_started',
    conversation_id: 'c1',
    caller_phone: '+4915112345678',
    language: 'en',
    supported_languages: ['en', 'de'],
  }),
  received({ type: 'state', state: 'listening' }),
]

describe('callReducer', () => {
  it('follows the state the backend announces', () => {
    const state = run(...connected, received({ type: 'state', state: 'speaking' }))

    expect(state.phase).toBe('speaking')
    expect(state.conversationId).toBe('c1')
    expect(state.startedAt).toBe(1000)
  })

  it('shows the reply while it streams and replaces it with the stored one', () => {
    const streaming = run(
      ...connected,
      received({ type: 'user_message', id: 2, text: 'Hi', source: 'voice' }),
      received({ type: 'assistant_delta', turn: 2, text: 'Hello ' }),
      received({ type: 'assistant_delta', turn: 2, text: 'there.' }),
    )
    const stored = callReducer(
      streaming,
      received({
        type: 'assistant_message',
        id: 3,
        turn: 2,
        text: 'Hello there.',
        source: 'llm',
        interrupted: true,
      }),
    )

    expect(streaming.draft).toEqual({ turn: 2, text: 'Hello there.' })
    expect(stored.draft).toBeNull()
    expect(
      stored.messages.flatMap((m) =>
        m.kind === 'message' ? [[m.role, m.text, m.interrupted]] : [],
      ),
    ).toEqual([
      ['user', 'Hi', false],
      ['assistant', 'Hello there.', true],
    ])
  })

  it('starts a new draft for the fixed reply after a cut-off one', () => {
    const state = run(
      ...connected,
      received({ type: 'assistant_delta', turn: 2, text: 'Let me' }),
      received({
        type: 'assistant_message',
        id: 3,
        turn: 2,
        text: 'Let me',
        source: 'llm',
        interrupted: true,
      }),
      received({ type: 'assistant_delta', turn: 2, text: 'Sorry.' }),
    )

    expect(state.draft).toEqual({ turn: 2, text: 'Sorry.' })
  })

  it('tells why the backend ended the call', () => {
    const state = run(...connected, received({ type: 'call_ended', reason: 'timeout' }, 5000))

    expect(state.phase).toBe('ended')
    expect(state.endedAt).toBe(5000)
    expect(state.notice).toBe('The call reached its time limit.')
  })

  it('ends the call when the connection drops', () => {
    expect(run(...connected, { type: 'disconnected', at: 2000 })).toMatchObject({
      phase: 'ended',
      notice: 'The connection was lost.',
    })
  })

  it('reports a call that never started', () => {
    expect(run({ type: 'dial' }, { type: 'disconnected', at: 2000 })).toMatchObject({
      phase: 'idle',
      notice: "Couldn't start the call. Please try again.",
    })
  })

  it('keeps the transcript after hanging up and ignores late messages', () => {
    const ended = run(
      ...connected,
      received({ type: 'user_message', id: 2, text: 'Bye', source: 'keyboard' }),
      { type: 'hungUp', at: 5000 },
    )
    const late = callReducer(ended, received({ type: 'call_ended', reason: 'hangup' }))

    expect(late).toBe(ended)
    expect(ended.messages).toHaveLength(1)
  })

  it('starts a fresh call after the last one ended', () => {
    const state = run(...connected, { type: 'hungUp', at: 5000 }, { type: 'dial' })

    expect(state).toEqual({ ...initialCallState, phase: 'connecting' })
  })
})

describe('callReducer with Carrie', () => {
  it('keeps who calls and in which language', () => {
    const state = run(...connected, received({ type: 'language', language: 'de' }))

    expect(state.callerPhone).toBe('+4915112345678')
    expect(state.supportedLanguages).toEqual(['en', 'de'])
    expect(state.language).toBe('de')
  })

  it('lists tool calls between the messages', () => {
    const state = run(
      ...connected,
      received({ type: 'user_message', id: 2, text: 'My ticket?', source: 'voice' }),
      received({
        type: 'tool',
        turn: 2,
        name: 'find_open_tickets',
        status: 'refused',
        label: 'No ticket for these details (1 of 2)',
        data: {},
      }),
    )

    expect(state.messages.map((m) => m.kind)).toEqual(['message', 'tool'])
    expect(state.messages[1]).toMatchObject({ status: 'refused', name: 'find_open_tickets' })
  })

  it('is still in the call while on hold', () => {
    const onHold = run(...connected, received({ type: 'state', state: 'on_hold' }))
    const later = callReducer(onHold, received({ type: 'state', state: 'speaking' }))

    expect(onHold.phase).toBe('on_hold')
    expect(later.phase).toBe('speaking')
  })
})
