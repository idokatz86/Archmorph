import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import PricingPage from '../PricingPage';

const MOCK_TIERS = [
  {
    id: 'free',
    name: 'Free',
    price_monthly: 0,
    price_annual: 0,
    highlighted: false,
    cta: 'Get Started',
    features: ['5 analyses/month', 'Basic export'],
  },
  {
    id: 'pro',
    name: 'Pro',
    price_monthly: 29,
    price_annual: 290,
    highlighted: true,
    cta: 'Start Free Trial',
    features: ['Unlimited analyses', 'All export formats', 'Priority support'],
  },
  {
    id: 'enterprise',
    name: 'Enterprise',
    price_monthly: 99,
    price_annual: 990,
    highlighted: false,
    cta: 'Contact Sales',
    features: ['Custom SLA', 'Dedicated support', 'SSO'],
  },
];

describe('PricingPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetch.mockResolvedValue({
      json: () => Promise.resolve({ tiers: MOCK_TIERS }),
    });
  });

  it('renders the pricing page container', async () => {
    render(<PricingPage />);
    await waitFor(() => {
      expect(screen.getByTestId('pricing-page')).toBeInTheDocument();
    });
  });

  it('shows loading state initially', () => {
    fetch.mockReturnValue(new Promise(() => {})); // never resolves
    render(<PricingPage />);
    expect(screen.getByText(/Loading pricing/)).toBeInTheDocument();
  });

  it('renders headline text', async () => {
    render(<PricingPage />);
    await waitFor(() => {
      expect(screen.getByText('Simple, transparent pricing')).toBeInTheDocument();
    });
  });

  it('renders all three tier cards', async () => {
    render(<PricingPage />);
    await waitFor(() => {
      expect(screen.getByTestId('tier-free')).toBeInTheDocument();
      expect(screen.getByTestId('tier-pro')).toBeInTheDocument();
      expect(screen.getByTestId('tier-enterprise')).toBeInTheDocument();
    });
  });

  it('shows "Most Popular" badge on highlighted tier', async () => {
    render(<PricingPage />);
    await waitFor(() => {
      expect(screen.getByText('Most Popular')).toBeInTheDocument();
    });
  });

  it('shows "Free" for zero-price tier', async () => {
    render(<PricingPage />);
    await waitFor(() => {
      const freeElements = screen.getAllByText('Free');
      expect(freeElements.length).toBeGreaterThanOrEqual(2); // tier name + price display
    });
  });

  it('renders features for each tier', async () => {
    render(<PricingPage />);
    await waitFor(() => {
      expect(screen.getByText('5 analyses/month')).toBeInTheDocument();
      expect(screen.getByText('Unlimited analyses')).toBeInTheDocument();
      expect(screen.getByText('Custom SLA')).toBeInTheDocument();
    });
  });

  it('shows billing toggle', async () => {
    render(<PricingPage />);
    await waitFor(() => {
      expect(screen.getByTestId('billing-toggle')).toBeInTheDocument();
      expect(screen.getByText('Monthly')).toBeInTheDocument();
      expect(screen.getByText(/Annual/)).toBeInTheDocument();
    });
  });

  it('toggles between monthly and annual pricing', async () => {
    render(<PricingPage />);
    await waitFor(() => {
      expect(screen.getByText('$29')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('billing-toggle'));
    await waitFor(() => {
      expect(screen.getByText('$290')).toBeInTheDocument();
    });
  });

  it('renders back button when onBack is provided', async () => {
    const onBack = vi.fn();
    render(<PricingPage onBack={onBack} />);
    await waitFor(() => {
      expect(screen.getByText('Back')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText('Back'));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('does not render back button when onBack is not provided', async () => {
    render(<PricingPage />);
    await waitFor(() => {
      expect(screen.getByTestId('pricing-page')).toBeInTheDocument();
    });
    expect(screen.queryByText('Back')).not.toBeInTheDocument();
  });

  it('renders money-back guarantee text', async () => {
    render(<PricingPage />);
    await waitFor(() => {
      expect(screen.getByText(/14-day money-back guarantee/)).toBeInTheDocument();
    });
  });
});
