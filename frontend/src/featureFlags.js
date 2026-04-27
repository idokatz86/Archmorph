function envFlag(name, defaultValue = false) {
  const value = import.meta.env[`VITE_FEATURE_FLAG_${name}`];
  if (value === undefined) return defaultValue;
  return ['true', '1', 'yes', 'on'].includes(String(value).toLowerCase());
}

export const FEATURE_FLAGS = {
  deployEngine: envFlag('DEPLOY_ENGINE', false),
  livingArchitectureDrift: envFlag('LIVING_ARCHITECTURE_DRIFT', false),
  liveCloudScanner: envFlag('LIVE_CLOUD_SCANNER', false),
  enterpriseSsoScim: envFlag('ENTERPRISE_SSO_SCIM', false),
  stripeBilling: envFlag('STRIPE_BILLING', false),
};

export function isFeatureEnabled(name) {
  return Boolean(FEATURE_FLAGS[name]);
}