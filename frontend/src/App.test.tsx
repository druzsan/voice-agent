import { MantineProvider } from '@mantine/core'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Message, Status, TurnResponse } from './api/conversations.ts'
import App from './App.tsx'
import { theme } from './theme.ts'

// No real audio in jsdom: clips "play" instantly, the microphone is unavailable
vi.mock('./audio/playback.ts', () => ({
  playClip: () => ({ done: Promise.resolve(), stop: vi.fn() }),
  playKeyTone: vi.fn(),
}))
vi.mock('./audio/recorder.ts', () => ({
  startRecording: () => Promise.reject(new Error('No microphone in tests')),
}))

const status: Status = {
  database: 'ok',
  llm: { provider: 'requesty', model: 'azure/gpt-4.1-mini', configured: true },
  stt: { model: 'small.en', max_recording_s: 30 },
  tts: { model: 'en_US-lessac-medium' },
}

function message(id: number, role: Message['role'], source: Message['source'], text: string) {
  return { id, role, source, text, created_at: '2026-11-04T12:00:00Z', timings_ms: null }
}

const audio = { media_type: 'audio/wav', wav_base64: 'UklGRg==', duration_ms: 100 }

interface Call {
  url: string
  method: string
  body: unknown
}

function mockBackend() {
  const calls: Call[] = []
  let nextId = 2
  const fetchMock = vi.fn<typeof fetch>((input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const method = init?.method ?? 'GET'
    const body: unknown = typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body
    calls.push({ url, method, body })
    if (url === '/api/status') {
      return Promise.resolve(Response.json(status))
    }
    if (url === '/api/conversations' && method === 'POST') {
      return Promise.resolve(
        Response.json(
          {
            conversation: { id: 'c1', started_at: '', ended_at: null },
            greeting: message(1, 'assistant', 'template', 'Hello, how can I help you?'),
            audio,
          },
          { status: 201 },
        ),
      )
    }
    if (url.endsWith('/turns/text')) {
      const { text, via } = body as { text: string; via: Message['source'] }
      const answer: TurnResponse = {
        user_message: message(nextId++, 'user', via, text),
        assistant_message: message(nextId++, 'assistant', 'llm', `You said: ${text}`),
        audio: null,
      }
      return Promise.resolve(Response.json(answer))
    }
    if (url.endsWith('/end')) {
      return Promise.resolve(new Response(null, { status: 204 }))
    }
    return Promise.resolve(new Response(null, { status: 404 }))
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

function renderApp() {
  render(
    <MantineProvider theme={theme}>
      <App />
    </MantineProvider>,
  )
}

async function dial() {
  await userEvent.click(await screen.findByRole('button', { name: 'Start call' }))
  await screen.findByText('Hello, how can I help you?')
  await waitFor(() => {
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeEnabled()
  })
}

describe('Phone', () => {
  let calls: Call[]

  beforeEach(() => {
    calls = mockBackend()
  })

  it('shows the configured model before the call', async () => {
    renderApp()

    expect(await screen.findByText('LLM: requesty · azure/gpt-4.1-mini')).toBeInTheDocument()
  })

  it('greets the caller and answers a typed message', async () => {
    renderApp()
    await dial()

    await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'Hi there{Enter}')

    expect(await screen.findByText('You said: Hi there')).toBeInTheDocument()
    expect(calls.find((call) => call.url.endsWith('/turns/text'))?.body).toEqual({
      text: 'Hi there',
      via: 'keyboard',
    })
  })

  it('sends keypad digits with the # key', async () => {
    renderApp()
    await dial()

    await userEvent.click(screen.getByRole('button', { name: 'Show keypad' }))
    for (const key of ['4', '7', '1', '1']) {
      await userEvent.click(screen.getByRole('button', { name: key }))
    }
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('4711')
    await userEvent.click(screen.getByRole('button', { name: '# (send)' }))

    expect(await screen.findByText('You said: 4711')).toBeInTheDocument()
    expect(calls.find((call) => call.url.endsWith('/turns/text'))?.body).toEqual({
      text: '4711',
      via: 'keypad',
    })
  })

  it('explains when the microphone is not available', async () => {
    renderApp()
    await dial()

    await userEvent.click(screen.getByRole('button', { name: 'Talk' }))

    expect(await screen.findByText('No microphone in tests')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeEnabled()
  })

  it('hangs up, keeps the transcript and can call again', async () => {
    renderApp()
    await dial()

    await userEvent.click(screen.getByRole('button', { name: 'Hang up' }))

    expect(await screen.findByText(/Call ended/)).toBeInTheDocument()
    expect(screen.getByText('Hello, how can I help you?')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Call again' })).toBeInTheDocument()
    expect(calls.find((call) => call.url === '/api/conversations/c1/end')?.body).toEqual({
      reason: 'hangup',
    })
  })

  it('says so when the backend is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockRejectedValue(new TypeError('offline')))
    renderApp()

    expect(await screen.findByText(/backend is not reachable/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start call' })).toBeDisabled()
  })
})
