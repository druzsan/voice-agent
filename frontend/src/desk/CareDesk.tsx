import {
  Alert,
  Badge,
  Box,
  Card,
  Drawer,
  Group,
  ScrollArea,
  SegmentedControl,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
} from '@mantine/core'
import { useEffect, useState } from 'react'

import {
  fetchHandovers,
  fetchTickets,
  type Handover,
  type Priority,
  type Ticket,
  type TicketStatus,
  type Topic,
} from '../api/desk.ts'
import classes from './CareDesk.module.css'

// How often the desk refreshes while it's open
const REFRESH_MS = 4000

const TOPICS: Record<Topic, string> = {
  delivery: 'Delivery',
  charging: 'Charging',
  connected_services: 'App & services',
  warranty: 'Warranty & service',
}

const STATUS_COLORS: Record<TicketStatus, string> = {
  open: 'blue',
  in_progress: 'cyan',
  waiting_on_customer: 'grape',
  resolved: 'green',
  closed: 'gray',
}

const PRIORITY_COLORS: Record<Priority, string> = {
  normal: 'gray',
  high: 'orange',
  urgent: 'red',
  safety: 'red',
}

const AUTHORS: Record<string, string> = {
  carrie: 'Carrie',
  care_agent: 'Care team',
  system: 'System',
}

function words(value: string): string {
  return value.replaceAll('_', ' ')
}

function when(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// Polls the desk's data while the page shows it
function useDesk() {
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [handovers, setHandovers] = useState<Handover[]>([])
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    async function load() {
      try {
        const [t, h] = await Promise.all([
          fetchTickets(controller.signal),
          fetchHandovers(controller.signal),
        ])
        setTickets(t)
        setHandovers(h)
        setError(null)
      } catch (caught) {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : 'The desk is not reachable.')
        }
      }
    }
    void load()
    const timer = window.setInterval(() => void load(), REFRESH_MS)
    return () => {
      controller.abort()
      window.clearInterval(timer)
    }
  }, [])
  return { tickets, handovers, error }
}

