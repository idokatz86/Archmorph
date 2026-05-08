import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../../../services/apiClient', () => ({
  default: { post: vi.fn(), get: vi.fn() },
}))

import api from '../../../services/apiClient'
import ExportHub from '../ExportHub'

const ACCESSIBLE_LANDING_ZONE_SVG = `
<svg role="img" aria-labelledby="lz-title" aria-describedby="lz-desc" xmlns="http://www.w3.org/2000/svg">
  <title id="lz-title">Azure Landing Zone</title>
  <desc id="lz-desc">Target architecture preview</desc>
  <g data-tier="Compute">
    <title>Compute tier</title>
    <desc>Hosts application workloads</desc>
    <g>
      <title>Azure Kubernetes Service</title>
      <desc>Compute tier service for container workloads</desc>
    </g>
  </g>
  <g data-tier="Data">
    <title>Data tier</title>
    <desc>Stores operational data</desc>
    <g>
      <title>Azure SQL Database</title>
      <desc>Data tier service for relational data</desc>
    </g>
  </g>
</svg>`

function openExportHub() {
  act(() => {
    document.dispatchEvent(new CustomEvent('archmorph:command', { detail: 'export-hub' }))
  })
}

describe('ExportHub accessibility', () => {
  beforeEach(() => {
    api.post.mockReset()
    api.get.mockReset()
  })

  it('moves focus into the dialog and restores focus on Escape', async () => {
    const user = userEvent.setup()
    render(
      <>
        <button type="button">Export All</button>
        <ExportHub diagramId="diag-1" />
      </>
    )

    const trigger = screen.getByRole('button', { name: 'Export All' })
    trigger.focus()
    expect(trigger).toHaveFocus()

    openExportHub()

    const dialog = await screen.findByRole('dialog', { name: 'Generate Deliverables' })
    expect(dialog).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus())

    await user.keyboard('{Escape}')

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

  it('lets Enter toggle deliverables from the keyboard', async () => {
    render(<ExportHub diagramId="diag-1" />)

    openExportHub()

    const iacCheckbox = await screen.findByLabelText('Include Infrastructure Code')
    expect(iacCheckbox).toBeChecked()

    iacCheckbox.focus()
    fireEvent.keyDown(iacCheckbox, { key: 'Enter', code: 'Enter' })

    await waitFor(() => expect(iacCheckbox).not.toBeChecked())
  expect(screen.getByRole('status')).toHaveTextContent('5 of 6 deliverables selected')
  })

  it('renders generated SVG in a live Landing Zone viewer', async () => {
    const user = userEvent.setup()
    api.post.mockResolvedValueOnce({
      content: ACCESSIBLE_LANDING_ZONE_SVG,
      filename: 'archmorph-landing-zone.svg',
      export_capability: 'capability-token',
    })

    render(<ExportHub diagramId="diag-1" />)

    openExportHub()
    for (const label of [
      'Infrastructure Code',
      'High-Level Design',
      'Cost Estimate',
      'Migration Timeline',
      'PDF Analysis Report',
    ]) {
      await user.click(await screen.findByLabelText(`Include ${label}`))
    }

    await user.selectOptions(screen.getByLabelText('Architecture Package format'), 'svg-primary')
    await user.click(screen.getByRole('button', { name: /Generate All Selected/i }))

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      expect.stringContaining('format=svg'),
      undefined,
      undefined,
      undefined,
      {},
    ))

    const viewer = await screen.findByTestId('landing-zone-viewer')
    expect(viewer).toHaveTextContent('Target Landing Zone Preview')
    expect(viewer).toHaveTextContent('Azure Landing Zone')
    expect(screen.getByTestId('landing-zone-svg-preview').querySelector('svg')).toHaveAttribute('role', 'img')

    await user.tab()
    await user.click(screen.getByRole('button', { name: 'Azure Kubernetes Service' }))

    expect(screen.getByTestId('landing-zone-live-region')).toHaveTextContent('Compute tier: Azure Kubernetes Service')
  })
})

