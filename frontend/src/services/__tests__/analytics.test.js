import { beforeEach, describe, expect, it, vi } from 'vitest';

async function loadAnalytics() {
  vi.resetModules();
  return import('../analytics');
}

function postedEvents() {
  return fetch.mock.calls.map(([, options]) => JSON.parse(options.body));
}

describe('analytics service', () => {
  beforeEach(() => {
    fetch.mockClear();
    localStorage.clear();
    sessionStorage.clear();
    vi.useRealTimers();
  });

  it('tracks page views as generic and funnel events', async () => {
    const { trackPageView } = await loadAnalytics();

    trackPageView('translator');

    expect(postedEvents().map((payload) => payload.event)).toEqual([
      'page_view',
      'funnel:page_view',
    ]);
    expect(postedEvents()[1].properties).toMatchObject({
      tab: 'translator',
      funnel_step: 'page_view',
      funnel_index: 0,
    });
  });

  it('tracks returning users once per day', async () => {
    localStorage.setItem('archmorph-last-seen-date', '2026-04-27');
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-28T09:00:00Z'));
    const { trackPageView } = await loadAnalytics();

    trackPageView('playground');
    trackPageView('services');

    const events = postedEvents().map((payload) => payload.event);
    expect(events.filter((event) => event === 'funnel:returning_user')).toHaveLength(1);
    expect(localStorage.getItem('archmorph-last-seen-date')).toBe('2026-04-28');
  });
});