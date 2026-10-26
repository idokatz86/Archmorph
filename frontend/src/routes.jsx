import { lazy } from 'react';
import {
  Activity,
  Code,
  DollarSign,
  FileText,
  Layers,
  LayoutDashboard,
  LayoutTemplate,
  Rocket,
  Server,
  Upload,
} from 'lucide-react';
import {
  DEFAULT_ROUTE_ID,
  ROUTE_DEFINITIONS,
  isRouteEnabled,
} from './routeConfig';

export { DEFAULT_ROUTE_ID };

const COMPONENTS = {
  translator: lazy(() => import('./components/DiagramTranslator')),
  templates: lazy(() => import('./components/TemplateGallery')),
  dashboard: lazy(() => import('./components/DashboardPage')),
  services: lazy(() => import('./components/ServicesBrowser')),
  drift: lazy(() => import('./components/DriftDashboard')),
  roadmap: lazy(() => import('./components/Roadmap')),
  'api-docs': lazy(() => import('./components/ApiDocs')),
  collab: lazy(() => import('./components/CollabWorkspace')),
  replay: lazy(() => import('./components/MigrationReplay')),
};

const NAV_ICONS = {
  translator: Layers,
  templates: LayoutTemplate,
  dashboard: LayoutDashboard,
  services: Server,
  drift: Activity,
  roadmap: Rocket,
};

const COMMAND_ICONS = {
  'nav-workbench': Upload,
  'nav-iac': Code,
  'nav-hld': FileText,
  'nav-cost': DollarSign,
};

export const ROUTES = ROUTE_DEFINITIONS.map((route) => ({
  ...route,
  component: COMPONENTS[route.id],
  nav: route.nav ? { ...route.nav, icon: NAV_ICONS[route.id] } : undefined,
  commands: route.commands?.map((command) => ({
    ...command,
    icon: COMMAND_ICONS[command.id],
  })),
}));

const ROUTES_BY_ID = new Map(ROUTES.map((route) => [route.id, route]));

export function getRoute(routeId) {
  return ROUTES_BY_ID.get(routeId);
}

export function getEnabledRoute(routeId) {
  const route = getRoute(routeId);
  return route && isRouteEnabled(route) ? route : undefined;
}

export function getNavigationRoutes(group) {
  return ROUTES.filter(
    (route) => route.nav?.group === group && isRouteEnabled(route),
  );
}

export function getRouteCommands(setActiveTab) {
  return ROUTES.filter(isRouteEnabled).flatMap((route) =>
    (route.commands || []).map((command) => ({
      ...command,
      section: 'Navigation',
      action: () => setActiveTab(route.id),
    })),
  );
}