function Details({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details).filter(
    ([, value]) => value !== null && value !== '' && !(Array.isArray(value) && value.length === 0),
  )
  if (entries.length === 0) {
    return null
  }
  return (
    <Table fz="xs" withRowBorders={false} verticalSpacing={2}>
      <Table.Tbody>
        {entries.map(([key, value]) => (
          <Table.Tr key={key}>
            <Table.Td c="dimmed" w="40%">
              {words(key)}
            </Table.Td>
            <Table.Td>{Array.isArray(value) ? value.join(', ') : String(value)}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  )
}

function TicketDrawer({ ticket, onClose }: { ticket: Ticket | null; onClose: () => void }) {
  return (
    <Drawer
      opened={ticket !== null}
      onClose={onClose}
      position="right"
      size="md"
      title={ticket ? `${ticket.reference} · ${TOPICS[ticket.topic]}` : ''}
    >
      {ticket && (
        <Stack gap="sm">
          <Group gap="xs">
            <Badge color={STATUS_COLORS[ticket.status]}>{words(ticket.status)}</Badge>
            <Badge color={PRIORITY_COLORS[ticket.priority]} variant="light">
              {ticket.priority}
            </Badge>
            <Badge variant="outline">{ticket.language.toUpperCase()}</Badge>
          </Group>
          <Text fw={500}>{ticket.summary}</Text>
          <Text fz="sm" c="dimmed">
            {ticket.customer_name ?? 'Unknown customer'}
            {ticket.postal_code && ` · ${ticket.postal_code}`}
            {ticket.vehicle_model && ` · ${ticket.vehicle_model}`}
            {ticket.order_number && ` · order ${ticket.order_number}`}
            {ticket.mobile_phone && ` · ${ticket.mobile_phone}`}
          </Text>
          <Text fz="xs" c="dimmed">
            {words(ticket.issue_type)} · {words(ticket.verification_status)} · opened{' '}
            {when(ticket.created_at)}
          </Text>
          <Details details={ticket.details} />
          <Title order={5}>Notes</Title>
          {ticket.notes.length === 0 && (
            <Text fz="sm" c="dimmed">
              No notes yet.
            </Text>
          )}
          {ticket.notes.map((note, index) => (
            <Card key={index} withBorder padding="xs" data-author={note.author}>
              <Text fz="xs" c="dimmed">
                {AUTHORS[note.author] ?? note.author} · {when(note.created_at)}
              </Text>
              <Text fz="sm">{note.body}</Text>
            </Card>
          ))}
        </Stack>
      )}
    </Drawer>
  )
}

type Filter = 'open' | 'all'

function Tickets({ tickets }: { tickets: Ticket[] }) {
  const [filter, setFilter] = useState<Filter>('open')
  const [selected, setSelected] = useState<number | null>(null)
  const shown = tickets.filter(
    (ticket) => filter === 'all' || !['resolved', 'closed'].includes(ticket.status),
  )
  const current = tickets.find((ticket) => ticket.number === selected) ?? null
  return (
    <Stack gap="sm">
      <SegmentedControl
        w={220}
        size="xs"
        value={filter}
        onChange={(value) => {
          setFilter(value)
        }}
        data={[
          { label: 'Open', value: 'open' },
          { label: 'All', value: 'all' },
        ]}
      />
      <ScrollArea>
        <Table highlightOnHover striped fz="sm" miw={720}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Ticket</Table.Th>
              <Table.Th>Topic</Table.Th>
              <Table.Th>Customer</Table.Th>
              <Table.Th>ZIP code</Table.Th>
              <Table.Th>Summary</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Updated</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {shown.map((ticket) => (
              <Table.Tr
                key={ticket.number}
                className={classes['row']}
                onClick={() => {
                  setSelected(ticket.number)
                }}
              >
                <Table.Td>
                  <Text fz="sm" fw={500}>
                    {ticket.reference}
                  </Text>
                  {ticket.priority !== 'normal' && (
                    <Badge size="xs" color={PRIORITY_COLORS[ticket.priority]} variant="light">
                      {ticket.priority}
                    </Badge>
                  )}
                </Table.Td>
                <Table.Td>{TOPICS[ticket.topic]}</Table.Td>
                <Table.Td>{ticket.customer_name ?? '–'}</Table.Td>
                <Table.Td>{ticket.postal_code ?? '–'}</Table.Td>
                <Table.Td className={classes['summary']}>{ticket.summary}</Table.Td>
                <Table.Td>
                  <Badge size="sm" color={STATUS_COLORS[ticket.status]} variant="light">
                    {words(ticket.status)}
                  </Badge>
                </Table.Td>
                <Table.Td>{when(ticket.updated_at)}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
      <TicketDrawer
        ticket={current}
        onClose={() => {
          setSelected(null)
        }}
      />
    </Stack>
  )
}

function Handovers({ handovers }: { handovers: Handover[] }) {
  if (handovers.length === 0) {
    return (
      <Text c="dimmed" fz="sm">
        No transfers yet. Ask Carrie for a colleague in a call.
      </Text>
    )
  }
  return (
    <Stack gap="sm">
      {handovers.map((handover) => (
        <Card key={handover.id} withBorder padding="sm">
          <Group justify="space-between" mb={4}>
            <Group gap="xs">
              <Text fw={500}>{words(handover.route)}</Text>
              <Badge
                size="sm"
                color={handover.status === 'transferred' ? 'yellow' : 'gray'}
                variant="light"
              >
                {handover.status === 'transferred' ? 'waiting on hold' : 'no colleague available'}
              </Badge>
              <Badge size="sm" color={PRIORITY_COLORS[handover.priority]} variant="light">
                {handover.priority}
              </Badge>
              <Badge size="sm" variant="outline">
                {handover.language.toUpperCase()}
              </Badge>
            </Group>
            <Text fz="xs" c="dimmed">
              {when(handover.created_at)}
            </Text>
          </Group>
          <Text fz="xs" c="dimmed" mb={4}>
            {handover.reason}
          </Text>
          <Text fz="sm" mb={4}>
            {handover.summary}
          </Text>
          <Details details={handover.details} />
        </Card>
      ))}
    </Stack>
  )
}

export function CareDesk() {
  const { tickets, handovers, error } = useDesk()
  return (
    <Box className={classes['desk']}>
      <Title order={2} fz="lg" mb="sm">
        Care desk
      </Title>
      {error && (
        <Alert color="red" variant="light" mb="sm">
          {error}
        </Alert>
      )}
      <Tabs defaultValue="handovers">
        <Tabs.List mb="sm">
          <Tabs.Tab value="handovers">Transfers ({handovers.length})</Tabs.Tab>
          <Tabs.Tab value="tickets">Tickets ({tickets.length})</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="handovers">
          <Handovers handovers={handovers} />
        </Tabs.Panel>
        <Tabs.Panel value="tickets">
          <Tickets tickets={tickets} />
        </Tabs.Panel>
      </Tabs>
    </Box>
  )
}
