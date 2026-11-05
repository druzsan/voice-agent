import { Box, Group, Loader, ScrollArea, Stack, Text } from '@mantine/core'
import { useEffect, useRef } from 'react'

import type { Message, Source } from '../api/conversations.ts'
import { KeyboardIcon, KeypadIcon, MicIcon } from './icons.tsx'
import classes from './Phone.module.css'

const SOURCE_LABELS: Record<Source, string> = {
  voice: 'spoken',
  keyboard: 'typed',
  keypad: 'keypad',
  llm: 'model',
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

interface TranscriptProps {
  messages: readonly Message[]
  waiting: boolean
}

export function Transcript({ messages, waiting }: TranscriptProps) {
  const viewport = useRef<HTMLDivElement>(null)

  // Keep the newest message in view
  useEffect(() => {
    viewport.current?.scrollTo({ top: viewport.current.scrollHeight, behavior: 'smooth' })
  }, [messages.length, waiting])

  return (
    <ScrollArea className={classes['transcript']} viewportRef={viewport} type="auto">
      <Stack gap="xs" p="sm" role="log" aria-label="Transcript">
        {messages.map((message) => (
          <Box
            key={message.id}
            className={classes['bubble']}
            data-role={message.role}
            data-source={message.source}
          >
            <Text fz="sm">{message.text}</Text>
            <Group gap={4} mt={2} className={classes['meta']}>
              <SourceIcon source={message.source} />
              <Text fz={10}>{SOURCE_LABELS[message.source]}</Text>
            </Group>
          </Box>
        ))}
        {waiting && (
          <Box className={classes['bubble']} data-role="assistant" aria-label="Answering">
            <Loader type="dots" size="sm" />
          </Box>
        )}
      </Stack>
    </ScrollArea>
  )
}
