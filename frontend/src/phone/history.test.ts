import { describe, expect, it } from 'vitest'

import type { ConversationDetail, ConversationSummary } from '../api/conversations.ts'
import { describeStoredCall, previousCalls, toTranscript } from './history.ts'

const call: ConversationDetail = {
  id: 'c1',
  started_at: '2026-11-05T13:00:00Z',
  ended_at: '2026-11-05T13:02:05Z',
  end_reason: 'hangup',
  caller_phone: '+4915122000201',
  language: 'de',
  feedback_rating: null,
  feedback_comment: null,
  messages: [
    {
      id: 1,
      role: 'assistant',
      source: 'template',
      text: 'Hello, this is Carrie.',
      interrupted: false,
      created_at: '2026-11-05T13:00:00Z',
      tool_calls: null,
    },
    {
      id: 2,
      role: 'user',
      source: 'voice',
      text: 'Meine Wallbox lädt nicht.',
      interrupted: false,
      created_at: '2026-11-05T13:00:10Z',
      tool_calls: null,
    },
    {
      id: 3,
      role: 'assistant',
      source: 'llm',
      text: 'Ich habe Ihren Vorgang gefunden.',
      interrupted: true,
      created_at: '2026-11-05T13:00:20Z',
      tool_calls: [{ name: 'find_open_tickets', status: 'ok', label: 'Open tickets: CC-10006' }],
    },
  ],
}

function summary(id: string, messageCount: number): ConversationSummary {
  const { started_at, ended_at, end_reason, caller_phone, language } = call
  return {
    id,
    started_at,
    ended_at,
    end_reason,
    caller_phone,
    language,
    feedback_rating: null,
    feedback_comment: null,
    message_count: messageCount,
  }
}

describe('toTranscript', () => {
  it('puts the tools of a turn right before its reply', () => {
    const entries = toTranscript(call)

    expect(entries.map((e) => (e.kind === 'tool' ? e.label : e.text))).toEqual([
      'Hello, this is Carrie.',
      'Meine Wallbox lädt nicht.',
      'Open tickets: CC-10006',
      'Ich habe Ihren Vorgang gefunden.',
    ])
    expect(entries[3]).toMatchObject({ kind: 'message', interrupted: true })
  })
})

describe('previousCalls', () => {
  it('leaves out the call on screen and calls with only the greeting', () => {
    const calls = [summary('now', 6), summary('greeting-only', 1), summary('earlier', 4)]

    expect(previousCalls(calls, 'now').map((c) => c.id)).toEqual(['earlier'])
  })
})

describe('describeStoredCall', () => {
  it('names the length and how the call ended', () => {
    expect(describeStoredCall(call)).toMatch(/· 02:05 · hung up$/)
  })

  it('says when a call is still running', () => {
    expect(describeStoredCall({ ...call, ended_at: null, end_reason: null })).toMatch(
      /still running$/,
    )
  })
})
