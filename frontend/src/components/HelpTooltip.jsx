import React, { useState } from 'react';
import { HelpCircle, X, ExternalLink } from 'lucide-react';

/**
 * Contextual help tooltip for in-product guidance (#367).
 * Shows a help icon that reveals an explanation panel on click.
 */
export function HelpTooltip({ title, content, learnMoreUrl, className = '' }) {
  const [open, setOpen] = useState(false);

  return (
    <span className={`relative inline-flex items-center ${className}`}>
      <button
        onClick={() => setOpen(!open)}
        className="p-0.5 rounded-full hover:bg-secondary transition-colors cursor-pointer"
        aria-label={`Help: ${title}`}
        aria-expanded={open}
      >
        <HelpCircle className="w-3.5 h-3.5 text-text-muted hover:text-info" />
      </button>
      {open && (
        <div className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 w-72 bg-surface border border-border rounded-xl shadow-lg p-3 animate-in fade-in slide-in-from-bottom-1">
          <div className="flex items-start justify-between gap-2 mb-1.5">
            <p className="text-xs font-semibold text-text-primary">{title}</p>
            <button onClick={() => setOpen(false)} className="p-0.5 hover:bg-secondary rounded cursor-pointer" aria-label="Close">
              <X className="w-3 h-3 text-text-muted" />
            </button>
          </div>
          <p className="text-[11px] text-text-secondary leading-relaxed">{content}</p>
          {learnMoreUrl && (
            <a
              href={learnMoreUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[11px] text-cta hover:underline mt-2"
            >
              <ExternalLink className="w-3 h-3" /> Learn more
            </a>
          )}
        </div>
      )}
    </span>
  );
}

/**
 * Predefined help content for common Archmorph concepts.
 * Used across AnalysisResults, PricingTab, and HLDPanel.
 */
export const HELP_CONTENT = {
  confidence: {
    title: 'Understanding Confidence Scores',
    content: 'Confidence scores (0-100%) indicate how well a source cloud service maps to its Azure equivalent. High confidence (≥85%) means a near-direct replacement exists. Medium (60-84%) means some adaptation is needed. Low (<60%) means manual review is recommended. Click any score to see the detailed breakdown.',
    learnMoreUrl: 'https://learn.microsoft.com/en-us/azure/architecture/guide/technology-choices/compute-decision-tree',
  },
  hld: {
    title: 'What is an HLD?',
    content: 'A High-Level Design (HLD) document describes your target Azure architecture at a strategic level. It covers service selection rationale, networking topology, security posture, cost model, migration plan, and WAF (Well-Architected Framework) alignment. Share it with stakeholders for approval before implementation.',
    learnMoreUrl: 'https://learn.microsoft.com/en-us/azure/well-architected/',
  },
  pricing: {
    title: 'How Pricing is Estimated',
    content: 'Costs are estimated using the Azure Retail Prices API based on your selected region and detected services. Estimates show a low-to-high range reflecting different SKU tiers and usage patterns. Actual costs depend on configuration, reserved capacity, and usage. Use the Azure Pricing Calculator for exact quotes.',
    learnMoreUrl: 'https://azure.microsoft.com/en-us/pricing/calculator/',
  },
  iac: {
    title: 'Infrastructure as Code',
    content: 'Generated IaC code (Terraform, Bicep, or CloudFormation) provisions your Azure architecture automatically. The code includes resource definitions, networking, and security configurations. Review and customize before applying to your Azure subscription.',
    learnMoreUrl: 'https://learn.microsoft.com/en-us/azure/developer/terraform/overview',
  },
  migration_effort: {
    title: 'Migration Effort Levels',
    content: 'Low effort: Near drop-in replacement with minimal code changes. Medium effort: Some API/SDK changes, configuration adaptation, and testing needed. High effort: Significant rearchitecture, data migration, or feature redesign required.',
  },
  strengths: {
    title: 'Mapping Strengths',
    content: 'Strengths highlight why the Azure service is a good match for your source service. These include feature parity, managed service benefits, cost advantages, and native integrations.',
  },
  limitations: {
    title: 'Known Limitations',
    content: 'Limitations document known gaps or restrictions when migrating to the Azure equivalent. Each limitation includes a severity level and a link to Azure documentation for more details.',
  },
};

export default HelpTooltip;
