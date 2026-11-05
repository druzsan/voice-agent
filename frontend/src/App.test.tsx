import { MantineProvider } from '@mantine/core'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ClientMessage, ServerMessage } from './api/callProtocol.ts'
import type { Status } from './api/conversations.ts'
import App from './App.tsx'
import { theme } from './theme.ts'

// No real audio in jsdom: clips "play" at once; the test decides whether
// there's a microphone
const audio = vi.hoisted(() => ({
  frames: null as ((pcm: Int16Array<ArrayBuffer>) => void) | null,
  microphone: true,
  stopped: 0,
}))
vi.mock('./audio/playback.ts', () => ({
  ClipPlayer: class {
    private readonly onPlayed: (clip: number) => void
    constructor(onPlayed: (clip: number) => void) {
      this.onPlayed = onPlayed
    }
    unlock = vi.fn()
    append = vi.fn()
    end(clip: number) {
      this.onPlayed(clip)
    }
    stop() {
      audio.stopped += 1
    }
  },
  playKeyTone: vi.fn(),
}))
vi.mock('./audio/microphone.ts', () => ({
  openMicrophone: (onFrame: (pcm: Int16Array<ArrayBuffer>) => void) => {
    if (!audio.microphone) {
      return Promise.reject(new Error('No microphone in tests.'))
    }
    audio.frames = onFrame
    return Promise.resolve({ close: vi.fn() })
  },
}))

const status: Status = {
  database: 'ok',
  languages: ['en', 'de'],
  llm: { provider: 'requesty', model: 'azure/gpt-4.1-mini', configured: true },
  stt: {
    provider: 'openai',
    model: 'openai/gpt-live-transcribe',
    fallback_model: 'openai/gpt-4o-mini-transcribe',
    max_recording_s: 30,
  },
  tts: { provider: 'openai', model: 'openai/gpt-4o-mini-tts/marin', speed: 1.25 },
}

// The backend's end of the call
class FakeSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  static last: FakeSocket | null = null

  readonly url: string
  readyState = FakeSocket.CONNECTING
  readonly sent: (ClientMessage | Int16Array)[] = []
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onopen: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeSocket.last = this
  }

  send(data: string | Int16Array) {
    this.sent.push(typeof data === 'string' ? (JSON.parse(data) as ClientMessage) : data)
  }

  close() {
    this.readyState = FakeSocket.CLOSED
  }

  open() {
    this.readyState = FakeSocket.OPEN
    this.onopen?.()
  }

  push(...messages: ServerMessage[]) {
    act(() => {
      for (const message of messages) {
        this.onmessage?.({ data: JSON.stringify(message) })
      }
    })
  }

  drop() {
    act(() => {
      this.readyState = FakeSocket.CLOSED
      this.onclose?.()
    })
  }

  messages(): ClientMessage[] {
    return this.sent.filter((data): data is ClientMessage => !(data instanceof Int16Array))
  }
}

function renderApp() {
  render(
    <MantineProvider theme={theme}>
      <App />
    </MantineProvider>,
  )
}

const greeting = 'Hello, how can I help you?'

async function dial(): Promise<FakeSocket> {
  await userEvent.click(await screen.findByRole('button', { name: 'Start call' }))
  const socket = FakeSocket.last
  if (socket === null) {
    throw new Error('No connection')
  }
  act(() => {
    socket.open()
  })
  socket.push(
    {
      type: 'call_started',
      conversation_id: 'c1',
      caller_phone: '+4915112345678',
      language: 'en',
      supported_languages: ['en', 'de'],
    },
    { type: 'state', state: 'speaking' },
    { type: 'assistant_delta', turn: 1, text: greeting },
    { type: 'audio', clip: 1, turn: 1, sample_rate: 24000, pcm_base64: 'AAAA' },
    { type: 'audio_end', clip: 1, turn: 1, text: greeting, duration_ms: 900 },
    {
      type: 'assistant_message',
      id: 1,
      turn: 1,
      text: greeting,
      source: 'template',
      interrupted: false,
    },
    { type: 'state', state: 'listening' },
  )
  await screen.findByText(greeting)
  return socket
}

