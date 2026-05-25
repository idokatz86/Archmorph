import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import React from 'react'
import DataLifecyclePanel from '../../DiagramTranslator/DataLifecyclePanel'

const receipt = {
  schema_version: '2026-05-25',
  receipt_id: 'tr-abc123',
  correlation_id: 'diag-1',
  diagram_id: 'diag-1',
  status: 'active',
  retention: {
    class: 'ephemeral-analysis',
    customer_content_ttl_seconds: 7200,
    uploaded_at: '2026-05-25T10:00:00+00:00',
    expires_at: '2026-05-25T12:00:00+00:00',
  },
  export_capability: {
    status: 'issued',
    expires_in_seconds: 900,
  },
  ai_processing: {
    processor: 'Azure OpenAI',
    training_use: 'not_used_by_archmorph_for_model_training',
  },
  artifacts: {
    uploaded_content: 'present',
    analysis_session: 'present',
  },
  purge: {
    status: 'not_requested',
    server_content_deleted: false,
    client_cache_action: 'clear_session_storage_after_successful_purge',
  },
  audit_security_logs: {
    retained: true,
    retention_days: 30,
    contains_customer_content: false,
  },
}

describe('DataLifecyclePanel', () => {
  beforeEach(() => {
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:trust-receipt')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const createElement = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation((tagName, options) => {
      const element = createElement(tagName, options)
      if (tagName === 'a') element.click = vi.fn()
      return element
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows lifecycle receipt fields from backend analysis', () => {
    render(<DataLifecyclePanel diagramId="diag-1" analysis={{ trust_receipt: receipt }} exportCapability="cap-token" />)

    expect(screen.getByText('Data lifecycle receipt')).toBeInTheDocument()
    expect(screen.getByText('diag-1')).toBeInTheDocument()
    expect(screen.getByText('ephemeral-analysis')).toBeInTheDocument()
    expect(screen.getByText('15m')).toBeInTheDocument()
    expect(screen.getByText('Azure OpenAI')).toBeInTheDocument()
    expect(screen.getByText('Upload: present / Analysis: present')).toBeInTheDocument()
    expect(screen.getByText('Audit/security logs retained / no customer content')).toBeInTheDocument()
  })

  it('calls purge handler from the active receipt', async () => {
    const user = userEvent.setup()
    const onPurge = vi.fn()
    render(<DataLifecyclePanel diagramId="diag-1" analysis={{ trust_receipt: receipt }} onPurge={onPurge} />)

    await user.click(screen.getByRole('button', { name: /Purge Current Analysis/i }))
    expect(onPurge).toHaveBeenCalledTimes(1)
  })

  it('shows purge confirmation and hides purge action after deletion', () => {
    const purgeReceipt = {
      ...receipt,
      status: 'purged',
      purge: { ...receipt.purge, status: 'purged', server_content_deleted: true },
      artifacts: { uploaded_content: 'purged', analysis_session: 'purged' },
    }
    render(<DataLifecyclePanel purgeReceipt={purgeReceipt} onPurge={vi.fn()} />)

    expect(screen.getByText('Purged')).toBeInTheDocument()
    expect(screen.getByText('Upload: purged / Analysis: purged')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Purge Current Analysis/i })).not.toBeInTheDocument()
  })

  it('ignores stale purge receipt when a different diagram is active', () => {
    const purgeReceipt = {
      ...receipt,
      status: 'purged',
      purge: { ...receipt.purge, status: 'purged', server_content_deleted: true },
    }
    render(<DataLifecyclePanel diagramId="diag-2" analysis={null} purgeReceipt={purgeReceipt} />)

    expect(screen.getByText('diag-2')).toBeInTheDocument()
    expect(screen.getByText('Available')).toBeInTheDocument()
    expect(screen.getAllByText('Not available')).toHaveLength(3)
  })

  it('downloads the receipt as JSON', async () => {
    const user = userEvent.setup()
    render(<DataLifecyclePanel diagramId="diag-1" analysis={{ trust_receipt: receipt }} />)

    await user.click(screen.getByRole('button', { name: /Download Receipt/i }))

    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:trust-receipt')
  })
})