import type { ConversationDetail, ConversationSummary } from '../api/conversations.ts'
import type { TranscriptEntry } from './callState.ts'

// A stored call as the transcript shows it: Carrie's tool calls come right
// before the reply of their turn, as they did in the call
export function toTranscript(detail: ConversationDetail): TranscriptEntry[] {
  return detail.messages.flatMap((message): TranscriptEntry[] => [
    ...(message.tool_calls ?? []).map((tool, index): TranscriptEntry => ({
      kind: 'tool',
      id: `tool-${String(message.id)}-${String(index)}`,
      name: tool.name,
      status: tool.status,
      label: tool.label,
    })),
    {
      kind: 'message',
      id: message.id,
      role: message.role,
      source: message.source,
      text: message.text,
      interrupted: message.interrupted,
    },
  ])
}

// Earlier calls worth looking at: not the one on screen, and with more than
// the greeting
export function previousCalls(
  calls: readonly ConversationSummary[],
  current: string | null,
): ConversationSummary[] {
  return calls.filter((call) => call.id !== current && call.message_count > 1)
}

const END_REASONS: Record<string, string> = {
  hangup: 'hung up',
  page_closed: 'page closed',
  disconnect: 'connection lost',
  timeout: 'time limit',
  error: 'error',
}

// "5 Nov, 14:33 · 02:13 · hung up"
export function describeStoredCall(call: ConversationSummary | ConversationDetail): string {
  const started = new Date(call.started_at)
  const parts = [
    started.toLocaleString(undefined, {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    }),
  ]
  if (call.ended_at) {
    const seconds = Math.max(
      0,
      Math.round((new Date(call.ended_at).getTime() - started.getTime()) / 1000),
    )
    parts.push(
      `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`,
    )
  }
  if (call.end_reason) {
    parts.push(END_REASONS[call.end_reason] ?? call.end_reason)
  } else if (!call.ended_at) {
    parts.push('still running')
  }
  return parts.join(' · ')
}
