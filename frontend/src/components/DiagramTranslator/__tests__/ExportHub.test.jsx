import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../../../services/apiClient', () => ({
  default: { post: vi.fn(), get: vi.fn(), download: vi.fn() },
}))

import api from '../../../services/apiClient'
import ExportHub, { DELIVERABLES, generateDeliverable } from '../ExportHub'

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

function downloadResponse(body, contentType, filename, nextCapability = null) {
  const headers = new Headers({
    'content-type': contentType,
    'content-disposition': `attachment; filename="${filename}"`,
  })
  if (nextCapability) headers.set('x-export-capability-next', nextCapability)
  return new Response(body, { status: 200, headers })
}

describe('ExportHub accessibility', () => {
  beforeEach(() => {
    api.post.mockReset()
    api.get.mockReset()
    api.download.mockReset()
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
    api.download.mockReset()
  })

  it('runs the independent IaC lane in parallel with the sequential capability lane', async () => {
    let resolveIac
    let resolveCost
    api.post.mockImplementation(() => new Promise(resolve => { resolveIac = resolve }))
    api.download.mockImplementation(() => new Promise(resolve => { resolveCost = resolve }))

    const user = userEvent.setup()
    render(<ExportHub diagramId="diag-1" />)

    openExportHub()

    // Keep one free artifact and one capability-gated artifact selected.
    for (const label of ['Architecture Package', 'High-Level Design', 'Migration Timeline', 'PDF Analysis Report']) {
      await user.click(await screen.findByLabelText(`Include ${label}`))
    }

    await user.click(screen.getByRole('button', { name: /Generate All Selected/i }))

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        expect.stringContaining('/generate?format=terraform'),
        undefined,
        undefined,
        180_000,
      )
      expect(api.download).toHaveBeenCalledWith(
        '/diagrams/diag-1/cost-estimate/export',
        { headers: {} },
      )
    })

    resolveIac({ code: 'resource {}', filename: 'archmorph-iac.tf' })
    resolveCost(downloadResponse('Service,Monthly Low\nTOTAL,0\n', 'text/csv', 'cost.csv', 'next-token'))

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

    // Keep only the two JSON-delivered capability artifacts selected.
    for (const label of ['Infrastructure Code', 'Cost Estimate', 'Migration Timeline', 'PDF Analysis Report']) {
      await user.click(await screen.findByLabelText(`Include ${label}`))
    }

    await user.click(screen.getByRole('button', { name: /Generate All Selected/i }))

    await waitFor(() => expect(capabilityOrder.length).toBeGreaterThanOrEqual(2), { timeout: 3000 })

    // First capability-gated call should use the initial export token
    expect(capabilityOrder[0].cap).toBe('initial-token')
    // Second should use the token returned by the first response
    expect(capabilityOrder[1].cap).toBe('token-1')
  })

  it('refreshes a missing capability and retries capability-gated deliverables', async () => {
    const capabilityOrder = []
    const capabilityErr = new Error('Missing export capability')
    capabilityErr.status = 401
    const onRefreshExportCapability = vi.fn().mockResolvedValue('fresh-capability')
    const onExportCapability = vi.fn()

    api.post.mockImplementation((url, _body, _signal, _timeout, headers) => {
      const cap = headers?.['X-Export-Capability'] || null
      capabilityOrder.push({ url, cap })
      if (capabilityOrder.length === 1) return Promise.reject(capabilityErr)
      return Promise.resolve({
        content: '<html>pkg</html>',
        filename: 'pkg.html',
        export_capability: 'rotated-capability',
      })
    })

    const user = userEvent.setup()
    render(
      <ExportHub
        diagramId="diag-1"
        onRefreshExportCapability={onRefreshExportCapability}
        onExportCapability={onExportCapability}
      />
    )

    openExportHub()

    // Keep only Architecture Package selected.
    for (const label of ['Infrastructure Code', 'High-Level Design', 'Cost Estimate', 'Migration Timeline', 'PDF Analysis Report']) {
      await user.click(await screen.findByLabelText(`Include ${label}`))
    }

    await user.click(screen.getByRole('button', { name: /Generate All Selected/i }))

    await waitFor(() => expect(capabilityOrder).toHaveLength(2), { timeout: 3000 })
    expect(onRefreshExportCapability).toHaveBeenCalledTimes(1)
    expect(capabilityOrder[0].cap).toBeNull()
    expect(capabilityOrder[1].cap).toBe('fresh-capability')
    expect(onExportCapability).toHaveBeenCalledWith('rotated-capability')
  })
})

