import { Badge, Button, Container, Group, Stack, Title } from '@mantine/core'
import { useEffect, useState } from 'react'

import { fetchHealth } from './api/health.ts'

type BackendStatus =
  { kind: 'checking' } | { kind: 'connected'; version: string } | { kind: 'unreachable' }

export default function App() {
  const [status, setStatus] = useState<BackendStatus>({ kind: 'checking' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(controller.signal).then(
      (health) => {
        setStatus({ kind: 'connected', version: health.version })
      },
      () => {
        if (!controller.signal.aborted) {
          setStatus({ kind: 'unreachable' })
        }
      },
    )
    return () => {
      controller.abort()
    }
  }, [attempt])

  const retry = () => {
    setStatus({ kind: 'checking' })
    setAttempt((previous) => previous + 1)
  }

  return (
    <Container size="sm" py="xl">
      <Stack>
        <Title order={1}>Voice Agent</Title>
        <Group>
          {status.kind === 'checking' && <Badge color="gray">Checking…</Badge>}
          {status.kind === 'connected' && (
            <Badge color="green">Backend connected (v{status.version})</Badge>
          )}
          {status.kind === 'unreachable' && (
            <>
              <Badge color="red">Backend unreachable</Badge>
              <Button size="xs" variant="light" onClick={retry}>
                Retry
              </Button>
            </>
          )}
        </Group>
      </Stack>
    </Container>
  )
}
