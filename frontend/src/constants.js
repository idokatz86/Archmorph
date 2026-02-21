import {
  Server, Database, Globe, Shield, BarChart3, Zap, Box, Code,
  Activity, Settings, Layers, CloudCog,
} from 'lucide-react';

export const API_BASE = import.meta.env.VITE_API_BASE || 'https://archmorph-api.nicesea-1430d1f7.westeurope.azurecontainerapps.io/api';

export const APP_VERSION = '2.11.1';

export const CATEGORY_ICONS = {
  Compute: Server, Storage: Database, Networking: Globe, Security: Shield,
  Analytics: BarChart3, AI: Zap, Containers: Box, Database: Database,
  Integration: Layers, 'Developer Tools': Code, IoT: Activity,
  Management: Settings, default: CloudCog,
};

export function getCategoryIcon(category) {
  return CATEGORY_ICONS[category] || CATEGORY_ICONS.default;
}
