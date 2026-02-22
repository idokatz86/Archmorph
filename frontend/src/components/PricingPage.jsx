import React, { useState, useEffect } from 'react';
import { Check, Zap, Building2, Sparkles, ArrowLeft, Loader2 } from 'lucide-react';
import { API_BASE } from '../constants';

const TIER_ICONS = { free: Sparkles, pro: Zap, enterprise: Building2 };
const TIER_COLORS = {
  free: 'text-text-secondary',
  pro: 'text-cta',
  enterprise: 'text-amber-400',
};

export default function PricingPage({ onBack }) {
  const [tiers, setTiers] = useState(null);
  const [annual, setAnnual] = useState(false);
  const [loading, setLoading] = useState(true);
  const [checkoutLoading, setCheckoutLoading] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/billing/pricing`, { signal: controller.signal })
      .then(r => r.json())
      .then(data => { setTiers(data.tiers); setLoading(false); })
      .catch(() => setLoading(false));
    return () => controller.abort();
  }, []);

  const handleCheckout = async (tierId) => {
    if (tierId === 'free') return;
    setCheckoutLoading(tierId);
    try {
      const res = await fetch(`${API_BASE}/billing/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tier: tierId, annual }),
      });
      const data = await res.json();
      if (data.url) {
        window.open(data.url, '_blank', 'noopener');
      }
    } catch {
      // Silently fail — user can retry
    } finally {
      setCheckoutLoading(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="w-6 h-6 text-cta animate-spin" />
        <span className="ml-2 text-sm text-text-muted">Loading pricing…</span>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto" data-testid="pricing-page">
      {onBack && (
        <button
          onClick={onBack}
          className="flex items-center gap-1.5 text-sm text-text-secondary hover:text-cta transition-colors mb-6"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>
      )}

      <div className="text-center mb-10">
        <h1 className="text-3xl font-bold text-text-primary mb-3">
          Simple, transparent pricing
        </h1>
        <p className="text-text-muted max-w-lg mx-auto">
          Start free, upgrade when you need more power. All plans include core
          architecture translation features.
        </p>

        {/* Billing toggle */}
        <div className="flex items-center justify-center gap-3 mt-6">
          <span className={`text-sm ${!annual ? 'text-text-primary font-medium' : 'text-text-muted'}`}>Monthly</span>
          <button
            onClick={() => setAnnual(!annual)}
            className={`relative w-11 h-6 rounded-full transition-colors ${annual ? 'bg-cta' : 'bg-border'}`}
            aria-label="Toggle annual billing"
            data-testid="billing-toggle"
          >
            <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${annual ? 'translate-x-5' : ''}`} />
          </button>
          <span className={`text-sm ${annual ? 'text-text-primary font-medium' : 'text-text-muted'}`}>
            Annual <span className="text-cta text-xs font-medium">Save 17%</span>
          </span>
        </div>
      </div>

      <div className="grid md:grid-cols-3 gap-6">
        {(tiers || []).map(tier => {
          const Icon = TIER_ICONS[tier.id] || Sparkles;
          const colorClass = TIER_COLORS[tier.id] || 'text-text-secondary';
          const isHighlighted = tier.highlighted;
          const price = annual ? tier.price_annual : tier.price_monthly;
          const period = annual ? '/year' : '/month';

          return (
            <div
              key={tier.id}
              className={`relative rounded-2xl p-6 border transition-all ${
                isHighlighted
                  ? 'border-cta bg-cta/5 shadow-lg shadow-cta/10 scale-[1.02]'
                  : 'border-border bg-secondary/20 hover:border-border/80'
              }`}
              data-testid={`tier-${tier.id}`}
            >
              {isHighlighted && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 bg-cta text-white text-xs font-bold rounded-full">
                  Most Popular
                </div>
              )}

              <div className="flex items-center gap-2 mb-4">
                <Icon className={`w-5 h-5 ${colorClass}`} />
                <h3 className="text-lg font-bold text-text-primary">{tier.name}</h3>
              </div>

              <div className="mb-6">
                {price === 0 ? (
                  <div className="text-3xl font-bold text-text-primary">Free</div>
                ) : (
                  <div className="flex items-baseline gap-1">
                    <span className="text-3xl font-bold text-text-primary">${price}</span>
                    <span className="text-sm text-text-muted">{period}</span>
                  </div>
                )}
              </div>

              <ul className="space-y-2.5 mb-6">
                {tier.features.map((feature, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-text-secondary">
                    <Check className="w-4 h-4 text-cta shrink-0 mt-0.5" />
                    {feature}
                  </li>
                ))}
              </ul>

              <button
                onClick={() => handleCheckout(tier.id)}
                disabled={checkoutLoading === tier.id}
                className={`w-full py-2.5 rounded-xl text-sm font-medium transition-all ${
                  isHighlighted
                    ? 'bg-cta text-white hover:bg-cta/90'
                    : tier.id === 'enterprise'
                    ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20 hover:bg-amber-500/20'
                    : 'bg-secondary text-text-primary border border-border hover:bg-secondary/80'
                }`}
                data-testid={`checkout-${tier.id}`}
              >
                {checkoutLoading === tier.id ? (
                  <Loader2 className="w-4 h-4 animate-spin mx-auto" />
                ) : (
                  tier.cta
                )}
              </button>
            </div>
          );
        })}
      </div>

      <div className="mt-10 text-center">
        <p className="text-xs text-text-muted">
          All prices in USD. Enterprise plan includes custom SLA and dedicated support.
          <br />
          14-day money-back guarantee on all paid plans.
        </p>
      </div>
    </div>
  );
}
