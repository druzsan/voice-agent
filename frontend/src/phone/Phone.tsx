import {
  ActionIcon,
  Alert,
  Box,
  Center,
  Group,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core'
import { useEffect, useState } from 'react'

import { fetchStatus, type InputVia, type Status } from '../api/conversations.ts'
import { playKeyTone } from '../audio/playback.ts'
import { type CallState, isInCall, type Phase } from './callState.ts'
import { HangUpIcon, KeypadIcon, MicIcon, MicOffIcon, PhoneIcon, SendIcon } from './icons.tsx'
import { Keypad } from './Keypad.tsx'
import classes from './Phone.module.css'
import { Transcript } from './Transcript.tsx'
import { useCall } from './useCall.ts'

function clock(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

const PHASE_LABELS: Record<Phase, string> = {
  idle: '',
  connecting: 'Calling…',
  listening: 'Listening…',
  thinking: 'Thinking…',
  speaking: 'Speaking… talk to interrupt',
  ended: 'Call ended',
}

function describeCall({ phase, muted, callerSpeaking, microphone }: CallState): string {
  if (!isInCall(phase)) {
    return PHASE_LABELS[phase]
  }
  if (microphone === 'unavailable') {
    return phase === 'listening'
      ? 'Type a message'
      : PHASE_LABELS[phase].replace(' talk to interrupt', '')
  }
  if (muted) {
    return phase === 'listening'
      ? 'Muted'
      : `${PHASE_LABELS[phase].replace(' talk to interrupt', '')} (muted)`
  }
  return callerSpeaking ? 'Hearing you…' : PHASE_LABELS[phase]
}

function describeModel(status: Status | null): string {
  if (status === null) {
    return 'Connecting…'
  }
  const { provider, model, configured } = status.llm
  if (provider === 'echo') {
    return 'LLM: echo (repeats what you say)'
  }
  return configured ? `LLM: ${provider} · ${model ?? ''}` : `LLM: ${provider}, not configured`
}

// Re-renders every half second while `active`, for the call clock
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) {
      return
    }
    const timer = window.setInterval(() => {
      setNow(Date.now())
    }, 500)
    return () => {
      window.clearInterval(timer)
    }
  }, [active])
  return now
}

function useStatus() {
  const [status, setStatus] = useState<Status | null>(null)
  const [unreachable, setUnreachable] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    fetchStatus(controller.signal).then(setStatus, () => {
      if (!controller.signal.aborted) {
        setUnreachable(true)
      }
    })
    return () => {
      controller.abort()
    }
  }, [])
  return { status, unreachable }
}

