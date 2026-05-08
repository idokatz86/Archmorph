import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PricingTab from '../PricingTab'

const baseCostBreakdown = {
  summary: { total_monthly: { low: 100, mid: 150, high: 200 }, region: 'eastus', service_count: 2 },
  services: [],
  cost_drivers: [],
  optimizations: [],
  cost_by_category: {},
}

describe('PricingTab', () => {
  it('renders cost summary cards', () => {
    render(<PricingTab costBreakdown={baseCostBreakdown} loading={false} onSetStep={vi.fn()} />)

    expect(screen.getByText('Low Estimate')).toBeInTheDocument()
    expect(screen.getByText('Mid Estimate')).toBeInTheDocument()
    expect(screen.getByText('High Estimate')).toBeInTheDocument()
  })

  it('shows loading spinner when loading', () => {
    render(<PricingTab loading={true} onSetStep={vi.fn()} />)
    expect(screen.getByText('Loading pricing data...')).toBeInTheDocument()
  })

  it('shows empty state when no costBreakdown', () => {
    render(<PricingTab loading={false} onSetStep={vi.fn()} />)
    expect(screen.getByText('Pricing data is loading...')).toBeInTheDocument()
  })

  it('renders object-shaped service assumptions without crashing', async () => {
    const user = userEvent.setup()
    const breakdown = {
      ...baseCostBreakdown,
      services: [
        {
          service: 'Azure Functions',
          sku: 'Consumption',
          monthly_low: 10,
          monthly_mid: 20,
          monthly_high: 30,
          formula: 'executions * gb-seconds',
          assumptions: [{ message: 'One million executions' }],
        },
      ],
    }

    render(<PricingTab costBreakdown={breakdown} loading={false} onSetStep={vi.fn()} />)

    await user.click(screen.getByText('Azure Functions'))
    expect(screen.getByText('One million executions')).toBeInTheDocument()
  })

  it('renders object-shaped action_steps without crashing', async () => {
    const user = userEvent.setup()
    const breakdown = {
      ...baseCostBreakdown,
      optimizations: [
        {
          title: 'Use Reserved Instances',
          description: 'Save by committing to 1-year reservations.',
          savings: '30%',
          effort: 'low',
          action_steps: [
            { type: 'step', message: 'Evaluate workload patterns' },
            'plain string step',
            { name: 'Purchase reserved instances in Azure portal' },
          ],
        },
      ],
    }

    render(<PricingTab costBreakdown={breakdown} loading={false} onSetStep={vi.fn()} />)

    await user.click(screen.getByText('Show action steps'))

    expect(screen.getByText('Evaluate workload patterns')).toBeInTheDocument()
    expect(screen.getByText('plain string step')).toBeInTheDocument()
    expect(screen.getByText('Purchase reserved instances in Azure portal')).toBeInTheDocument()
  })

  it('renders object-shaped pricing_assumptions without crashing', () => {
    const breakdown = {
      ...baseCostBreakdown,
      pricing_assumptions: [
        { type: 'assumption', message: 'Pay-as-you-go pricing assumed' },
        'plain string assumption',
        { name: 'East US region pricing' },
      ],
    }

    render(<PricingTab costBreakdown={breakdown} loading={false} onSetStep={vi.fn()} />)

    expect(screen.getByText('Pay-as-you-go pricing assumed')).toBeInTheDocument()
    expect(screen.getByText('plain string assumption')).toBeInTheDocument()
    expect(screen.getByText('East US region pricing')).toBeInTheDocument()
  })
})
