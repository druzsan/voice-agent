import { MantineProvider } from '@mantine/core'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import App from './App.tsx'
import { theme } from './theme.ts'

function renderApp() {
  render(
    <MantineProvider theme={theme}>
      <App />
    </MantineProvider>,
  )
}

describe('App', () => {
  it('shows the backend as connected when the health check succeeds', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockResolvedValue(Response.json({ status: 'ok', version: '0.1.0' })),
    )

    renderApp()

    expect(await screen.findByText('Backend connected (v0.1.0)')).toBeInTheDocument()
  })

  it('shows the backend as unreachable when the health check fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<typeof fetch>().mockRejectedValue(new TypeError('Failed to fetch')),
    )

    renderApp()

    expect(await screen.findByText('Backend unreachable')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })
})
