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
});