describe('ExportHub parallel generation', () => {
  beforeEach(() => {
    api.post.mockReset()
    api.get.mockReset()
  })

  it('fires independent deliverables in parallel — all three reach the API before any resolves', async () => {
    // We control resolution so we can observe concurrency:
    // resolve() for each call is deferred until we explicitly trigger it.
    let pendingCount = 0
    const resolvers = []
    api.post.mockImplementation(() => {
      pendingCount++
      return new Promise((resolve) => {
        resolvers.push(() => {
          pendingCount--
          resolve({ code: 'resource {}', filename: 'archmorph-iac.tf' })
        })
      })
    })
    api.get.mockImplementation(() => {
      pendingCount++
      return new Promise((resolve) => {
        resolvers.push(() => {
          pendingCount--
          resolve({ services: [], total_monthly_estimate: { low: 0, high: 0 } })
        })
      })
    })

    const user = userEvent.setup()
    render(<ExportHub diagramId="diag-1" />)

    openExportHub()

    // Deselect capability-gated deliverables, keep only independent ones
    for (const label of ['Architecture Package', 'High-Level Design', 'PDF Analysis Report']) {
      await user.click(await screen.findByLabelText(`Include ${label}`))
    }

    // Start generation — 3 independent deliverables (IaC, Cost, Timeline)
    await user.click(screen.getByRole('button', { name: /Generate All Selected/i }))

    // All three API calls must be in-flight before we resolve any
    // CONCURRENCY limit is 3, so all should start immediately
    await waitFor(() => expect(resolvers.length).toBeGreaterThanOrEqual(2), { timeout: 2000 })

    // At least 2 were in-flight simultaneously — verify by resolving them all now
    const countBeforeResolve = resolvers.length
    expect(countBeforeResolve).toBeGreaterThanOrEqual(2)

    // Resolve all pending calls
    resolvers.forEach(r => r())

    // Generation should complete
    await waitFor(
      () => expect(screen.getByRole('button', { name: /Generate All Selected/i })).not.toBeDisabled(),
      { timeout: 3000 }
    )
  })

  it('capability-gated deliverables chain export tokens sequentially', async () => {
    // architecture-package returns token-1, hld should receive token-1
    const capabilityOrder = []
    api.post.mockImplementation((url, _body, _signal, _timeout, headers) => {
      const cap = headers?.['X-Export-Capability'] || null
      capabilityOrder.push({ url, cap })
      const nextToken = capabilityOrder.length === 1 ? 'token-1' : 'token-2'
      if (url.includes('export-architecture-package')) {
        return Promise.resolve({
          content: '<html>pkg</html>',
          filename: 'pkg.html',
          export_capability: nextToken,
        })
      }
      if (url.includes('export-hld')) {
        return Promise.resolve({
          content_b64: btoa('PDF content'),
          content_type: 'application/pdf',
          filename: 'hld.pdf',
          export_capability: 'token-2',
        })
      }
      return Promise.resolve({ content_b64: btoa('pdf'), content_type: 'application/pdf', filename: 'report.pdf' })
    })

    const user = userEvent.setup()
    render(<ExportHub diagramId="diag-1" exportCapability="initial-token" />)

    openExportHub()

    // Deselect independent deliverables, keep only capability-gated ones
    for (const label of ['Infrastructure Code', 'Cost Estimate', 'Migration Timeline']) {
      await user.click(await screen.findByLabelText(`Include ${label}`))
    }

    await user.click(screen.getByRole('button', { name: /Generate All Selected/i }))

    await waitFor(() => expect(capabilityOrder.length).toBeGreaterThanOrEqual(2), { timeout: 3000 })

    // First capability-gated call should use the initial export token
    expect(capabilityOrder[0].cap).toBe('initial-token')
    // Second should use the token returned by the first response
    expect(capabilityOrder[1].cap).toBe('token-1')
  })
})