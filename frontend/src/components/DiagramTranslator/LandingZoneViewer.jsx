import React, { useEffect, useMemo, useState } from 'react';
import DOMPurify from 'dompurify';
import { Check, Layers, Server } from 'lucide-react';
import { Card } from '../ui';

function directText(element, tagName) {
  return [...(element?.children || [])]
    .find(child => child.tagName?.toLowerCase() === tagName)
    ?.textContent
    ?.trim() || '';
}

function parseLandingZoneSvg(svgContent) {
  if (!svgContent || typeof window === 'undefined' || !window.DOMParser) {
    return { title: 'Landing Zone SVG', description: '', services: [], tiers: [] };
  }

  const doc = new window.DOMParser().parseFromString(svgContent, 'image/svg+xml');
  const parserError = doc.querySelector('parsererror');
  if (parserError) {
    return { title: 'Landing Zone SVG', description: '', services: [], tiers: [] };
  }

  const root = doc.querySelector('svg');
  const title = directText(root, 'title') || 'Landing Zone SVG';
  const description = directText(root, 'desc');
  const services = [...doc.querySelectorAll('g')]
    .map((group) => {
      const serviceTitle = directText(group, 'title');
      if (!serviceTitle) return null;
      if (group.hasAttribute('data-tier') && /\btier\b/i.test(serviceTitle) && group.querySelector('g')) {
        return null;
      }
      const serviceDescription = directText(group, 'desc');
      const tier = group.closest('[data-tier]')?.getAttribute('data-tier')
        || group.getAttribute('data-tier')
        || serviceDescription.match(/tier[:\s-]+([^.;]+)/i)?.[1]?.trim()
        || '';
      return { name: serviceTitle, description: serviceDescription, tier };
    })
    .filter(Boolean);
  const tierNames = [...new Set([
    ...[...doc.querySelectorAll('[data-tier]')].map(group => group.getAttribute('data-tier')),
    ...services.map(service => service.tier),
  ].filter(Boolean))];

  return { title, description, services, tiers: tierNames };
}

function variantLabel(variant) {
  return variant === 'dr' ? 'DR' : 'Target';
}

export default function LandingZoneViewer({ svgContent, variant = 'primary', filename }) {
  const [announcement, setAnnouncement] = useState('');
  const metadata = useMemo(() => parseLandingZoneSvg(svgContent), [svgContent]);
  const sanitizedSvg = useMemo(() => DOMPurify.sanitize(svgContent || '', {
    USE_PROFILES: { svg: true, svgFilters: true },
    ADD_ATTR: ['role', 'aria-labelledby', 'aria-describedby', 'data-tier'],
  }), [svgContent]);
  const label = variantLabel(variant);

  useEffect(() => {
    if (!svgContent) return;
    const serviceText = metadata.services.length === 1 ? '1 service' : `${metadata.services.length} services`;
    const tierText = metadata.tiers.length > 0 ? ` across ${metadata.tiers.length} tiers` : '';
    setAnnouncement(`${label} landing zone SVG rendered with ${serviceText}${tierText}.`);
  }, [label, metadata.services.length, metadata.tiers.length, svgContent]);

  const announceTier = (tier) => {
    const count = metadata.services.filter(service => service.tier === tier).length;
    setAnnouncement(`${tier} tier selected with ${count} service${count === 1 ? '' : 's'}.`);
  };

  const announceService = (service) => {
    const tierText = service.tier ? `${service.tier} tier: ` : '';
    const descriptionText = service.description ? ` ${service.description}` : '';
    setAnnouncement(`${tierText}${service.name}.${descriptionText}`);
  };

  if (!svgContent) return null;

  return (
    <Card className="mt-4 p-4 border-cta/30 bg-cta/5">
      <div className="flex flex-col gap-3" data-testid="landing-zone-viewer">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
              <Layers className="w-4 h-4 text-cta" aria-hidden="true" />
              {label} Landing Zone Preview
            </h3>
            <p className="text-xs text-text-muted mt-1">
              {metadata.title}{filename ? ` · ${filename}` : ''}
            </p>
          </div>
          <div className="inline-flex items-center gap-1 text-xs text-cta" aria-hidden="true">
            <Check className="w-3.5 h-3.5" />
            Ready
          </div>
        </div>

        <div className="sr-only" role="status" aria-live="polite" data-testid="landing-zone-live-region">
          {announcement}
        </div>

        {metadata.description && <p className="text-xs text-text-secondary">{metadata.description}</p>}

        {metadata.tiers.length > 0 && (
          <div className="flex flex-wrap gap-2" aria-label="Landing zone tiers">
            {metadata.tiers.map(tier => (
              <button
                key={tier}
                type="button"
                onClick={() => announceTier(tier)}
                onFocus={() => announceTier(tier)}
                className="px-2 py-1 rounded-md border border-border bg-secondary text-xs text-text-primary hover:border-cta/60 focus:outline-none focus:ring-2 focus:ring-cta/50"
              >
                {tier}
              </button>
            ))}
          </div>
        )}

        {metadata.services.length > 0 && (
          <div className="max-h-28 overflow-y-auto rounded-lg border border-border bg-primary/60 p-2" aria-label="Landing zone services">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
              {metadata.services.slice(0, 12).map((service) => (
                <button
                  key={`${service.tier}-${service.name}`}
                  type="button"
                  onClick={() => announceService(service)}
                  onFocus={() => announceService(service)}
                  className="flex items-center gap-2 text-left px-2 py-1.5 rounded-md text-xs text-text-secondary hover:bg-secondary focus:outline-none focus:ring-2 focus:ring-cta/50"
                >
                  <Server className="w-3.5 h-3.5 text-cta shrink-0" aria-hidden="true" />
                  <span className="truncate">{service.name}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div
          data-testid="landing-zone-svg-preview"
          tabIndex={0}
          aria-label={`${label} landing zone SVG preview`}
          className="max-h-72 overflow-auto rounded-lg border border-border bg-surface p-2 [&_svg]:max-w-full [&_svg]:h-auto"
          dangerouslySetInnerHTML={{ __html: sanitizedSvg }}
        />
      </div>
    </Card>
  );
}