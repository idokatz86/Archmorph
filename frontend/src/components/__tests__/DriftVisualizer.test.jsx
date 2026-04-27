import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { DriftVisualizer } from '../DriftDashboard/DriftVisualizer'

const jsonResponse = (body) => ({
  ok: true,
  status: 200,
  headers: new Headers({ 'content-type': 'application/json' }),
  json: () => Promise.resolve(body),
})

describe('DriftVisualizer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    fetch.mockImplementation((url) => {
      const path = String(url)
      if (path.includes('/drift/baselines') && !path.includes('/report') && !path.includes('/findings')) {
        return Promise.resolve(jsonResponse({
          baseline_id: 'baseline-test',
          name: 'Archmorph production sample',
          last_result: {
            audit_id: 'audit-test',
            overall_score: 0.38,
            summary: { status: 'attention_required', modified: 1, missing: 1, shadow: 1, matched: 1 },
            detailed_findings: [
              {
                finding_id: 'finding-api',
                id: 'api-prod',
                status: 'yellow',
                message: 'Configuration differs from baseline',
                recommendation: 'Review the tracked settings.',
                resolution_status: 'open',
              },
            ],
          },
        }))
      }
      if (path.includes('/findings/finding-api')) {
        return Promise.resolve(jsonResponse({
          finding_id: 'finding-api',
          id: 'api-prod',
          status: 'yellow',
          message: 'Configuration differs from baseline',
          recommendation: 'Review the tracked settings.',
          resolution_status: 'accepted',
        }))
      }
      if (path.includes('/report')) {
        return Promise.resolve(jsonResponse({ content: '# Drift Report: Archmorph production sample\n' }))
      }
      return Promise.resolve(jsonResponse({}))
    })
  })

  it('creates a sample baseline and exports its report', async () => {
    render(<DriftVisualizer onSync={vi.fn()} />)

    fireEvent.click(screen.getByText('Run Sample Drift Audit'))

    expect(await screen.findByText('api-prod')).toBeInTheDocument()
    expect(screen.getByText('38%')).toBeInTheDocument()

    fireEvent.click(screen.getByLabelText('Accept finding api-prod'))
    expect(await screen.findByText('accepted')).toBeInTheDocument()

    fireEvent.click(screen.getByText('Export Report'))
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled())
  })
})
