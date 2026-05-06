import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
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
    const user = userEvent.setup()
    render(<ExportHub diagramId="diag-1" />)

    openExportHub()

    const iacCheckbox = await screen.findByLabelText('Include Infrastructure Code')
    expect(iacCheckbox).toBeChecked()

    iacCheckbox.focus()
    await user.keyboard('{Enter}')

    expect(iacCheckbox).not.toBeChecked()
    expect(screen.getByRole('status')).toHaveTextContent('6 of 7 deliverables selected')
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
      'Compliance Report',
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