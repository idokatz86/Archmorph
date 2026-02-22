import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import CookieBanner from '../CookieBanner';

describe('CookieBanner', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows banner after delay when no consent stored', () => {
    render(<CookieBanner />);
    expect(screen.queryByTestId('cookie-banner')).not.toBeInTheDocument();
    act(() => vi.advanceTimersByTime(1500));
    expect(screen.getByTestId('cookie-banner')).toBeInTheDocument();
  });

  it('does not show banner when consent is already stored', () => {
    localStorage.setItem('archmorph_cookie_consent', JSON.stringify({
      necessary: true, analytics: false, timestamp: new Date().toISOString(),
    }));
    render(<CookieBanner />);
    act(() => vi.advanceTimersByTime(2000));
    expect(screen.queryByTestId('cookie-banner')).not.toBeInTheDocument();
  });

  it('accept all saves full consent and hides banner', () => {
    render(<CookieBanner />);
    act(() => vi.advanceTimersByTime(1500));
    fireEvent.click(screen.getByText('Accept all'));
    expect(screen.queryByTestId('cookie-banner')).not.toBeInTheDocument();
    const saved = JSON.parse(localStorage.getItem('archmorph_cookie_consent'));
    expect(saved.analytics).toBe(true);
    expect(saved.marketing).toBe(true);
  });

  it('necessary only saves minimal consent', () => {
    render(<CookieBanner />);
    act(() => vi.advanceTimersByTime(1500));
    fireEvent.click(screen.getByText('Necessary only'));
    const saved = JSON.parse(localStorage.getItem('archmorph_cookie_consent'));
    expect(saved.necessary).toBe(true);
    expect(saved.analytics).toBe(false);
  });

  it('dismiss hides banner', () => {
    render(<CookieBanner />);
    act(() => vi.advanceTimersByTime(1500));
    fireEvent.click(screen.getByLabelText('Dismiss cookie banner'));
    expect(screen.queryByTestId('cookie-banner')).not.toBeInTheDocument();
  });

  it('customize toggle shows detail checkboxes', () => {
    render(<CookieBanner />);
    act(() => vi.advanceTimersByTime(1500));
    fireEvent.click(screen.getByText('Customize'));
    expect(screen.getByText('Analytics')).toBeInTheDocument();
    expect(screen.getByText('Functional')).toBeInTheDocument();
    expect(screen.getByText('Marketing')).toBeInTheDocument();
  });

  it('shows cookie policy link', () => {
    render(<CookieBanner />);
    act(() => vi.advanceTimersByTime(1500));
    expect(screen.getByText('Cookie Policy')).toBeInTheDocument();
  });
});
