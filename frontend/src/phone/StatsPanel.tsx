import { Paper, Stack, Table, Text, Title } from '@mantine/core'

import type { Service } from '../api/callProtocol.ts'
import type { Status } from '../api/conversations.ts'
import { type DialogStats, formatCost, SERVICES, stageTiming, totalCost } from './dialogStats.ts'
import classes from './Phone.module.css'

const SERVICE_LABELS: Record<Service, string> = {
  stt: 'Speech recognition',
  llm: 'Language model',
  tts: 'Speech synthesis',
}

// Stages of a turn, measured from the end of the caller's turn
const STAGES: readonly { stage: string; label: string }[] = [
  { stage: 'stt', label: 'Transcript ready' },
  { stage: 'llm_first_token', label: 'LLM first text' },
  { stage: 'first_audio', label: 'First audio' },
  { stage: 'total', label: 'Whole answer' },
]

function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(2)} s`
}

function tokens(input: number, output: number): string {
  return input === 0 && output === 0 ? '–' : `${String(input)} → ${String(output)}`
}

function Models({ status }: { status: Status | null }) {
  if (status === null) {
    return (
      <Text fz="sm" c="dimmed">
        Loading…
      </Text>
    )
  }
  const { llm, stt, tts } = status
  const rows: [string, string][] = [
    [
      'LLM',
      llm.provider === 'echo'
        ? 'echo (repeats the caller)'
        : `${llm.provider} · ${llm.model ?? ''}${llm.configured ? '' : ' (not configured)'}`,
    ],
    ['STT', stt.fallback_model ? `${stt.model} (fallback ${stt.fallback_model})` : stt.model],
    ['TTS', tts.speed === null ? tts.model : `${tts.model} · speed ${String(tts.speed)}`],
  ]
  return (
    <Table fz="sm" withRowBorders={false} verticalSpacing={2} aria-label="Models">
      <Table.Tbody>
        {rows.map(([label, value]) => (
          <Table.Tr key={label}>
            <Table.Th w={48}>{label}</Table.Th>
            <Table.Td className={classes['model']}>{value}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  )
}

function Usage({ stats }: { stats: DialogStats }) {
  const total = totalCost(stats)
  return (
    <Table fz="sm" verticalSpacing={4} aria-label="Usage of this dialog">
      <Table.Thead>
        <Table.Tr>
          <Table.Th />
          <Table.Th ta="right">Calls</Table.Th>
          <Table.Th ta="right">Tokens in → out</Table.Th>
          <Table.Th ta="right">Audio</Table.Th>
          <Table.Th ta="right">Time</Table.Th>
          <Table.Th ta="right">Cost</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {SERVICES.map((service) => {
          const totals = stats.services[service]
          const audio = totals.audioInS + totals.audioOutS
          return (
            <Table.Tr key={service}>
              <Table.Th>{SERVICE_LABELS[service]}</Table.Th>
              <Table.Td ta="right">{totals.calls}</Table.Td>
              <Table.Td ta="right">{tokens(totals.inputTokens, totals.outputTokens)}</Table.Td>
              <Table.Td ta="right">{audio === 0 ? '–' : `${audio.toFixed(1)} s`}</Table.Td>
              <Table.Td ta="right">
                {totals.durationMs === 0 ? '–' : seconds(totals.durationMs)}
              </Table.Td>
              <Table.Td ta="right">{formatCost(totals.costUsd, totals.unpriced)}</Table.Td>
            </Table.Tr>
          )
        })}
        <Table.Tr>
          <Table.Th>Total</Table.Th>
          <Table.Td colSpan={4} />
          <Table.Td ta="right" fw={600}>
            {formatCost(total.costUsd, total.unpriced)}
          </Table.Td>
        </Table.Tr>
      </Table.Tbody>
    </Table>
  )
}

function Latency({ stats }: { stats: DialogStats }) {
  const rows = STAGES.flatMap(({ stage, label }) => {
    const timing = stageTiming(stats, stage)
    return timing ? [{ label, ...timing }] : []
  })
  if (rows.length === 0) {
    return (
      <Text fz="sm" c="dimmed">
        No answer yet.
      </Text>
    )
  }
  return (
    <Table fz="sm" verticalSpacing={4} aria-label="Latency of this dialog">
      <Table.Thead>
        <Table.Tr>
          <Table.Th />
          <Table.Th ta="right">Mean</Table.Th>
          <Table.Th ta="right">Last</Table.Th>
          <Table.Th ta="right">Turns</Table.Th>
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {rows.map(({ label, meanMs, lastMs, turns }) => (
          <Table.Tr key={label}>
            <Table.Th>{label}</Table.Th>
            <Table.Td ta="right">{seconds(meanMs)}</Table.Td>
            <Table.Td ta="right">{seconds(lastMs)}</Table.Td>
            <Table.Td ta="right">{turns}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  )
}

// The models in use, and what the current (or last) dialog consumed
export function StatsPanel({ status, stats }: { status: Status | null; stats: DialogStats }) {
  return (
    <Paper className={classes['stats']} withBorder radius="lg" p="md">
      <Stack gap="md">
        <Stack gap={4}>
          <Title order={3} fz="sm">
            Models
          </Title>
          <Models status={status} />
        </Stack>
        <Stack gap={4}>
          <Title order={3} fz="sm">
            This dialog
          </Title>
          <Usage stats={stats} />
          <Text fz="xs" c="dimmed">
            Time is the models&apos; own work, summed over all calls. Costs are list prices in USD;
            local models cost nothing.
          </Text>
        </Stack>
        <Stack gap={4}>
          <Title order={3} fz="sm">
            Latency
          </Title>
          <Latency stats={stats} />
          <Text fz="xs" c="dimmed">
            From the end of the caller&apos;s turn.
          </Text>
        </Stack>
      </Stack>
    </Paper>
  )
}