export function Phone() {
  const { status, unreachable } = useStatus()
  const call = useCall()
  const { phase, messages, draft, startedAt, endedAt, notice, muted, callerSpeaking, microphone } =
    call.state
  const [composer, setComposer] = useState('')
  // Keypad input is stored as such, unless the caller also typed
  const [composerVia, setComposerVia] = useState<InputVia>('keyboard')
  const [keypadOpen, setKeypadOpen] = useState(false)

  const inCall = isInCall(phase)
  const now = useNow(inCall)

  // Typing works at any time; the backend answers in order
  function send(text = composer, via = composerVia) {
    const trimmed = text.trim()
    if (!inCall || trimmed === '') {
      return
    }
    call.type(trimmed, via)
    setComposer('')
    setComposerVia('keyboard')
  }

  function pressKey(key: string) {
    playKeyTone(key)
    if (key === '#') {
      send()
      return
    }
    setComposer((previous) => previous + key)
    if (composer === '') {
      setComposerVia('keypad')
    }
  }

  const duration =
    startedAt === null ? '' : clock((phase === 'ended' && endedAt ? endedAt : now) - startedAt)
  const statusLine = describeCall(call.state)
  const showsCall = inCall || phase === 'ended'

  return (
    <Center mih="100dvh" p={{ base: 0, xs: 'md' }}>
      <Box className={classes['phone']}>
        <Box className={classes['header']}>
          <Title order={2} fz="lg">
            Voice Agent
          </Title>
          <Text fz="xs" c="dimmed">
            {showsCall ? `${duration} · ${statusLine}` : describeModel(status)}
          </Text>
        </Box>

        {!showsCall ? (
          <Center flex={1}>
            <Stack align="center" gap="md" px="lg">
              <ActionIcon
                size={84}
                radius="100%"
                color="green"
                variant="filled"
                aria-label="Start call"
                loading={phase === 'connecting'}
                disabled={unreachable}
                onClick={call.start}
              >
                <PhoneIcon size={38} />
              </ActionIcon>
              <Text fz="sm" c="dimmed" ta="center">
                {phase === 'connecting' ? PHASE_LABELS.connecting : 'Tap to call'}
              </Text>
              {unreachable && (
                <Alert color="red" variant="light">
                  The backend is not reachable. Is it running?
                </Alert>
              )}
              {status?.database === 'error' && (
                <Alert color="red" variant="light">
                  The database is not reachable, so calls can&apos;t be stored.
                </Alert>
              )}
              {notice && (
                <Alert color="red" variant="light">
                  {notice}
                </Alert>
              )}
            </Stack>
          </Center>
        ) : (
          <Transcript
            messages={messages}
            draft={draft?.text ?? null}
            waiting={phase === 'thinking' && messages.length > 0}
          />
        )}

        {showsCall && (
          <Stack gap="sm" className={classes['footer']}>
            {notice && (
              <Text fz="sm" c="orange" ta="center" role="status">
                {notice}
              </Text>
            )}
            {inCall && (
              <>
                <Group gap="xs" wrap="nowrap">
                  <TextInput
                    flex={1}
                    radius="xl"
                    placeholder="Type a message…"
                    aria-label="Message"
                    value={composer}
                    onChange={(event) => {
                      setComposer(event.currentTarget.value)
                      setComposerVia('keyboard')
                    }}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        send()
                      }
                    }}
                  />
                  <ActionIcon
                    size="lg"
                    radius="xl"
                    aria-label="Send message"
                    disabled={composer.trim() === ''}
                    onClick={() => {
                      send()
                    }}
                  >
                    <SendIcon size={18} />
                  </ActionIcon>
                </Group>
                {keypadOpen && <Keypad onKey={pressKey} />}
                <Group justify="space-evenly" mt="xs">
                  <Tooltip label={keypadOpen ? 'Hide keypad' : 'Show keypad'}>
                    <ActionIcon
                      size={56}
                      radius="100%"
                      variant={keypadOpen ? 'filled' : 'light'}
                      color="gray"
                      aria-label={keypadOpen ? 'Hide keypad' : 'Show keypad'}
                      aria-pressed={keypadOpen}
                      onClick={() => {
                        setKeypadOpen((open) => !open)
                      }}
                    >
                      <KeypadIcon />
                    </ActionIcon>
                  </Tooltip>
                  <Tooltip label={muted ? 'Unmute' : 'Mute'}>
                    <ActionIcon
                      size={64}
                      radius="100%"
                      variant="filled"
                      color={muted || microphone === 'unavailable' ? 'gray' : 'blue'}
                      className={callerSpeaking && !muted ? classes['hearing'] : undefined}
                      aria-label={muted ? 'Unmute' : 'Mute'}
                      aria-pressed={muted}
                      disabled={microphone !== 'on'}
                      onClick={call.toggleMute}
                    >
                      {muted || microphone === 'unavailable' ? (
                        <MicOffIcon size={28} />
                      ) : (
                        <MicIcon size={28} />
                      )}
                    </ActionIcon>
                  </Tooltip>
                  <ActionIcon
                    size={56}
                    radius="100%"
                    variant="filled"
                    color="red"
                    aria-label="Hang up"
                    onClick={call.hangUp}
                  >
                    <HangUpIcon />
                  </ActionIcon>
                </Group>
              </>
            )}
            {phase === 'ended' && (
              <Group justify="center">
                <ActionIcon
                  size={64}
                  radius="100%"
                  color="green"
                  variant="filled"
                  aria-label="Call again"
                  onClick={call.start}
                >
                  <PhoneIcon size={30} />
                </ActionIcon>
              </Group>
            )}
          </Stack>
        )}
      </Box>
    </Center>
  )
}
