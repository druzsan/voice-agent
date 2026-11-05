import { Box, Group, Loader, ScrollArea, Stack, Text } from '@mantine/core'
import { useEffect, useRef } from 'react'

import type { Source } from '../api/conversations.ts'
import type { MessageEntry, ToolEntry, TranscriptEntry } from './callState.ts'
import { KeyboardIcon, KeypadIcon, MicIcon } from './icons.tsx'
import classes from './Phone.module.css'

const SOURCE_LABELS: Record<Source, string> = {
  voice: 'spoken',
  keyboard: 'typed',
  keypad: 'keypad',
  llm: 'Carrie',
  template: 'fixed text',
}

function SourceIcon({ source }: { source: Source }) {
  switch (source) {
    case 'voice':
      return <MicIcon size={12} />
    case 'keyboard':
      return <KeyboardIcon size={12} />
    case 'keypad':
      return <KeypadIcon size={12} />
    default:
      return null
  }
}

function Message({ message }: { message: MessageEntry }) {
  return (
    <Box className={classes['bubble']} data-role={message.role} data-source={message.source}>
      <Text fz="sm">{message.text}</Text>
      <Group gap={4} mt={2} className={classes['meta']}>
        <SourceIcon source={message.source} />
        <Text fz={10}>
          {SOURCE_LABELS[message.source]}
          {message.interrupted && ' · interrupted'}
        </Text>
      </Group>
    </Box>
  )
}

// A tool Carrie used, as a small line between the messages
function Tool({ tool }: { tool: ToolEntry }) {
  return (
    <Text
      fz={11}
      className={classes['tool']}
      data-status={tool.status}
      title={tool.name}
      role="note"
    >
      {tool.status === 'ok' ? '✓' : '✕'} {tool.label}
    </Text>
  )
}

interface TranscriptProps {
  messages: readonly TranscriptEntry[]
  // The reply as the model writes it
  draft: string | null
  waiting: boolean
}

export function Transcript({ messages, draft, waiting }: TranscriptProps) {
  const viewport = useRef<HTMLDivElement>(null)

  // Keep the newest message in view
  useEffect(() => {
    viewport.current?.scrollTo({ top: viewport.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, draft, waiting])

  return (
    <ScrollArea className={classes['transcript']} viewportRef={viewport} type="auto">
      <Stack gap="xs" p="sm" role="log" aria-label="Transcript">
        {messages.map((entry) =>
          entry.kind === 'tool' ? (
            <Tool key={entry.id} tool={entry} />
          ) : (
            <Message key={entry.id} message={entry} />
          ),
        )}
        {draft !== null && (
          <Box className={classes['bubble']} data-role="assistant" aria-label="Answer so far">
            <Text fz="sm">{draft.trim()}</Text>
          </Box>
        )}
        {waiting && draft === null && (
          <Box className={classes['bubble']} data-role="assistant" aria-label="Answering">
            <Loader type="dots" size="sm" />
          </Box>
        )}
      </Stack>
    </ScrollArea>
  )
}
