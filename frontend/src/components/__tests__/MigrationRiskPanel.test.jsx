import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import MigrationRiskPanel from '../MigrationRiskPanel';

vi.mock('../../services/apiClient', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import api from '../../services/apiClient';

describe('MigrationRiskPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows upload prompt when no diagramId', () => {
    render(<MigrationRiskPanel />);
    expect(screen.getByText(/Upload a diagram first/)).toBeInTheDocument();
  });

  it('shows "Compute Risk Score" button when diagramId given', () => {
    render(<MigrationRiskPanel diagramId="test-456" />);
    expect(screen.getByText('Migration Risk Assessment')).toBeInTheDocument();
    expect(screen.getByText('Compute Risk Score')).toBeInTheDocument();
  });

  it('shows risk factors description', () => {
    render(<MigrationRiskPanel diagramId="test-456" />);
    expect(screen.getByText(/Analyze potential risks across 6 weighted factors/)).toBeInTheDocument();
  });

  it('clicking Compute triggers fetch', () => {
    api.get.mockResolvedValue({
      overall_score: 45,
      tier: 'moderate',
      factors: {},
      recommendations: [],
    });

    render(<MigrationRiskPanel diagramId="test-456" />);
    fireEvent.click(screen.getByText('Compute Risk Score'));

    expect(api.get).toHaveBeenCalledWith('/diagrams/test-456/risk-score');
  });

  it('shows loading state during fetch', () => {
    api.get.mockReturnValue(new Promise(() => {}));

    render(<MigrationRiskPanel diagramId="test-456" />);
    fireEvent.click(screen.getByText('Compute Risk Score'));

    expect(screen.getByText(/Computing migration risk/)).toBeInTheDocument();
  });

  it('shows error state on fetch failure', async () => {
    api.get.mockRejectedValue(new Error('Server error'));

    render(<MigrationRiskPanel diagramId="test-456" />);
    fireEvent.click(screen.getByText('Compute Risk Score'));

    await vi.waitFor(() => {
      expect(screen.getByText('Server error')).toBeInTheDocument();
    });
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });

  it('renders risk score after successful fetch', async () => {
    api.get.mockResolvedValue({
      overall_score: 45,
      tier: 'moderate',
      factors: {
        complexity: { score: 50, weight: 0.2, description: 'Service complexity' },
        data: { score: 40, weight: 0.3, description: 'Data migration risk' },
      },
      recommendations: [
        { description: 'Consider staged migration approach' },
      ],
    });

    render(<MigrationRiskPanel diagramId="test-456" />);
    fireEvent.click(screen.getByText('Compute Risk Score'));

    await vi.waitFor(() => {
      expect(screen.getByText('Migration Risk Score')).toBeInTheDocument();
    });
    // Should show factor names (may appear in both title and description)
    expect(screen.getAllByText(/complexity/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/data/i).length).toBeGreaterThan(0);
    // Should show recommendation
    expect(screen.getByText('Consider staged migration approach')).toBeInTheDocument();
  });

  it('renders Recalculate button after results load', async () => {
    api.get.mockResolvedValue({
      overall_score: 30,
      tier: 'low',
      factors: {},
      recommendations: [],
    });

    render(<MigrationRiskPanel diagramId="test-456" />);
    fireEvent.click(screen.getByText('Compute Risk Score'));

    await vi.waitFor(() => {
      expect(screen.getByText('Recalculate')).toBeInTheDocument();
    });
  });
});
