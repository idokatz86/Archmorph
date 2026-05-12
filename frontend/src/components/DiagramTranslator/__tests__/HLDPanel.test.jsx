import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import HLDPanel from '../../DiagramTranslator/HLDPanel'

describe('HLDPanel', () => {
  const defaultProps = {
    hldData: null,
    hldTab: 'overview',
    hldExportLoading: {},
    hldIncludeDiagrams: true,
    copyFeedback: {},
    onSetHldTab: vi.fn(),
    onSetHldIncludeDiagrams: vi.fn(),
    onHldExport: vi.fn(),
    onCopyWithFeedback: vi.fn(),
  }

  it('renders nothing when hldData is null', () => {
    const { container } = render(<HLDPanel {...defaultProps} />)
    expect(container.innerHTML).toBe('')
  })

  it('renders title when hldData is provided', () => {
    const hldData = {
      hld: { title: 'My Architecture HLD', executive_summary: 'Summary text' },
      markdown: '# HLD',
    }
    render(<HLDPanel {...defaultProps} hldData={hldData} />)
    expect(screen.getByText('My Architecture HLD')).toBeInTheDocument()
  })

  it('shows AI-generated subtitle', () => {
    const hldData = {
      hld: { title: 'HLD Doc' },
      markdown: '',
    }
    render(<HLDPanel {...defaultProps} hldData={hldData} />)
    expect(screen.getByText('AI-generated architecture document')).toBeInTheDocument()
  })

  it('shows tab navigation', () => {
    const hldData = { hld: { title: 'HLD' }, markdown: '' }
    render(<HLDPanel {...defaultProps} hldData={hldData} />)
    expect(screen.getByText('Executive Summary')).toBeInTheDocument()
  })

  it('shows export document formats', () => {
    const hldData = { hld: { title: 'HLD' }, markdown: '' }
    render(<HLDPanel {...defaultProps} hldData={hldData} />)
    expect(screen.getByText('Word')).toBeInTheDocument()
    expect(screen.getByText('PDF')).toBeInTheDocument()
    expect(screen.getByText('PowerPoint')).toBeInTheDocument()
  })

  it('shows overview tab content with executive summary', () => {
    const hldData = {
      hld: { title: 'HLD', executive_summary: 'This is the summary' },
      markdown: '',
    }
    render(<HLDPanel {...defaultProps} hldData={hldData} hldTab="overview" />)
    expect(screen.getByText('This is the summary')).toBeInTheDocument()
  })

  it('shows Copy MD and Download buttons', () => {
    const hldData = { hld: { title: 'HLD' }, markdown: '# test' }
    render(<HLDPanel {...defaultProps} hldData={hldData} />)
    expect(screen.getByText('Copy MD')).toBeInTheDocument()
    expect(screen.getByText('Download')).toBeInTheDocument()
  })

  it('shows Include diagrams checkbox', () => {
    const hldData = { hld: { title: 'HLD' }, markdown: '' }
    render(<HLDPanel {...defaultProps} hldData={hldData} />)
    expect(screen.getByText('Include diagrams')).toBeInTheDocument()
  })

  it('shows risk impact with tokenized badges and text labels', () => {
    const hldData = {
      hld: {
        title: 'HLD',
        risks_and_mitigations: [
          { impact: 'High', risk: 'Cutover outage', mitigation: 'Use staged rollout' },
          { impact: 'medium', risk: 'Cost drift', mitigation: 'Set budgets' },
          { impact: 'Low', risk: 'Training gap', mitigation: 'Run enablement' },
        ],
      },
      markdown: '',
    }
    const { container } = render(<HLDPanel {...defaultProps} hldData={hldData} hldTab="risks" />)

    expect(screen.getByLabelText('High impact')).toHaveTextContent('High')
    expect(screen.getByLabelText('Medium impact')).toHaveTextContent('Medium')
    expect(screen.getByLabelText('Low impact')).toHaveTextContent('Low')
    expect(container.innerHTML).not.toContain('bg-red-500')
    expect(container.innerHTML).not.toContain('bg-yellow-500')
    expect(container.innerHTML).not.toContain('bg-green-500')
  })

  it('uses tokenized WAF score badges with icons', () => {
    const hldData = {
      hld: {
        title: 'HLD',
        waf_assessment: {
          reliability: { score: 'low', notes: 'Needs failover' },
          security: { score: 'unknown', notes: 'Needs review' },
        },
      },
      markdown: '',
    }
    const { container } = render(<HLDPanel {...defaultProps} hldData={hldData} hldTab="waf" />)

    expect(screen.getByText('Low')).toBeInTheDocument()
    expect(screen.getByText('Medium')).toBeInTheDocument()
    expect(container.innerHTML).toContain('bg-danger/15')
    expect(container.innerHTML).not.toContain('bg-red-500')
    expect(container.innerHTML).not.toContain('text-red-400')
  })
})