describe('Phone', () => {
  beforeEach(() => {
    audio.microphone = true
    audio.frames = null
    audio.stopped = 0
    FakeSocket.last = null
    vi.stubGlobal('WebSocket', FakeSocket)
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>(() => Promise.resolve(Response.json(status))),
    )
  })

  it('shows the configured model before the call', async () => {
    renderApp()

    expect(await screen.findByText('LLM: requesty · azure/gpt-4.1-mini')).toBeInTheDocument()
  })

  it('connects, greets and acknowledges the played clips', async () => {
    renderApp()
    const socket = await dial()

    // From a random German mobile number
    expect(socket.url).toMatch(/^ws:\/\/localhost:3000\/api\/call\?phone=%2B49%201\d{2}%20\d{8}$/)
    expect(socket.messages()).toEqual([{ type: 'played', clip: 1 }])
    expect(await screen.findByText(/Listening…/)).toBeInTheDocument()
  })

  it('streams the microphone and shows the answer as it is written', async () => {
    renderApp()
    const socket = await dial()
    await waitFor(() => {
      expect(audio.frames).not.toBeNull()
    })

    audio.frames?.(new Int16Array(512))
    socket.push(
      { type: 'caller_speech', active: true },
      { type: 'caller_speech', active: false },
      { type: 'state', state: 'thinking' },
      { type: 'user_message', id: 2, text: 'What time is it?', source: 'voice' },
      { type: 'assistant_delta', turn: 2, text: 'It is ' },
    )

    expect(socket.sent.some((data) => data instanceof Int16Array)).toBe(true)
    expect(screen.getByText('What time is it?')).toBeInTheDocument()
    expect(screen.getByLabelText('Answer so far')).toHaveTextContent('It is')
  })

  it('sends typed messages at any time', async () => {
    renderApp()
    const socket = await dial()
    socket.push({ type: 'state', state: 'speaking' })

    await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'Hi there{Enter}')

    expect(socket.messages()).toContainEqual({ type: 'text', text: 'Hi there', via: 'keyboard' })
  })

  it('sends keypad digits with the # key', async () => {
    renderApp()
    const socket = await dial()

    await userEvent.click(screen.getByRole('button', { name: 'Show keypad' }))
    for (const key of ['4', '7', '1', '1']) {
      await userEvent.click(screen.getByRole('button', { name: key }))
    }
    expect(screen.getByRole('textbox', { name: 'Message' })).toHaveValue('4711')
    await userEvent.click(screen.getByRole('button', { name: '# (send)' }))

    expect(socket.messages()).toContainEqual({ type: 'text', text: '4711', via: 'keypad' })
  })

  it('shows the models in use', async () => {
    renderApp()

    const models = await screen.findByRole('table', { name: 'Models' })
    expect(models).toHaveTextContent(
      'openai/gpt-live-transcribe (fallback openai/gpt-4o-mini-transcribe)',
    )
    expect(models).toHaveTextContent('openai/gpt-4o-mini-tts/marin · speed 1.25')
  })

  it('adds up what the dialog consumed', async () => {
    renderApp()
    const socket = await dial()

    const usage = (service: 'stt' | 'llm' | 'tts', cost: number | null) => ({
      service,
      model: `${service}-model`,
      calls: 1,
      input_tokens: service === 'llm' ? 200 : 0,
      output_tokens: service === 'llm' ? 30 : 0,
      audio_in_s: service === 'stt' ? 2 : 0,
      audio_out_s: service === 'tts' ? 3 : 0,
      duration_ms: 500,
      cost_usd: cost,
    })
    socket.push(
      {
        type: 'turn_done',
        turn: 2,
        timings_ms: { stt: 600, first_audio: 2400 },
        usage: [usage('stt', 0.001), usage('llm', 0.002)],
      },
      {
        type: 'turn_done',
        turn: 3,
        timings_ms: { stt: 400, first_audio: 1600 },
        usage: [usage('llm', 0.002), usage('tts', null)],
      },
    )

    const table = screen.getByRole('table', { name: 'Usage of this dialog' })
    expect(table).toHaveTextContent('Language model2400 → 60')
    // The synthesis has no known price, so the total is a lower bound
    expect(table).toHaveTextContent('Total≥ $0.0050')
    const latency = screen.getByRole('table', { name: 'Latency of this dialog' })
    expect(latency).toHaveTextContent('First audio2.00 s1.60 s2')
  })

  it('stops speaking when the caller interrupts', async () => {
    renderApp()
    const socket = await dial()

    socket.push({ type: 'interrupted', turn: 2 })

    expect(audio.stopped).toBe(1)
  })

  it('mutes the microphone', async () => {
    renderApp()
    const socket = await dial()
    const mute = await screen.findByRole('button', { name: 'Mute' })
    await waitFor(() => {
      expect(mute).toBeEnabled()
    })

    await userEvent.click(mute)
    audio.frames?.(new Int16Array(512))

    expect(socket.messages()).toContainEqual({ type: 'mute', muted: true })
    expect(socket.sent.some((data) => data instanceof Int16Array)).toBe(false)
    expect(screen.getByRole('button', { name: 'Unmute' })).toBeInTheDocument()
  })

  it('explains when the microphone is not available', async () => {
    audio.microphone = false
    renderApp()
    await dial()

    expect(await screen.findByText(/No microphone in tests/)).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeEnabled()
  })

  it('hangs up, keeps the transcript and can call again', async () => {
    renderApp()
    const socket = await dial()

    await userEvent.click(screen.getByRole('button', { name: 'Hang up' }))

    expect(socket.messages()).toContainEqual({ type: 'hangup' })
    expect(socket.readyState).toBe(FakeSocket.CLOSED)
    expect(await screen.findByText(/Call ended/)).toBeInTheDocument()
    expect(screen.getByText(greeting)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Call again' })).toBeInTheDocument()
  })

  it('says so when the connection is lost', async () => {
    renderApp()
    const socket = await dial()

    socket.drop()

    expect(await screen.findByText('The connection was lost.')).toBeInTheDocument()
  })

  it('says so when the call cannot start', async () => {
    renderApp()
    await userEvent.click(await screen.findByRole('button', { name: 'Start call' }))

    FakeSocket.last?.drop()

    expect(await screen.findByText(/Couldn't start the call/)).toBeInTheDocument()
  })

  it('says so when the backend is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockRejectedValue(new TypeError('offline')))
    renderApp()

    expect(await screen.findByText(/backend is not reachable/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Start call' })).toBeDisabled()
  })

  it('calls from the number the caller typed', async () => {
    renderApp()
    const number = await screen.findByRole('textbox', { name: 'Your phone number' })
    await userEvent.clear(number)
    await userEvent.type(number, '+49 151 22000201')

    const socket = await dial()

    expect(socket.url).toBe('ws://localhost:3000/api/call?phone=%2B49%20151%2022000201')
  })

  it("can't call from a number that isn't German", async () => {
    renderApp()
    const number = await screen.findByRole('textbox', { name: 'Your phone number' })
    await userEvent.clear(number)
    await userEvent.type(number, '+44 20 7946 0958')

    expect(screen.getByRole('button', { name: 'Start call' })).toBeDisabled()
  })

  it('shows the tools Carrie used and the conversation language', async () => {
    renderApp()
    const socket = await dial()

    socket.push(
      { type: 'user_message', id: 2, text: 'Wann kommt mein Auto?', source: 'voice' },
      { type: 'language', language: 'de' },
      {
        type: 'tool',
        turn: 2,
        name: 'lookup_order',
        status: 'ok',
        label: 'Order 456789 verified',
        data: {},
      },
    )

    expect(await screen.findByText(/Order 456789 verified/)).toBeInTheDocument()
    expect(screen.getByLabelText('Conversation language')).toHaveTextContent('DE')
  })

  it('waits on hold after a transfer until the caller continues', async () => {
    renderApp()
    const socket = await dial()

    socket.push({ type: 'state', state: 'on_hold' })
    const hold = await screen.findByRole('button', { name: 'On hold, continue talking' })
    expect(screen.queryByRole('textbox', { name: 'Message' })).not.toBeInTheDocument()
    await userEvent.click(hold)

    expect(socket.messages()).toContainEqual({ type: 'resume' })
    socket.push({ type: 'state', state: 'speaking' })
    expect(await screen.findByRole('textbox', { name: 'Message' })).toBeInTheDocument()
  })

  it('steps through previous calls like a carousel and back to the phone', async () => {
    const stored = (id: string, text: string) => ({
      id,
      started_at: '2026-11-05T13:00:00Z',
      ended_at: '2026-11-05T13:01:00Z',
      end_reason: 'hangup',
      caller_phone: '+4915122000201',
      language: 'de',
      message_count: 3,
      feedback_rating: id === 'older' ? 'down' : null,
      feedback_comment: id === 'older' ? 'Took too long.' : null,
      messages: [
        {
          id: 1,
          role: 'user',
          source: 'voice',
          text,
          interrupted: false,
          created_at: '2026-11-05T13:00:10Z',
          tool_calls: null,
        },
      ],
    })
    const calls = [stored('newer', 'Wann kommt mein X5?'), stored('older', 'Mein Auto lädt nicht.')]
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>((input) => {
        const path = typeof input === 'string' ? input : ''
        if (path.startsWith('/api/conversations?')) {
          return Promise.resolve(Response.json(calls))
        }
        const call = calls.find((c) => path.endsWith(`/${c.id}`))
        return Promise.resolve(Response.json(call ?? status))
      }),
    )
    renderApp()

    await userEvent.click(await screen.findByRole('button', { name: 'Previous call' }))
    expect(await screen.findByText('Wann kommt mein X5?')).toBeInTheDocument()
    expect(screen.getByText(/Previous call 1 of 2/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Previous call' }))
    expect(await screen.findByText('Mein Auto lädt nicht.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous call' })).toBeDisabled()
    // Its feedback, as given before
    expect(screen.getByRole('button', { name: 'Not helpful' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByRole('textbox', { name: 'Feedback comment' })).toHaveValue('Took too long.')

    await userEvent.click(screen.getByRole('button', { name: 'Next call' }))
    expect(await screen.findByText('Wann kommt mein X5?')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Back to phone' }))
    expect(await screen.findByRole('button', { name: 'Start call' })).toBeInTheDocument()
  })

  it("doesn't browse during a call", async () => {
    renderApp()
    await dial()

    expect(screen.getByRole('button', { name: 'Previous call' })).toBeDisabled()
  })

  it('asks for feedback under a finished call and saves it', async () => {
    const fetchMock = vi.fn<typeof fetch>((input) =>
      Promise.resolve(
        typeof input === 'string' && input.includes('/feedback')
          ? Response.json({})
          : Response.json(status),
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderApp()
    const socket = await dial()
    socket.push({ type: 'call_ended', reason: 'hangup' })

    await userEvent.click(await screen.findByRole('button', { name: 'Helpful' }))
    expect(await screen.findByText('Thanks for your feedback.')).toBeInTheDocument()
    await userEvent.type(
      screen.getByRole('textbox', { name: 'Feedback comment' }),
      'Quick and kind',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Send comment' }))

    const feedback = fetchMock.mock.calls.filter(
      ([input]) => typeof input === 'string' && input.includes('/feedback'),
    )
    expect(feedback.map(([input, init]) => [input, init?.method, init?.body])).toEqual([
      ['/api/conversations/c1/feedback', 'PUT', JSON.stringify({ rating: 'up', comment: null })],
      [
        '/api/conversations/c1/feedback',
        'PUT',
        JSON.stringify({ rating: 'up', comment: 'Quick and kind' }),
      ],
    ])
    expect(await screen.findByText('Thanks for your feedback.')).toBeInTheDocument()
  })
})
