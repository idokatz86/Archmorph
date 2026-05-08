import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import PricingTab from '../PricingTab'

describe('PricingTab', () => {
  it('renders object-shaped pricing assumptions and action steps without crashing', async () => {
    const user = userEvent.setup()
    const costBreakdown = {
      summary: { monthly_low: 10, monthly_mid: 20, monthly_high: 30, region: 'eastus', service_count: 1 },
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
      optimizations: [
        {
          title: 'Use reserved capacity',
          description: 'Reduce steady-state cost',
          savings: '$5/mo',
          effort: 'low',
          action_steps: [{ description: 'Review usage baseline' }],
        },
      ],
      pricing_assumptions: [{ message: 'Prices exclude taxes' }],
    }

    render(
      <PricingTab
        costBreakdown={costBreakdown}
        onSetStep={vi.fn()}
        onExportPackage={vi.fn()}
        exportingPackage={false}
      />
    )

    await user.click(screen.getByText('Azure Functions'))
    expect(screen.getByText('One million executions')).toBeInTheDocument()
    expect(screen.getByText('Prices exclude taxes')).toBeInTheDocument()

    await user.click(screen.getByText('Show action steps'))
    expect(screen.getByText('Review usage baseline')).toBeInTheDocument()
  })
})