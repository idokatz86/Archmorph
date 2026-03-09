import {
  Server, Database, Globe, Shield, BarChart3, Zap, Box, Code,
  Activity, Settings, Layers, CloudCog,
} from 'lucide-react';

export const API_BASE = import.meta.env.VITE_API_BASE || '/api';

export const APP_VERSION = '3.8.0';

export const CATEGORY_ICONS = {
  Compute: Server, Storage: Database, Networking: Globe, Security: Shield,
  Analytics: BarChart3, AI: Zap, Containers: Box, Database: Database,
  Integration: Layers, 'Developer Tools': Code, IoT: Activity,
  Management: Settings, default: CloudCog,
};

export function getCategoryIcon(category) {
  return CATEGORY_ICONS[category] || CATEGORY_ICONS.default;
}
