import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import CompliancePanel from '../CompliancePanel';

// Mock the apiClient module
vi.mock('../../services/apiClient', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import api from '../../services/apiClient';

describe('CompliancePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows upload prompt when no diagramId is provided', () => {
    render(<CompliancePanel />);
    expect(screen.getByText(/Upload a diagram first/)).toBeInTheDocument();
  });

  it('shows "Run Assessment" button when diagramId is provided but not loaded', () => {
    render(<CompliancePanel diagramId="test-123" />);
    expect(screen.getByText('Compliance Assessment')).toBeInTheDocument();
    expect(screen.getByText('Run Assessment')).toBeInTheDocument();
  });

  it('shows compliance frameworks description', () => {
    render(<CompliancePanel diagramId="test-123" />);
    expect(screen.getByText(/HIPAA, PCI-DSS, SOC 2, GDPR/)).toBeInTheDocument();
  });

  it('clicking Run Assessment triggers fetch', async () => {
    api.get.mockResolvedValue({
      overall_score: 85,
      frameworks: [],
      total_gaps: 0,
      critical_gaps: 0,
    });

    render(<CompliancePanel diagramId="test-123" />);
    fireEvent.click(screen.getByText('Run Assessment'));

    expect(api.get).toHaveBeenCalledWith('/diagrams/test-123/compliance');
  });

  it('shows loading state during fetch', async () => {
    api.get.mockReturnValue(new Promise(() => {})); // never resolves

    render(<CompliancePanel diagramId="test-123" />);
    fireEvent.click(screen.getByText('Run Assessment'));

    expect(screen.getByText(/Running compliance checks/)).toBeInTheDocument();
  });

  it('shows error state on fetch failure', async () => {
    api.get.mockRejectedValue(new Error('Network error'));

    render(<CompliancePanel diagramId="test-123" />);
    fireEvent.click(screen.getByText('Run Assessment'));

    await vi.waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });

  it('renders compliance score after successful fetch', async () => {
    api.get.mockResolvedValue({
      overall_score: 85,
      frameworks: [
        {
          framework: 'HIPAA',
          score: 80,
          controls_met: 8,
          total_controls: 10,
          gaps: [],
        },
      ],
      total_gaps: 0,
      critical_gaps: 0,
    });

    render(<CompliancePanel diagramId="test-123" />);
    fireEvent.click(screen.getByText('Run Assessment'));

    await vi.waitFor(() => {
      expect(screen.getByText('Compliance Score')).toBeInTheDocument();
    });
    expect(screen.getByText('HIPAA')).toBeInTheDocument();
    expect(screen.getByText(/No gaps detected/)).toBeInTheDocument();
  });

  it('shows gap count when gaps exist', async () => {
    api.get.mockResolvedValue({
      overall_score: 60,
      frameworks: [
        {
          framework: 'PCI-DSS',
          score: 60,
          controls_met: 6,
          total_controls: 10,
          gaps: [
            { control: 'Encryption at rest', severity: 'high', description: 'Missing', remediation: 'Enable encryption' },
          ],
        },
      ],
      total_gaps: 1,
      critical_gaps: 0,
    });

    render(<CompliancePanel diagramId="test-123" />);
    fireEvent.click(screen.getByText('Run Assessment'));

    await vi.waitFor(() => {
      expect(screen.getByText(/1 gap found/)).toBeInTheDocument();
    });
  });
});
