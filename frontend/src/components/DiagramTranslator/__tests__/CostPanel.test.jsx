import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import CostPanel from '../../DiagramTranslator/CostPanel'

describe('CostPanel', () => {
  it('renders nothing when costEstimate is null', () => {
    const { container } = render(<CostPanel costEstimate={null} />)
    expect(container.innerHTML).toBe('')
  })

  it('renders nothing when costEstimate is undefined', () => {
    const { container } = render(<CostPanel />)
    expect(container.innerHTML).toBe('')
  })

  it('renders title when costEstimate provided', () => {
    const costEstimate = {
      total_monthly_estimate: { low: 100, high: 500 },
      services: [],
    }
    render(<CostPanel costEstimate={costEstimate} />)
    expect(screen.getByText('Estimated Monthly Cost')).toBeInTheDocument()
  })

  it('shows low and high estimates', () => {
    const costEstimate = {
      total_monthly_estimate: { low: 150, high: 800 },
      services: [],
    }
    render(<CostPanel costEstimate={costEstimate} />)
    expect(screen.getByText('$150')).toBeInTheDocument()
    expect(screen.getByText('$800')).toBeInTheDocument()
  })

  it('shows region info', () => {
    const costEstimate = {
      region: 'East US',
      service_count: 5,
      total_monthly_estimate: { low: 100, high: 500 },
      services: [],
    }
    render(<CostPanel costEstimate={costEstimate} />)
    expect(screen.getByText('East US')).toBeInTheDocument()
    expect(screen.getByText('(5 services)')).toBeInTheDocument()
  })

  it('renders individual service costs', () => {
    const costEstimate = {
      total_monthly_estimate: { low: 200, high: 600 },
      services: [
        { service: 'Azure VM', monthly_low: 50, monthly_high: 150 },
        { service: 'Azure SQL', monthly_low: 100, monthly_high: 300 },
      ],
    }
    render(<CostPanel costEstimate={costEstimate} />)
    expect(screen.getByText('Azure VM')).toBeInTheDocument()
    expect(screen.getByText('Azure SQL')).toBeInTheDocument()
  })

  it('shows pricing calculator link', () => {
    const costEstimate = {
      total_monthly_estimate: { low: 100, high: 500 },
      services: [],
    }
    render(<CostPanel costEstimate={costEstimate} />)
    expect(screen.getByText('Azure Pricing Calculator')).toBeInTheDocument()
  })
})