describe('ExportHub truthful artifact contracts', () => {
  beforeEach(() => {
    api.post.mockReset()
    api.get.mockReset()
    api.download.mockReset()
  })

  it('offers only the implemented CSV cost format', () => {
    const cost = DELIVERABLES.find(deliverable => deliverable.id === 'cost')
    expect(cost.formats).toEqual([{ id: 'csv', label: 'CSV' }])
  })

  it('downloads the canonical backend cost CSV with capability rotation', async () => {
    api.download.mockResolvedValueOnce(downloadResponse(
      'Service,Monthly Low (USD)\nTOTAL,10\n',
      'text/csv; charset=utf-8',
      'cost-estimate-diag-1.csv',
      'cost-next',
    ))

    const result = await generateDeliverable('diag-1', { id: 'cost' }, 'csv', true, 'cost-current')

    expect(api.download).toHaveBeenCalledWith('/diagrams/diag-1/cost-estimate/export', {
      headers: { 'X-Export-Capability': 'cost-current' },
    })
    expect(result).toMatchObject({
      filename: 'cost-estimate-diag-1.csv',
      format: 'cost-csv',
      mimeType: 'text/csv',
      exportCapability: 'cost-next',
    })
    expect(await result.blob.text()).toContain('TOTAL,10')
  })

  it('generates and exports the canonical seven-phase timeline', async () => {
    api.post.mockResolvedValueOnce({ phases: Array.from({ length: 7 }, (_, index) => ({ order: index + 1 })) })
    api.download.mockResolvedValueOnce(downloadResponse(
      '# Migration Timeline\n\n## Phase 1',
      'text/markdown',
      'timeline-diag-1.md',
      'timeline-next',
    ))

    const result = await generateDeliverable('diag-1', { id: 'timeline' }, 'markdown', true, 'timeline-current')

    expect(api.post).toHaveBeenCalledWith('/diagrams/diag-1/migration-timeline')
    expect(api.download).toHaveBeenCalledWith('/diagrams/diag-1/migration-timeline/export?format=md', {
      headers: { 'X-Export-Capability': 'timeline-current' },
    })
    expect(result).toMatchObject({
      filename: 'timeline-diag-1.md',
      format: 'timeline-markdown',
      mimeType: 'text/markdown',
      exportCapability: 'timeline-next',
    })
  })

  it('uses the real streamed analysis report instead of HLD export', async () => {
    api.download.mockResolvedValueOnce(downloadResponse(
      '%PDF-1.7\n',
      'application/pdf',
      'archmorph-report-diag-1.pdf',
      'report-next',
    ))

    const result = await generateDeliverable('diag-1', { id: 'pdf-report' }, null, true, 'report-current')

    expect(api.download).toHaveBeenCalledWith('/diagrams/diag-1/report?format=pdf', {
      headers: { 'X-Export-Capability': 'report-current' },
    })
    expect(api.post).not.toHaveBeenCalledWith(expect.stringContaining('export-hld'), expect.anything())
    expect(result).toMatchObject({
      filename: 'archmorph-report-diag-1.pdf',
      format: 'analysis-report-pdf',
      mimeType: 'application/pdf',
      exportCapability: 'report-next',
    })
    expect(await result.blob.text()).toMatch(/^%PDF-/)
  })
})