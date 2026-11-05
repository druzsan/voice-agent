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
import { isInCall, type Phase } from './callState.ts'
import { HangUpIcon, KeypadIcon, MicIcon, PhoneIcon, SendIcon, StopIcon } from './icons.tsx'
import { Keypad } from './Keypad.tsx'
import classes from './Phone.module.css'
import { Transcript } from './Transcript.tsx'
import { useCall } from './useCall.ts'

const DEFAULT_MAX_RECORDING_S = 30

function clock(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000))
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

const PHASE_LABELS: Record<Phase, string> = {
  idle: '',
  starting: 'Calling…',
  ready: 'Tap the mic to talk',
  recording: 'Listening… tap again to send',
  waiting: 'Thinking…',
  playing: 'Speaking…',
  ended: 'Call ended',
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
  const call = useCall(status?.stt.max_recording_s ?? DEFAULT_MAX_RECORDING_S)
  const { phase, messages, startedAt, endedAt, notice } = call.state
  const [draft, setDraft] = useState('')
  // Keypad input is stored as such, unless the caller also typed
  const [draftVia, setDraftVia] = useState<InputVia>('keyboard')
  const [keypadOpen, setKeypadOpen] = useState(false)

  const inCall = isInCall(phase)
  const ready = phase === 'ready'
  const now = useNow(inCall)
  const [recordingSince, setRecordingSince] = useState(0)

  function send(text = draft, via = draftVia) {
    const trimmed = text.trim()
    if (!ready || trimmed === '') {
      return
    }
    call.type(trimmed, via)
    setDraft('')
    setDraftVia('keyboard')
  }

  function pressKey(key: string) {
    playKeyTone(key)
    if (key === '#') {
      send()
      return
    }
    setDraft((previous) => previous + key)
    if (draft === '') {
      setDraftVia('keypad')
    }
  }

  function toggleTalking() {
    if (phase === 'recording') {
      call.stopTalking()
    } else {
      setRecordingSince(Date.now())
      call.talk()
    }
  }

  const duration =
    startedAt === null ? '' : clock((phase === 'ended' && endedAt ? endedAt : now) - startedAt)
  const statusLine =
    phase === 'recording'
      ? `${PHASE_LABELS.recording} (${clock(now - recordingSince)})`
      : PHASE_LABELS[phase]

  return (
    <Center mih="100dvh" p={{ base: 0, xs: 'md' }}>
      <Box className={classes['phone']}>
        <Box className={classes['header']}>
          <Title order={2} fz="lg">
            Voice Agent
          </Title>
          <Text fz="xs" c="dimmed">
            {inCall || phase === 'ended' ? `${duration} · ${statusLine}` : describeModel(status)}
          </Text>
        </Box>

        {phase === 'idle' || phase === 'starting' ? (
          <Center flex={1}>
            <Stack align="center" gap="md" px="lg">
              <ActionIcon
                size={84}
                radius="100%"
                color="green"
                variant="filled"
                aria-label="Start call"
                loading={phase === 'starting'}
                disabled={unreachable}
                onClick={call.start}
              >
                <PhoneIcon size={38} />
              </ActionIcon>
              <Text fz="sm" c="dimmed" ta="center">
                {phase === 'starting' ? PHASE_LABELS.starting : 'Tap to call'}
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
          <Transcript messages={messages} waiting={phase === 'waiting'} />
        )}

        {(inCall || phase === 'ended') && (
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
                    placeholder={ready ? 'Type a message…' : 'Wait for the answer…'}
                    aria-label="Message"
                    value={draft}
                    disabled={!ready}
                    onChange={(event) => {
                      setDraft(event.currentTarget.value)
                      setDraftVia('keyboard')
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
                    disabled={!ready || draft.trim() === ''}
                    onClick={() => {
                      send()
                    }}
                  >
                    <SendIcon size={18} />
                  </ActionIcon>
                </Group>
                {keypadOpen && <Keypad onKey={pressKey} disabled={!ready} />}
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
                  <ActionIcon
                    size={64}
                    radius="100%"
                    variant="filled"
                    color={phase === 'recording' ? 'red' : 'blue'}
                    className={phase === 'recording' ? classes['recording'] : undefined}
                    aria-label={phase === 'recording' ? 'Stop and send' : 'Talk'}
                    disabled={!ready && phase !== 'recording'}
                    onClick={toggleTalking}
                  >
                    {phase === 'recording' ? <StopIcon size={28} /> : <MicIcon size={28} />}
                  </ActionIcon>
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
