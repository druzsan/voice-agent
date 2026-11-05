import { ActionIcon, Button, Group, Stack, Text, Textarea, Tooltip } from '@mantine/core'
import { useState } from 'react'

import { type FeedbackRating, sendFeedback } from '../api/conversations.ts'

interface FeedbackProps {
  conversationId: string
  // Feedback given earlier, e.g. on a previous call
  rating?: FeedbackRating | null
  comment?: string | null
}

type Saving = 'idle' | 'saving' | 'saved' | 'failed'

// Thumbs up or down under a call; a rating is saved at once, a comment
// can follow
export function Feedback({ conversationId, rating = null, comment = null }: FeedbackProps) {
  const [current, setCurrent] = useState<FeedbackRating | null>(rating)
  const [text, setText] = useState(comment ?? '')
  const [savedText, setSavedText] = useState(comment ?? '')
  const [saving, setSaving] = useState<Saving>(rating ? 'saved' : 'idle')

  async function save(next: FeedbackRating, withText: string) {
    setCurrent(next)
    setSaving('saving')
    try {
      await sendFeedback(conversationId, next, withText)
      setSavedText(withText)
      setSaving('saved')
    } catch {
      setSaving('failed')
    }
  }

  return (
    <Stack gap={6} align="center" aria-label="Feedback on this call" role="group">
      <Group gap="xs" justify="center">
        <Text fz="sm" c="dimmed">
          How did Carrie do?
        </Text>
        {(['up', 'down'] as const).map((choice) => (
          <Tooltip key={choice} label={choice === 'up' ? 'Helpful' : 'Not helpful'}>
            <ActionIcon
              size="lg"
              radius="xl"
              variant={current === choice ? 'filled' : 'light'}
              color={choice === 'up' ? 'green' : 'red'}
              aria-label={choice === 'up' ? 'Helpful' : 'Not helpful'}
              aria-pressed={current === choice}
              disabled={saving === 'saving'}
              onClick={() => void save(choice, text)}
            >
              {choice === 'up' ? '👍' : '👎'}
            </ActionIcon>
          </Tooltip>
        ))}
      </Group>
      {current !== null && (
        <>
          <Textarea
            w="100%"
            size="xs"
            rows={2}
            maxLength={2000}
            placeholder="Anything to add? (optional)"
            aria-label="Feedback comment"
            value={text}
            onChange={(event) => {
              setText(event.currentTarget.value)
            }}
          />
          {text.trim() !== savedText.trim() && (
            <Button
              size="xs"
              variant="light"
              loading={saving === 'saving'}
              onClick={() => void save(current, text)}
            >
              Send comment
            </Button>
          )}
        </>
      )}
      {saving === 'saved' && text.trim() === savedText.trim() && (
        <Text fz="xs" c="dimmed" role="status">
          Thanks for your feedback.
        </Text>
      )}
      {saving === 'failed' && (
        <Text fz="xs" c="red" role="status">
          Couldn&apos;t save the feedback. Please try again.
        </Text>
      )}
    </Stack>
  )
}
