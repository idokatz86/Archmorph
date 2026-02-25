import { describe, it, expect, vi, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import GuidedQuestions from '../../DiagramTranslator/GuidedQuestions'

beforeAll(() => {
  Element.prototype.scrollTo = vi.fn()
})

describe('GuidedQuestions', () => {
  const mockAnalysis = {
    services_detected: 5,
    source_provider: 'aws',
    zones: [{ id: 1 }, { id: 2 }],
  }

  const mockQuestions = [
    {
      id: 'q1',
      question: 'What region do you prefer?',
      category: 'infrastructure',
      type: 'single_choice',
      default: 'eastus',
      options: [
        { value: 'eastus', label: 'East US' },
        { value: 'westus', label: 'West US' },
      ],
    },
    {
      id: 'q2',
      question: 'Enable monitoring?',
      category: 'operations',
      type: 'boolean',
      default: 'yes',
    },
    {
      id: 'q3',
      question: 'Select features',
      category: 'infrastructure',
      type: 'multi_choice',
      default: [],
      options: [
        { value: 'cdn', label: 'CDN' },
        { value: 'waf', label: 'WAF' },
      ],
    },
  ]

  const defaultProps = {
    analysis: mockAnalysis,
    questions: mockQuestions,
    answers: { q1: 'eastus', q2: 'yes' },
    loading: false,
    onUpdateAnswer: vi.fn(),
    onApplyAnswers: vi.fn(),
    onSkip: vi.fn(),
  }

  it('renders the title', () => {
    render(<GuidedQuestions {...defaultProps} />)
    expect(screen.getByText('Customize Your Azure Architecture')).toBeInTheDocument()
  })

  it('shows services detected info', () => {
    render(<GuidedQuestions {...defaultProps} />)
    expect(screen.getByText(/5 AWS services detected across 2 zones/)).toBeInTheDocument()
  })

  it('shows progress bar', () => {
    render(<GuidedQuestions {...defaultProps} />)
    expect(screen.getByText('2 of 3 answered')).toBeInTheDocument()
  })

  it('renders questions for the active category', () => {
    render(<GuidedQuestions {...defaultProps} />)
    // Only infrastructure category questions are visible on initial render
    expect(screen.getByText('What region do you prefer?')).toBeInTheDocument()
    expect(screen.getByText('Select features')).toBeInTheDocument()
    // q2 (operations category) is on a different tab
    expect(screen.queryByText('Enable monitoring?')).not.toBeInTheDocument()
  })

  it('renders single_choice radio options', () => {
    render(<GuidedQuestions {...defaultProps} />)
    expect(screen.getByText('East US')).toBeInTheDocument()
    expect(screen.getByText('West US')).toBeInTheDocument()
  })

  it('renders boolean toggle on operations tab', async () => {
    const user = userEvent.setup()
    render(<GuidedQuestions {...defaultProps} />)
    // Navigate to operations category tab
    await user.click(screen.getByText(/operations/))
    // Boolean questions use a toggle showing "Yes — Enabled" / "No — Disabled"
    expect(screen.getByText(/Yes — Enabled|No — Disabled/)).toBeInTheDocument()
  })

  it('renders multi_choice checkboxes', () => {
    render(<GuidedQuestions {...defaultProps} />)
    expect(screen.getByText('CDN')).toBeInTheDocument()
    expect(screen.getByText('WAF')).toBeInTheDocument()
  })

  it('calls onUpdateAnswer when radio is selected', async () => {
    const user = userEvent.setup()
    render(<GuidedQuestions {...defaultProps} />)
    await user.click(screen.getByText('West US'))
    expect(defaultProps.onUpdateAnswer).toHaveBeenCalledWith('q1', 'westus')
  })

  it('renders Skip All button', () => {
    render(<GuidedQuestions {...defaultProps} />)
    expect(screen.getByText('Skip All')).toBeInTheDocument()
  })

  it('renders Next Category button on first tab', () => {
    render(<GuidedQuestions {...defaultProps} />)
    // On the first category tab, button says "Next Category"; "Apply and View Results" appears on the last tab
    expect(screen.getByText('Next Category')).toBeInTheDocument()
  })

  it('calls onSkip when skip button clicked', async () => {
    const user = userEvent.setup()
    render(<GuidedQuestions {...defaultProps} />)
    await user.click(screen.getByText('Skip All'))
    expect(defaultProps.onSkip).toHaveBeenCalledTimes(1)
  })

  it('calls onApplyAnswers when apply button clicked on last tab', async () => {
    const user = userEvent.setup()
    render(<GuidedQuestions {...defaultProps} />)
    // Navigate to the last category (operations)
    await user.click(screen.getByText(/operations/))
    // On the last tab, the button says "Apply and View Results"
    await user.click(screen.getByText('Apply and View Results'))
    expect(defaultProps.onApplyAnswers).toHaveBeenCalledTimes(1)
  })

  it('shows category headers', () => {
    render(<GuidedQuestions {...defaultProps} />)
    // Category names include answer count suffix e.g. "infrastructure 1/2"
    const infraElements = screen.getAllByText(/infrastructure/)
    expect(infraElements.length).toBeGreaterThan(0)
    const opsElements = screen.getAllByText(/operations/)
    expect(opsElements.length).toBeGreaterThan(0)
  })
})
