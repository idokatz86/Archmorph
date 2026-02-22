import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import LegalPages from '../LegalPages';

describe('LegalPages', () => {
  it('renders legal page index with all document links', () => {
    render(<LegalPages />);
    expect(screen.getByTestId('legal-pages')).toBeInTheDocument();
    expect(screen.getByTestId('legal-link-terms')).toBeInTheDocument();
    expect(screen.getByTestId('legal-link-privacy')).toBeInTheDocument();
    expect(screen.getByTestId('legal-link-dpa')).toBeInTheDocument();
    expect(screen.getByTestId('legal-link-ai-disclaimer')).toBeInTheDocument();
    expect(screen.getByTestId('legal-link-cookies')).toBeInTheDocument();
  });

  it('renders Legal & Privacy heading', () => {
    render(<LegalPages />);
    expect(screen.getByText('Legal & Privacy')).toBeInTheDocument();
  });

  it('navigates to Terms of Service on click', () => {
    render(<LegalPages />);
    fireEvent.click(screen.getByTestId('legal-link-terms'));
    expect(screen.getByTestId('legal-terms')).toBeInTheDocument();
    expect(screen.getByText('Terms of Service')).toBeInTheDocument();
  });

  it('navigates to Privacy Policy on click', () => {
    render(<LegalPages />);
    fireEvent.click(screen.getByTestId('legal-link-privacy'));
    expect(screen.getByTestId('legal-privacy')).toBeInTheDocument();
    expect(screen.getByText('Privacy Policy')).toBeInTheDocument();
  });

  it('navigates to AI Disclaimer on click', () => {
    render(<LegalPages />);
    fireEvent.click(screen.getByTestId('legal-link-ai-disclaimer'));
    expect(screen.getByTestId('legal-ai-disclaimer')).toBeInTheDocument();
    expect(screen.getByText('AI Disclaimer')).toBeInTheDocument();
  });

  it('navigates to Cookie Policy on click', () => {
    render(<LegalPages />);
    fireEvent.click(screen.getByTestId('legal-link-cookies'));
    expect(screen.getByTestId('legal-cookies')).toBeInTheDocument();
    expect(screen.getByText('Cookie Policy')).toBeInTheDocument();
  });

  it('navigates back from section to index', () => {
    render(<LegalPages />);
    fireEvent.click(screen.getByTestId('legal-link-terms'));
    expect(screen.getByTestId('legal-terms')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Back to Legal'));
    expect(screen.getByTestId('legal-pages')).toBeInTheDocument();
  });

  it('shows Back button when onBack is provided', () => {
    const onBack = vi.fn();
    render(<LegalPages onBack={onBack} />);
    const backBtn = screen.getByText('Back');
    fireEvent.click(backBtn);
    expect(onBack).toHaveBeenCalled();
  });

  it('navigates to DPA on click', () => {
    render(<LegalPages />);
    fireEvent.click(screen.getByTestId('legal-link-dpa'));
    expect(screen.getByTestId('legal-dpa')).toBeInTheDocument();
    expect(screen.getByText('Data Processing Agreement')).toBeInTheDocument();
  });

  it('shows DPO contact section', () => {
    render(<LegalPages />);
    expect(screen.getByText('Contact DPO')).toBeInTheDocument();
  });

  it('shows Your Privacy Rights section', () => {
    render(<LegalPages />);
    expect(screen.getByText('Your Privacy Rights')).toBeInTheDocument();
  });
});
