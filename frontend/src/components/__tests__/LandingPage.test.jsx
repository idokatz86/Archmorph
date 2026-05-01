import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import LandingPage from '../LandingPage';

describe('LandingPage', () => {
  const defaultProps = {
    onGetStarted: vi.fn(),
    onTrySample: vi.fn(),
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
    expect(screen.getByText(/Translate Between Any/)).toBeInTheDocument();
    expect(screen.getByText('Cloud Providers')).toBeInTheDocument();
  });

  it('hero CTA calls onGetStarted', () => {
    render(<LandingPage {...defaultProps} />);
    fireEvent.click(screen.getByTestId('hero-cta'));
    expect(defaultProps.onGetStarted).toHaveBeenCalledTimes(1);
  });

  it('renders all 9 feature cards', () => {
    render(<LandingPage {...defaultProps} />);
    expect(screen.getByText('AI-Powered Translation')).toBeInTheDocument();
    expect(screen.getByText('Terraform, Bicep & CloudFormation')).toBeInTheDocument();
    expect(screen.getByText('HLD Documents & Runbooks')).toBeInTheDocument();
    expect(screen.getByText('Architecture Versioning')).toBeInTheDocument();
    expect(screen.getByText('Cost Estimates & Optimization')).toBeInTheDocument();
    expect(screen.getByText('Living Architecture')).toBeInTheDocument();
    expect(screen.getByText('Enterprise Security')).toBeInTheDocument();
    expect(screen.getByText('AI Assistant & Community')).toBeInTheDocument();
    expect(screen.getByText('Multi-Cloud, Any Direction')).toBeInTheDocument();
  });

  it('renders stats bar with key metrics', () => {
    render(<LandingPage {...defaultProps} />);
    expect(screen.getByText('405+')).toBeInTheDocument();
    expect(screen.getByText('120+')).toBeInTheDocument();
    expect(screen.getByText('100%')).toBeInTheDocument();
  });

  it('routes sample CTA via the onTrySample callback', () => {
    render(<LandingPage {...defaultProps} />);
    fireEvent.click(screen.getByText('Try a sample diagram'));
    expect(defaultProps.onTrySample).toHaveBeenCalledTimes(1);
  });

  it('renders how-it-works section with 4 steps', () => {
    render(<LandingPage {...defaultProps} />);
    expect(screen.getByText('How it works')).toBeInTheDocument();
    expect(screen.getByText('Upload')).toBeInTheDocument();
    expect(screen.getByText('Analyze')).toBeInTheDocument();
    expect(screen.getByText('Refine')).toBeInTheDocument();
    expect(screen.getByText('Export')).toBeInTheDocument();
  });

  it('renders FAQ section with all 6 questions collapsed by default', () => {
    render(<LandingPage {...defaultProps} />);
    expect(screen.getByText('Frequently asked questions')).toBeInTheDocument();
    expect(screen.getByText('What cloud platforms do you support?')).toBeInTheDocument();
    expect(screen.getByText('How accurate are the translations?')).toBeInTheDocument();
    expect(screen.getByText('Is Archmorph really free?')).toBeInTheDocument();
    // Answers should not be visible until expanded
    expect(screen.queryByText(/translates between AWS/)).not.toBeInTheDocument();
  });

  it('FAQ accordion toggles on click', () => {
    render(<LandingPage {...defaultProps} />);
    const question = screen.getByText('What cloud platforms do you support?');
    fireEvent.click(question);
    expect(screen.getByText(/translates between AWS/)).toBeInTheDocument();
    fireEvent.click(question);
    expect(screen.queryByText(/translates between AWS/)).not.toBeInTheDocument();
  });

  it('bottom CTA calls onGetStarted', () => {
    render(<LandingPage {...defaultProps} />);
    fireEvent.click(screen.getByTestId('bottom-cta'));
    expect(defaultProps.onGetStarted).toHaveBeenCalledTimes(1);
  });

  it('renders trust badges (free access, no account, GDPR)', () => {
    render(<LandingPage {...defaultProps} />);
    expect(screen.getByText('100% free')).toBeInTheDocument();
    expect(screen.getByText('No account required')).toBeInTheDocument();
    expect(screen.getByText('GDPR compliant')).toBeInTheDocument();
  });
});
