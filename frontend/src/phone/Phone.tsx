import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
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
import { Feedback } from './Feedback.tsx'
import { describeStoredCall, toTranscript } from './history.ts'
import { isGermanPhone, randomPhone } from './phoneNumber.ts'
import { StatsPanel } from './StatsPanel.tsx'
import { Transcript } from './Transcript.tsx'
import { useCall } from './useCall.ts'
import { useHistory } from './useHistory.ts'

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
  on_hold: 'On hold',
  ended: 'Call ended',
}

function describeCall({ phase, muted, callerSpeaking, microphone }: CallState): string {
  if (!isInCall(phase) || phase === 'on_hold') {
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

const LANGUAGE_NAMES: Record<string, string> = { en: 'English', de: 'German' }

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
  // The number the next call comes from: new for every call, unless the
  // caller typed their own
  const [phone, setPhone] = useState(randomPhone)
  const [phoneTyped, setPhoneTyped] = useState(false)
  const phoneValid = isGermanPhone(phone)

  const inCall = isInCall(phase)
  const now = useNow(inCall)
  // Earlier calls can be looked at while no call runs
  const history = useHistory(call.state.conversationId)
  const browsing = history.index !== null
  const canBrowse = !inCall && phase !== 'connecting'

  function dial() {
    call.start(phone.trim())
    // The next call comes from a new number, unless the caller typed theirs
    if (!phoneTyped) {
      setPhone(randomPhone())
    }
  }

  const numberField = (
    <Group gap={4} wrap="nowrap" justify="center">
      <TextInput
        className={classes['number']}
        size="xs"
        radius="xl"
        label="Calling from"
        aria-label="Your phone number"
        value={phone}
        error={phoneValid ? undefined : 'A German number, e.g. +49 151 12345678'}
        onChange={(event) => {
          setPhone(event.currentTarget.value)
          setPhoneTyped(true)
        }}
      />
      <Tooltip label="New random number">
        <ActionIcon
          variant="subtle"
          color="gray"
          mt={20}
          aria-label="New random number"
          onClick={() => {
            setPhone(randomPhone())
            setPhoneTyped(false)
          }}
        >
          ↻
        </ActionIcon>
      </Tooltip>
    </Group>
  )

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
    <Box className={classes['page']}>
      <Box className={classes['phone']}>
        <Box className={classes['header']}>
          <Group justify="space-between" wrap="nowrap" gap={4}>
            <Tooltip label="Previous call">
              <ActionIcon
                variant="subtle"
                color="gray"
                aria-label="Previous call"
                className={canBrowse ? undefined : classes['hidden']}
                disabled={!canBrowse || !history.hasOlder || history.loading}
                onClick={history.older}
              >
                ‹
              </ActionIcon>
            </Tooltip>
            <Title order={2} fz="lg">
              Carrie · Customer Care
            </Title>
            <Tooltip label={history.index === 0 ? 'Back to phone' : 'Next call'}>
              <ActionIcon
                variant="subtle"
                color="gray"
                aria-label="Next call"
                className={canBrowse ? undefined : classes['hidden']}
                disabled={!canBrowse || !browsing}
                onClick={history.newer}
              >
                ›
              </ActionIcon>
            </Tooltip>
          </Group>
          {browsing ? (
            <>
              <Group gap={6} justify="center">
                <Text fz="xs" c="dimmed">
                  Previous call {(history.index ?? 0) + 1} of {history.calls.length}
                  {history.detail && ` · ${describeStoredCall(history.detail)}`}
                </Text>
                {history.detail?.language && (
                  <Badge size="xs" variant="light" aria-label="Conversation language">
                    {history.detail.language.toUpperCase()}
                  </Badge>
                )}
              </Group>
              {history.detail?.caller_phone && (
                <Text fz={10} c="dimmed">
                  from {history.detail.caller_phone}
                </Text>
              )}
            </>
          ) : (
            <>
              <Group gap={6} justify="center">
                <Text fz="xs" c="dimmed">
                  {showsCall ? `${duration} · ${statusLine}` : describeModel(status)}
                </Text>
                {showsCall && (
                  <Badge size="xs" variant="light" aria-label="Conversation language">
                    {call.state.language.toUpperCase()}
                  </Badge>
                )}
              </Group>
              {showsCall && call.state.callerPhone && (
                <Text fz={10} c="dimmed">
                  from {call.state.callerPhone}
                </Text>
              )}
            </>
          )}
        </Box>

        {browsing ? (
          <>
            <Transcript
              messages={history.detail ? toTranscript(history.detail) : []}
              draft={null}
              waiting={history.loading}
            />
            <Stack gap="sm" className={classes['footer']}>
              {history.notice && (
                <Text fz="sm" c="orange" ta="center" role="status">
                  {history.notice}
                </Text>
              )}
              {history.detail && (
                <Feedback
                  key={history.detail.id}
                  conversationId={history.detail.id}
                  rating={history.detail.feedback_rating}
                  comment={history.detail.feedback_comment}
                />
              )}
              <Button variant="light" radius="xl" onClick={history.close}>
                Back to phone
              </Button>
            </Stack>
          </>
        ) : !showsCall ? (
          <Center flex={1}>
            <Stack align="center" gap="md" px="lg">
              <ActionIcon
                size={84}
                radius="100%"
                color="green"
                variant="filled"
                aria-label="Start call"
                loading={phase === 'connecting'}
                disabled={unreachable || !phoneValid}
                onClick={dial}
              >
                <PhoneIcon size={38} />
              </ActionIcon>
              <Text fz="sm" c="dimmed" ta="center">
                {phase === 'connecting' ? PHASE_LABELS.connecting : 'Tap to call customer care'}
              </Text>
              {numberField}
              {history.notice && (
                <Text fz="xs" c="dimmed" role="status">
                  {history.notice}
                </Text>
              )}
              {status && (
                <Text fz={11} c="dimmed" ta="center">
                  Carrie speaks{' '}
                  {status.languages.map((code) => LANGUAGE_NAMES[code] ?? code).join(' and ')}
                </Text>
              )}
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

        {showsCall && !browsing && (
          <Stack gap="sm" className={classes['footer']}>
            {(notice ?? history.notice) && (
              <Text fz="sm" c="orange" ta="center" role="status">
                {notice ?? history.notice}
              </Text>
            )}
            {phase === 'on_hold' && (
              <Stack gap="sm" align="center">
                <Text fz="sm" ta="center" c="dimmed">
                  You&apos;ve been transferred to a colleague and are on hold.
                </Text>
                <Button
                  color="yellow"
                  radius="xl"
                  size="lg"
                  fullWidth
                  aria-label="On hold, continue talking"
                  onClick={call.resume}
                >
                  On hold · tap to continue
                </Button>
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
              </Stack>
            )}
            {inCall && phase !== 'on_hold' && (
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
              <Stack gap="xs" align="center">
                {call.state.conversationId && (
                  <Feedback
                    key={call.state.conversationId}
                    conversationId={call.state.conversationId}
                  />
                )}
                {numberField}
                <ActionIcon
                  size={64}
                  radius="100%"
                  color="green"
                  variant="filled"
                  aria-label="Call again"
                  disabled={!phoneValid}
                  onClick={dial}
                >
                  <PhoneIcon size={30} />
                </ActionIcon>
              </Stack>
            )}
          </Stack>
        )}
      </Box>
      <StatsPanel status={status} stats={call.state.stats} />
    </Box>
  )
}
