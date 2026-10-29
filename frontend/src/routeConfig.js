import { isFeatureEnabled } from './featureFlags';

export const DEFAULT_ROUTE_ID = 'translator';

export const ROUTE_DEFINITIONS = [
  {
    id: 'translator',
    hash: '',
    nav: { label: 'Workbench', group: 'primary' },
    commands: [
      { id: 'nav-workbench', label: 'Go to Workbench', shortcut: '1' },
      { id: 'nav-iac', label: 'Go to IaC', shortcut: '3' },
      { id: 'nav-hld', label: 'Go to HLD', shortcut: '4' },
      { id: 'nav-cost', label: 'Go to Cost', shortcut: '5' },
    ],
  },
  {
    id: 'templates',
    hash: '#templates',
    nav: { label: 'Starters', group: 'primary' },
  },
  {
    id: 'dashboard',
    hash: '#dashboard',
    nav: { label: 'History', group: 'primary' },
  },
  {
    id: 'services',
    hash: '#services',
    nav: { label: 'Reference', group: 'primary' },
  },
  {
    id: 'drift',
    hash: '#drift',
    nav: { label: 'Drift', group: 'more' },
    feature: 'livingArchitectureDrift',
  },
  {
    id: 'roadmap',
    hash: '#roadmap',
    nav: { label: 'Roadmap', group: 'more' },
  },
  {
    id: 'api-docs',
    hash: '#api-docs',
  },
  {
    id: 'collab',
    hash: '#collab',
  },
  {
    id: 'replay',
    hash: '#replay',
  },
];

const ROUTES_BY_ID = new Map(
  ROUTE_DEFINITIONS.map((route) => [route.id, route]),
);
const ROUTES_BY_HASH = new Map(
  ROUTE_DEFINITIONS.map((route) => [route.hash, route]),
);

export function isRouteEnabled(route) {
  return !route.feature || isFeatureEnabled(route.feature);
}

export function getRouteDefinition(routeId) {
  return ROUTES_BY_ID.get(routeId);
}

export function getEnabledRouteDefinition(routeId) {
  const route = getRouteDefinition(routeId);
  return route && isRouteEnabled(route) ? route : undefined;
}

export function routeIdFromHash(hash) {
  const normalizedHash = hash === '#translator' ? '' : hash.replace('#/', '#');
  const route = ROUTES_BY_HASH.get(normalizedHash);
  return route && isRouteEnabled(route) ? route.id : DEFAULT_ROUTE_ID;
}

export function hashFromRouteId(routeId) {
  return getEnabledRouteDefinition(routeId)?.hash ?? '';
}
