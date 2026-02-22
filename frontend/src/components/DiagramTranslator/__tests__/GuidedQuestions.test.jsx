import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import GuidedQuestions from '../../DiagramTranslator/GuidedQuestions'

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
    expect(screen.getByText(/5 AWS services across 2 zones/)).toBeInTheDocument()
  })

  it('shows progress bar', () => {
    render(<GuidedQuestions {...defaultProps} />)
    expect(screen.getByText('2 of 3 answered')).toBeInTheDocument()
  })

  it('renders questions', () => {
    render(<GuidedQuestions {...defaultProps} />)
    expect(screen.getByText('What region do you prefer?')).toBeInTheDocument()
    expect(screen.getByText('Enable monitoring?')).toBeInTheDocument()
    expect(screen.getByText('Select features')).toBeInTheDocument()
  })

  it('renders single_choice radio options', () => {
    render(<GuidedQuestions {...defaultProps} />)
    expect(screen.getByText('East US')).toBeInTheDocument()
    expect(screen.getByText('West US')).toBeInTheDocument()
  })

  it('renders boolean yes/no options', () => {
    render(<GuidedQuestions {...defaultProps} />)
    const yesOptions = screen.getAllByText(/^yes$/i)
    expect(yesOptions.length).toBeGreaterThan(0)
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

  it('renders Skip Customization button', () => {
    render(<GuidedQuestions {...defaultProps} />)
    expect(screen.getByText('Skip Customization')).toBeInTheDocument()
  })

  it('renders Apply and View Results button', () => {
    render(<GuidedQuestions {...defaultProps} />)
    expect(screen.getByText('Apply and View Results')).toBeInTheDocument()
  })

  it('calls onSkip when skip button clicked', async () => {
    const user = userEvent.setup()
    render(<GuidedQuestions {...defaultProps} />)
    await user.click(screen.getByText('Skip Customization'))
    expect(defaultProps.onSkip).toHaveBeenCalledTimes(1)
  })

  it('calls onApplyAnswers when apply button clicked', async () => {
    const user = userEvent.setup()
    render(<GuidedQuestions {...defaultProps} />)
    await user.click(screen.getByText('Apply and View Results'))
    expect(defaultProps.onApplyAnswers).toHaveBeenCalledTimes(1)
  })

  it('shows category headers', () => {
    render(<GuidedQuestions {...defaultProps} />)
    const infraElements = screen.getAllByText('infrastructure')
    expect(infraElements.length).toBeGreaterThan(0)
    const opsElements = screen.getAllByText('operations')
    expect(opsElements.length).toBeGreaterThan(0)
  })
})
