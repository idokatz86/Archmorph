/**
 * Tests for ArchitectReviewQueue component — Issue #1137
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ArchitectReviewQueue from '../../DiagramTranslator/ArchitectReviewQueue'

// ── Fixtures ──────────────────────────────────────────────────────────────────

const makeItem = (overrides = {}) => ({
  id: 'abc123',
  bucket: 'low_confidence',
  title: 'Low-confidence mapping: EC2 → Azure VM',
  description: 'The mapping from EC2 to Azure VM has a confidence of 60%. Validate this mapping.',
  severity: 'medium',
  source: { source_service: 'EC2', azure_service: 'Azure VM', confidence: 0.6 },
  ...overrides,
})

const makeHighItem = () =>
  makeItem({
    id: 'high1',
    bucket: 'security_concern',
    title: 'Security concern: Encryption at rest not configured',
    description: 'Encryption at rest is not configured for Blob Storage.',
    severity: 'high',
  })

const makeGapItem = () =>
  makeItem({
    id: 'gap1',
    bucket: 'architecture_gap',
    title: 'Architecture gap: Missing load balancer',
    description: 'No load balancer detected in frontend zone.',
    severity: 'medium',
  })

const defaultProps = {
  items: [],
  dispositions: {},
  summary: {},
  onDispose: vi.fn(),
  loading: false,
}

// ─────────────────────────────────────────────────────────────────────────────
describe('ArchitectReviewQueue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // ── Empty / loading states ─────────────────────────────────────────────────

  it('renders nothing when items are empty', () => {
    const { container } = render(<ArchitectReviewQueue {...defaultProps} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders a loading skeleton when loading=true', () => {
    const { container } = render(<ArchitectReviewQueue {...defaultProps} loading={true} />)
    // Loading skeleton should render something (animated pulses)
    expect(container.firstChild).not.toBeNull()
  })

  it('renders nothing when loading=false and items empty', () => {
    const { container } = render(<ArchitectReviewQueue {...defaultProps} loading={false} items={[]} />)
    expect(container.firstChild).toBeNull()
  })

  // ── Rendering items ────────────────────────────────────────────────────────

  it('renders the queue heading when items are present', () => {
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} />)
    expect(screen.getByRole('region', { name: /architect review queue/i })).toBeInTheDocument()
  })

  it('renders item titles in the queue', () => {
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} />)
    expect(screen.getByText('Low-confidence mapping: EC2 → Azure VM')).toBeInTheDocument()
  })

  it('renders item description', () => {
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} />)
    expect(screen.getByText(/The mapping from EC2 to Azure VM has a confidence/i)).toBeInTheDocument()
  })

  it('renders object-shaped item text without crashing', () => {
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem({
      title: { message: 'Object title rendered safely' },
      description: { description: 'Object description rendered safely' },
    })]} />)
    expect(screen.getByText('Object title rendered safely')).toBeInTheDocument()
    expect(screen.getByText('Object description rendered safely')).toBeInTheDocument()
  })

  it('renders multiple buckets when items span buckets', () => {
    const items = [makeHighItem(), makeGapItem()]
    render(<ArchitectReviewQueue {...defaultProps} items={items} />)
    expect(screen.getByText(/Security \/ Compliance Concerns/i)).toBeInTheDocument()
    expect(screen.getByText(/Architecture Gaps/i)).toBeInTheDocument()
  })

  // ── Severity labels ────────────────────────────────────────────────────────

  it('shows High severity badge for high-severity items', () => {
    render(<ArchitectReviewQueue {...defaultProps} items={[makeHighItem()]} />)
    expect(screen.getByText('High')).toBeInTheDocument()
  })

  it('shows Medium severity badge for medium-severity items', () => {
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} />)
    expect(screen.getByText('Medium')).toBeInTheDocument()
  })

  // ── Action buttons ─────────────────────────────────────────────────────────

  it('renders all four action buttons per item', () => {
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} />)
    expect(screen.getByRole('button', { name: /accept/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /edit/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /mark as risk/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /exclude/i })).toBeInTheDocument()
  })

  it('calls onDispose with "accept" when Accept is clicked', async () => {
    const onDispose = vi.fn()
    const user = userEvent.setup()
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} onDispose={onDispose} />)
    await user.click(screen.getByRole('button', { name: /accept/i }))
    expect(onDispose).toHaveBeenCalledWith('abc123', 'accept', undefined)
  })

  it('calls onDispose with "mark_risk" when Mark as risk is clicked', async () => {
    const onDispose = vi.fn()
    const user = userEvent.setup()
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} onDispose={onDispose} />)
    await user.click(screen.getByRole('button', { name: /mark as risk/i }))
    expect(onDispose).toHaveBeenCalledWith('abc123', 'mark_risk', undefined)
  })

  it('calls onDispose with "exclude" when Exclude is clicked', async () => {
    const onDispose = vi.fn()
    const user = userEvent.setup()
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} onDispose={onDispose} />)
    await user.click(screen.getByRole('button', { name: /exclude/i }))
    expect(onDispose).toHaveBeenCalledWith('abc123', 'exclude', undefined)
  })

  // ── Edit flow ──────────────────────────────────────────────────────────────

  it('shows a textarea when Edit is clicked', async () => {
    const user = userEvent.setup()
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} />)
    await user.click(screen.getByRole('button', { name: /edit/i }))
    expect(screen.getByRole('textbox', { name: /edit review item/i })).toBeInTheDocument()
  })

  it('calls onDispose with "edit" and edited text when Save edit is clicked', async () => {
    const onDispose = vi.fn()
    const user = userEvent.setup()
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} onDispose={onDispose} />)
    await user.click(screen.getByRole('button', { name: /edit/i }))
    const textarea = screen.getByRole('textbox', { name: /edit review item/i })
    await user.clear(textarea)
    await user.type(textarea, 'Custom edited text')
    await user.click(screen.getByRole('button', { name: /save edit/i }))
    expect(onDispose).toHaveBeenCalledWith('abc123', 'edit', 'Custom edited text')
  })

  it('hides textarea when Cancel is clicked', async () => {
    const user = userEvent.setup()
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} />)
    await user.click(screen.getByRole('button', { name: /edit/i }))
    expect(screen.getByRole('textbox')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /cancel/i }))
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  // ── Disposition state rendering ────────────────────────────────────────────

  it('shows Accepted badge when item is disposed as accept', () => {
    const dispositions = { abc123: { action: 'accept' } }
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} dispositions={dispositions} />)
    expect(screen.getByText('Accepted')).toBeInTheDocument()
  })

  it('shows Marked as risk badge when item is disposed as mark_risk', () => {
    const dispositions = { abc123: { action: 'mark_risk' } }
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} dispositions={dispositions} />)
    expect(screen.getByText('Marked as risk')).toBeInTheDocument()
  })

  it('shows Excluded badge when item is disposed as exclude', () => {
    const dispositions = { abc123: { action: 'exclude' } }
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} dispositions={dispositions} />)
    expect(screen.getByText('Excluded')).toBeInTheDocument()
  })

  it('shows edited_text instead of original description when disposition is edit', () => {
    const dispositions = { abc123: { action: 'edit', edited_text: 'My custom note.' } }
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} dispositions={dispositions} />)
    expect(screen.getByText('My custom note.')).toBeInTheDocument()
  })

  // ── Summary / gate banner ──────────────────────────────────────────────────

  it('shows blockers count when summary.blocking > 0', () => {
    const summary = { total: 1, unresolved: 1, blocking: 2, resolved: 0, risks_accepted: 0, gated: true }
    render(<ArchitectReviewQueue {...defaultProps} items={[makeHighItem()]} summary={summary} />)
    expect(screen.getByText(/2 blockers/i)).toBeInTheDocument()
  })

  it('shows deliverables locked banner when gated', () => {
    const summary = { total: 1, unresolved: 1, blocking: 1, resolved: 0, risks_accepted: 0, gated: true }
    render(<ArchitectReviewQueue {...defaultProps} items={[makeHighItem()]} summary={summary} />)
    expect(screen.getByText(/Deliverables are locked/i)).toBeInTheDocument()
  })

  it('shows "All reviewed" when all items are resolved', () => {
    const item = makeItem()
    const dispositions = { abc123: { action: 'accept' } }
    const summary = { total: 1, unresolved: 0, blocking: 0, resolved: 1, risks_accepted: 0, gated: false }
    render(
      <ArchitectReviewQueue
        {...defaultProps}
        items={[item]}
        dispositions={dispositions}
        summary={summary}
      />
    )
    expect(screen.getByText(/All reviewed/i)).toBeInTheDocument()
  })

  it('shows risks accepted count in summary', () => {
    const summary = { total: 1, unresolved: 0, blocking: 0, resolved: 1, risks_accepted: 1, gated: false }
    const dispositions = { abc123: { action: 'mark_risk' } }
    render(
      <ArchitectReviewQueue
        {...defaultProps}
        items={[makeItem()]}
        dispositions={dispositions}
        summary={summary}
      />
    )
    expect(screen.getByText(/1 risk accepted/i)).toBeInTheDocument()
  })

  // ── Collapsibility ─────────────────────────────────────────────────────────

  it('hides body when Hide button is clicked', async () => {
    const user = userEvent.setup()
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} />)
    // Queue body should initially be visible
    expect(screen.getByText('Low-confidence mapping: EC2 → Azure VM')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /hide/i }))
    expect(screen.queryByText('Low-confidence mapping: EC2 → Azure VM')).toBeNull()
  })

  it('shows body again when Show button is clicked after hiding', async () => {
    const user = userEvent.setup()
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} />)
    await user.click(screen.getByRole('button', { name: /hide/i }))
    await user.click(screen.getByRole('button', { name: /show/i }))
    expect(screen.getByText('Low-confidence mapping: EC2 → Azure VM')).toBeInTheDocument()
  })

  // ── Bucket collapsibility ──────────────────────────────────────────────────

  it('collapses a bucket when its header is clicked', async () => {
    const user = userEvent.setup()
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} />)
    const bucketButton = screen.getByRole('button', { name: /low-confidence mappings/i })
    await user.click(bucketButton)
    // After collapse, the item text should not be visible
    expect(screen.queryByText('Low-confidence mapping: EC2 → Azure VM')).toBeNull()
  })

  // ── Keyboard accessibility ─────────────────────────────────────────────────

  it('action buttons have aria-pressed attribute', () => {
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} />)
    const acceptButton = screen.getByRole('button', { name: /accept/i })
    expect(acceptButton).toHaveAttribute('aria-pressed', 'false')
  })

  it('action button aria-pressed becomes true after selection', () => {
    const dispositions = { abc123: { action: 'accept' } }
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} dispositions={dispositions} />)
    const acceptButton = screen.getByRole('button', { name: /accept/i })
    expect(acceptButton).toHaveAttribute('aria-pressed', 'true')
  })

  it('bucket header has aria-expanded attribute', () => {
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} />)
    const bucketButton = screen.getByRole('button', { name: /low-confidence mappings/i })
    expect(bucketButton).toHaveAttribute('aria-expanded', 'true')
  })

  it('show/hide button has aria-expanded attribute', () => {
    render(<ArchitectReviewQueue {...defaultProps} items={[makeItem()]} />)
    const showHideButton = screen.getByRole('button', { name: /hide/i })
    expect(showHideButton).toHaveAttribute('aria-expanded', 'true')
  })
})
