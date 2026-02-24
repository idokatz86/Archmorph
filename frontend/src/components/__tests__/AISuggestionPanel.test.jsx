import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import AISuggestionPanel from '../AISuggestionPanel';

vi.mock('../../services/apiClient', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

describe('AISuggestionPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the panel heading', () => {
    render(<AISuggestionPanel />);
    expect(screen.getByText('AI Mapping Suggestions')).toBeInTheDocument();
  });

  it('renders GPT description', () => {
    render(<AISuggestionPanel />);
    expect(screen.getByText(/GPT-4o-powered cross-cloud/)).toBeInTheDocument();
  });

  it('renders Single Service Lookup section', () => {
    render(<AISuggestionPanel />);
    expect(screen.getByText('Single Service Lookup')).toBeInTheDocument();
  });

  it('renders service name input', () => {
    render(<AISuggestionPanel />);
    expect(screen.getByPlaceholderText(/Amazon SQS/)).toBeInTheDocument();
  });

  it('renders provider selector with AWS and GCP', () => {
    render(<AISuggestionPanel />);
    const selects = screen.getAllByRole('combobox');
    expect(selects.length).toBeGreaterThan(0);
  });

  it('renders Suggest button', () => {
    render(<AISuggestionPanel />);
    expect(screen.getByText('Suggest')).toBeInTheDocument();
  });

  it('renders Dependency Graph section when diagramId is provided', () => {
    render(<AISuggestionPanel diagramId="test-789" />);
    expect(screen.getByText('Dependency Graph')).toBeInTheDocument();
    expect(screen.getByText('Generate')).toBeInTheDocument();
  });

  it('does not render Dependency Graph when no diagramId', () => {
    render(<AISuggestionPanel />);
    expect(screen.queryByText('Dependency Graph')).not.toBeInTheDocument();
  });
});
