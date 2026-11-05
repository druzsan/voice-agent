import { MantineProvider } from '@mantine/core'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Handover, Ticket } from '../api/desk.ts'
import { theme } from '../theme.ts'
import { CareDesk } from './CareDesk.tsx'

const ticket: Ticket = {
  number: 10006,
  reference: 'CC-10006',
  topic: 'charging',
  issue_type: 'charging_interrupted',
  status: 'open',
  priority: 'normal',
  summary: 'Home wallbox charging stops after a few minutes.',
  details: { charging_location: 'home' },
  customer_name: 'Markus Hoffmann',
  postal_code: '60311',
  vehicle_model: 'BMW iX xDrive45',
  order_number: '318842',
  mobile_phone: '+4915122000201',
  verification_status: 'order_verified',
  language: 'de',
  conversation_id: null,
  created_at: '2026-10-30T09:00:00Z',
  updated_at: '2026-11-05T14:00:00Z',
  notes: [
    { author: 'carrie', body: 'Stopped twice yesterday.', created_at: '2026-11-05T14:00:00Z' },
  ],
}

const handover: Handover = {
  id: 1,
  conversation_id: 'c1',
  ticket_number: null,
  route: 'technical_support',
  priority: 'normal',
  language: 'de',
  reason: 'Caller asked for a person',
  summary: 'Language: German. App-Anmeldung schlägt fehl.',
  details: { caller_phone: '+4915122000302', tickets: [] },
  status: 'transferred',
  created_at: '2026-11-05T14:05:00Z',
}

function renderDesk() {
  render(
    <MantineProvider theme={theme}>
      <CareDesk />
    </MantineProvider>,
  )
}

describe('CareDesk', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      // The desk only fetches by path
      vi.fn<typeof fetch>((input) =>
        Promise.resolve(
          Response.json(
            typeof input === 'string' && input.endsWith('/handovers') ? [handover] : [ticket],
          ),
        ),
      ),
    )
  })

  it('shows transfers with their summary and language', async () => {
    renderDesk()

    expect(await screen.findByText(/App-Anmeldung schlägt fehl/)).toBeInTheDocument()
    expect(screen.getByText('waiting on hold')).toBeInTheDocument()
    expect(screen.getByText('+4915122000302')).toBeInTheDocument()
  })

  it('lists tickets with the customer and their ZIP code', async () => {
    renderDesk()
    await userEvent.click(await screen.findByRole('tab', { name: /Tickets/ }))

    expect(await screen.findByRole('columnheader', { name: 'ZIP code' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '60311' })).toBeInTheDocument()
  })

  it('opens a ticket with its notes', async () => {
    renderDesk()
    await userEvent.click(await screen.findByRole('tab', { name: /Tickets/ }))
    await userEvent.click(await screen.findByText('CC-10006'))

    expect(await screen.findByText('Stopped twice yesterday.')).toBeInTheDocument()
    expect(screen.getByText(/Markus Hoffmann · 60311 · BMW iX xDrive45/)).toBeInTheDocument()
  })
})
