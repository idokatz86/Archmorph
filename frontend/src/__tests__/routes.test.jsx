import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FEATURE_FLAGS } from '../featureFlags';
import useAppStore from '../stores/useAppStore';
import {
  DEFAULT_ROUTE_ID,
  ROUTE_DEFINITIONS,
  hashFromRouteId,
  routeIdFromHash,
} from '../routeConfig';
import {
  ROUTES,
  getEnabledRoute,
  getNavigationRoutes,
  getRouteCommands,
} from '../routes';

describe('route registry', () => {
  const originalDriftFlag = FEATURE_FLAGS.livingArchitectureDrift;

  beforeEach(() => {
    FEATURE_FLAGS.livingArchitectureDrift = false;
    window.history.replaceState(null, '', '/');
    useAppStore.setState({ activeTab: DEFAULT_ROUTE_ID });
  });

  afterEach(() => {
    FEATURE_FLAGS.livingArchitectureDrift = originalDriftFlag;
  });

  it('owns a unique component and preserves the existing hash for every route', () => {
    const expectedHashes = {
      dashboard: '#dashboard',
      translator: '',
      services: '#services',
      templates: '#templates',
      roadmap: '#roadmap',
      drift: '#drift',
      'api-docs': '#api-docs',
      collab: '#collab',
      replay: '#replay',
    };

    expect(Object.fromEntries(ROUTES.map(({ id, hash }) => [id, hash]))).toEqual(expectedHashes);
    expect(ROUTES.map(({ id }) => id)).toEqual(
      ROUTE_DEFINITIONS.map(({ id }) => id),
    );
    expect(
      ROUTE_DEFINITIONS.every((route) => !Object.hasOwn(route, 'component')),
    ).toBe(true);
    expect(new Set(ROUTES.map(({ id }) => id)).size).toBe(ROUTES.length);
    expect(ROUTES.every(({ component }) => component)).toBe(true);
    expect(routeIdFromHash('')).toBe(DEFAULT_ROUTE_ID);
    expect(routeIdFromHash('#translator')).toBe(DEFAULT_ROUTE_ID);
    expect(routeIdFromHash('#/services')).toBe('services');
    expect(hashFromRouteId('translator')).toBe('');
    expect(hashFromRouteId('services')).toBe('#services');
  });

  it('keeps Zustand navigation synchronized with the existing hash URLs', () => {
    useAppStore.getState().setActiveTab('services');
    expect(useAppStore.getState().activeTab).toBe('services');
    expect(window.location.hash).toBe('#services');

    useAppStore.getState().setActiveTab('translator');
    expect(useAppStore.getState().activeTab).toBe('translator');
    expect(window.location.hash).toBe('');
  });

  it('derives navigation labels and command-palette targets from route metadata', () => {
    expect(getNavigationRoutes('primary').map(({ id, nav }) => [id, nav.label])).toEqual([
      ['translator', 'Workbench'],
      ['templates', 'Starters'],
      ['dashboard', 'History'],
      ['services', 'Reference'],
    ]);
    expect(getNavigationRoutes('more').map(({ id, nav }) => [id, nav.label])).toEqual([
      ['roadmap', 'Roadmap'],
    ]);

    const setActiveTab = vi.fn();
    const commands = getRouteCommands(setActiveTab);
    expect(commands.map(({ id, label }) => [id, label])).toEqual([
      ['nav-workbench', 'Go to Workbench'],
      ['nav-iac', 'Go to IaC'],
      ['nav-hld', 'Go to HLD'],
      ['nav-cost', 'Go to Cost'],
    ]);

    commands[0].action();
    expect(setActiveTab).toHaveBeenCalledWith('translator');
  });

  it('applies feature gates consistently to URLs, rendering, and navigation', () => {
    expect(getEnabledRoute('drift')).toBeUndefined();
    expect(routeIdFromHash('#drift')).toBe(DEFAULT_ROUTE_ID);
    expect(getNavigationRoutes('more').map(({ id }) => id)).not.toContain('drift');

    useAppStore.getState().setActiveTab('drift');
    expect(useAppStore.getState().activeTab).toBe(DEFAULT_ROUTE_ID);
    expect(window.location.hash).toBe('');

    FEATURE_FLAGS.livingArchitectureDrift = true;

    expect(getEnabledRoute('drift')?.id).toBe('drift');
    expect(routeIdFromHash('#drift')).toBe('drift');
    expect(getNavigationRoutes('more').map(({ id }) => id)).toContain('drift');
  });
});
