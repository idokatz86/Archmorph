import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import LandingPage from '../LandingPage';

describe('LandingPage', () => {
  const defaultProps = {
    onGetStarted: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the landing page container', () => {
    render(<LandingPage {...defaultProps} />);
    expect(screen.getByTestId('landing-page')).toBeInTheDocument();
  });

  it('renders hero headline', () => {
    render(<LandingPage {...defaultProps} />);
    expect(screen.getByText(/Translate Any Cloud Architecture/)).toBeInTheDocument();
    expect(screen.getByText('to Azure')).toBeInTheDocument();
  });

  it('hero CTA calls onGetStarted', () => {
    render(<LandingPage {...defaultProps} />);
    fireEvent.click(screen.getByTestId('hero-cta'));
    expect(defaultProps.onGetStarted).toHaveBeenCalledTimes(1);
  });

  it('view pricing button calls onViewPricing — SKIPPED (pricing removed for beta)', () => {
    // Pricing removed for beta launch
  });

  it('renders all 6 feature cards', () => {
    render(<LandingPage {...defaultProps} />);
    expect(screen.getByText('AI-Powered Translation')).toBeInTheDocument();
    expect(screen.getByText('Infrastructure as Code')).toBeInTheDocument();
    expect(screen.getByText('High-Level Design Docs')).toBeInTheDocument();
    expect(screen.getByText('Smart Analysis')).toBeInTheDocument();
    expect(screen.getByText('Enterprise Security')).toBeInTheDocument();
    expect(screen.getByText('Multi-Cloud Support')).toBeInTheDocument();
  });

  it('renders how-it-works section with 4 steps', () => {
    render(<LandingPage {...defaultProps} />);
    expect(screen.getByText('How it works')).toBeInTheDocument();
    expect(screen.getByText('Upload')).toBeInTheDocument();
    expect(screen.getByText('Analyze')).toBeInTheDocument();
    expect(screen.getByText('Translate')).toBeInTheDocument();
    expect(screen.getByText('Export')).toBeInTheDocument();
  });

  it('renders FAQ section with all 6 questions collapsed by default', () => {
    render(<LandingPage {...defaultProps} />);
    expect(screen.getByText('Frequently asked questions')).toBeInTheDocument();
    expect(screen.getByText('What cloud platforms do you support?')).toBeInTheDocument();
    expect(screen.getByText('How accurate are the translations?')).toBeInTheDocument();
    // Answers should not be visible until expanded
    expect(screen.queryByText(/currently translates architectures from AWS/)).not.toBeInTheDocument();
  });

  it('FAQ accordion toggles on click', () => {
    render(<LandingPage {...defaultProps} />);
    const question = screen.getByText('What cloud platforms do you support?');
    fireEvent.click(question);
    expect(screen.getByText(/currently translates architectures from AWS/)).toBeInTheDocument();
    fireEvent.click(question);
    expect(screen.queryByText(/currently translates architectures from AWS/)).not.toBeInTheDocument();
  });

  it('renders social proof section', () => {
    render(<LandingPage {...defaultProps} />);
    expect(screen.getByText(/Trusted by cloud architects/)).toBeInTheDocument();
    expect(screen.getByText('200+ Azure services mapped')).toBeInTheDocument();
  });

  it('bottom CTA calls onGetStarted', () => {
    render(<LandingPage {...defaultProps} />);
    fireEvent.click(screen.getByTestId('bottom-cta'));
    expect(defaultProps.onGetStarted).toHaveBeenCalledTimes(1);
  });

  it('renders trust badges (no credit card, free analyses, GDPR)', () => {
    render(<LandingPage {...defaultProps} />);
    expect(screen.getByText('Free during beta')).toBeInTheDocument()
    expect(screen.getByText('Unlimited analyses')).toBeInTheDocument()
    expect(screen.getByText('GDPR compliant')).toBeInTheDocument();
  });
});
