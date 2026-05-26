/**
 * ArchitectReviewQueue — Issue #1137
 *
 * Displays the architect review queue populated from analysis results.
 * Buckets: assumptions | low_confidence | architecture_gap | cost_warning | security_concern
 * Disposition actions: Accept | Edit | Mark as risk | Exclude
 *
 * Fully keyboard-accessible (tab order, Enter/Space on all interactive elements).
 */

import React, { useState } from 'react';
import {
  AlertTriangle, CheckCircle2, XCircle, Edit3, ShieldAlert,
  ChevronDown, ChevronUp, Lock, AlertCircle,
  HelpCircle, DollarSign, Shield, Zap,
} from 'lucide-react';
import { Button, Card, Badge } from '../ui';
import { toRenderableString } from '../../utils/toRenderableString';

// ── Bucket metadata ───────────────────────────────────────────────────────────
const BUCKET_META = {
  assumptions: {
    label: 'Assumptions',
    icon: HelpCircle,
    colorClass: 'text-info',
    bgClass: 'bg-info/5 border-info/20',
    dotClass: 'bg-info',
  },
  low_confidence: {
    label: 'Low-Confidence Mappings',
    icon: AlertCircle,
    colorClass: 'text-warning',
    bgClass: 'bg-warning/5 border-warning/20',
    dotClass: 'bg-warning',
  },
  architecture_gap: {
    label: 'Architecture Gaps',
    icon: Zap,
    colorClass: 'text-danger',
    bgClass: 'bg-danger/5 border-danger/20',
    dotClass: 'bg-danger',
  },
  cost_warning: {
    label: 'Cost / Pricing Warnings',
    icon: DollarSign,
    colorClass: 'text-warning',
    bgClass: 'bg-warning/5 border-warning/20',
    dotClass: 'bg-warning',
  },
  security_concern: {
    label: 'Security / Compliance Concerns',
    icon: Shield,
    colorClass: 'text-danger',
    bgClass: 'bg-danger/5 border-danger/20',
    dotClass: 'bg-danger',
  },
};

const SEVERITY_STYLES = {
  high:   { badge: 'bg-danger/10 text-danger border-danger/30',   label: 'High' },
  medium: { badge: 'bg-warning/10 text-warning border-warning/30', label: 'Medium' },
  low:    { badge: 'bg-secondary text-text-muted border-border',   label: 'Low' },
};

const ACTION_LABELS = {
  accept:    'Accepted',
  edit:      'Edited',
  mark_risk: 'Marked as risk',
  exclude:   'Excluded',
};

// ── ReviewItem ────────────────────────────────────────────────────────────────
function ReviewItem({ item, disposition, onDispose }) {
  const title = toRenderableString(item.title);
  const description = toRenderableString(item.description);
  const editedDescription = toRenderableString(disposition?.edited_text) || description;
  const [editMode, setEditMode] = useState(false);
  const [editText, setEditText] = useState(description);
  const action = disposition?.action;
  const isResolved = !!action;

  const handleAction = (selectedAction, overrideText) => {
    onDispose(item.id, selectedAction, selectedAction === 'edit' ? (overrideText ?? editText) : undefined);
    if (selectedAction !== 'edit') setEditMode(false);
  };

  const severityStyle = SEVERITY_STYLES[item.severity] || SEVERITY_STYLES.low;

  return (
    <div
      className={`rounded-lg border p-3 transition-opacity ${isResolved ? 'opacity-60' : ''} ${
        item.severity === 'high' && !isResolved
          ? 'border-danger/30 bg-danger/3'
          : 'border-border bg-secondary/30'
      }`}
      role="listitem"
    >
      <div className="flex items-start gap-3">
        {/* Severity dot */}
        <span
          className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
            item.severity === 'high' ? 'bg-danger' : item.severity === 'medium' ? 'bg-warning' : 'bg-text-muted'
          }`}
          aria-hidden="true"
        />

        <div className="min-w-0 flex-1 space-y-1">
          {/* Title + severity badge */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-text-primary leading-snug">
              {title}
            </span>
            <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium ${severityStyle.badge}`}>
              {severityStyle.label}
            </span>
            {isResolved && (
              <span className="inline-flex items-center gap-1 rounded bg-cta/10 border border-cta/20 px-1.5 py-0.5 text-[10px] font-medium text-cta">
                <CheckCircle2 className="w-3 h-3" aria-hidden="true" />
                {ACTION_LABELS[action] || action}
              </span>
            )}
          </div>

          {/* Description */}
          {!editMode && (
            <p className="text-xs text-text-muted leading-relaxed">
              {editedDescription}
            </p>
          )}

          {/* Edit text area */}
          {editMode && (
            <div className="mt-2 space-y-2">
              <textarea
                aria-label="Edit review item description"
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                className="w-full text-xs p-2 rounded-md bg-surface border border-border text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1 focus:ring-cta resize-none"
                rows={3}
              />
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  onClick={() => handleAction('edit', editText)}
                >
                  Save edit
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => { setEditMode(false); setEditText(description); }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {/* Action buttons */}
          {!editMode && (
            <div className="flex flex-wrap gap-1.5 pt-1" role="group" aria-label="Disposition actions">
              <button
                type="button"
                onClick={() => handleAction('accept')}
                className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-medium transition-colors cursor-pointer focus:outline-none focus:ring-1 focus:ring-cta ${
                  action === 'accept'
                    ? 'bg-cta/15 border-cta/30 text-cta'
                    : 'border-border hover:border-cta/40 hover:bg-cta/5 text-text-secondary'
                }`}
                aria-pressed={action === 'accept'}
              >
                <CheckCircle2 className="w-3 h-3" aria-hidden="true" />
                Accept
              </button>

              <button
                type="button"
                onClick={() => { setEditMode(true); setEditText(editedDescription); }}
                className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-medium transition-colors cursor-pointer focus:outline-none focus:ring-1 focus:ring-cta ${
                  action === 'edit'
                    ? 'bg-info/15 border-info/30 text-info'
                    : 'border-border hover:border-info/40 hover:bg-info/5 text-text-secondary'
                }`}
                aria-pressed={action === 'edit'}
              >
                <Edit3 className="w-3 h-3" aria-hidden="true" />
                Edit
              </button>

              <button
                type="button"
                onClick={() => handleAction('mark_risk')}
                className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-medium transition-colors cursor-pointer focus:outline-none focus:ring-1 focus:ring-cta ${
                  action === 'mark_risk'
                    ? 'bg-warning/15 border-warning/30 text-warning'
                    : 'border-border hover:border-warning/40 hover:bg-warning/5 text-text-secondary'
                }`}
                aria-pressed={action === 'mark_risk'}
              >
                <AlertTriangle className="w-3 h-3" aria-hidden="true" />
                Mark as risk
              </button>

              <button
                type="button"
                onClick={() => handleAction('exclude')}
                className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-medium transition-colors cursor-pointer focus:outline-none focus:ring-1 focus:ring-cta ${
                  action === 'exclude'
                    ? 'bg-danger/15 border-danger/30 text-danger'
                    : 'border-border hover:border-danger/40 hover:bg-danger/5 text-text-secondary'
                }`}
                aria-pressed={action === 'exclude'}
              >
                <XCircle className="w-3 h-3" aria-hidden="true" />
                Exclude
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── BucketSection ─────────────────────────────────────────────────────────────
function BucketSection({ bucket, items, dispositions, onDispose }) {
  const [expanded, setExpanded] = useState(true);
  const meta = BUCKET_META[bucket] || BUCKET_META.architecture_gap;
  const Icon = meta.icon;
  const unresolvedCount = items.filter(i => !dispositions[i.id]?.action).length;

  return (
    <div className={`rounded-xl border ${meta.bgClass} overflow-hidden`}>
      {/* Bucket header — collapsible */}
      <button
        type="button"
        className="w-full flex items-center gap-3 px-4 py-3 cursor-pointer focus:outline-none focus:ring-2 focus:ring-inset focus:ring-cta/50"
        aria-expanded={expanded}
        onClick={() => setExpanded(v => !v)}
      >
        <Icon className={`w-4 h-4 shrink-0 ${meta.colorClass}`} aria-hidden="true" />
        <span className={`flex-1 text-left text-xs font-semibold ${meta.colorClass}`}>
          {meta.label}
        </span>
        {unresolvedCount > 0 && (
          <span className={`rounded-full border px-1.5 py-0.5 text-[10px] font-bold ${meta.colorClass} border-current/30`}>
            {unresolvedCount}
          </span>
        )}
        {expanded
          ? <ChevronUp className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
          : <ChevronDown className="w-3.5 h-3.5 text-text-muted" aria-hidden="true" />
        }
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-2" role="list" aria-label={`${meta.label} items`}>
          {items.map(item => (
            <ReviewItem
              key={item.id}
              item={item}
              disposition={dispositions[item.id]}
              onDispose={onDispose}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ── ArchitectReviewQueue (main export) ────────────────────────────────────────
/**
 * Props
 * -----
 * items        — array of review items from the backend queue
 * dispositions — map of { itemId: { action, edited_text } }
 * summary      — { total, unresolved, blocking, resolved, risks_accepted, gated }
 * onDispose    — (itemId, action, editedText?) => void
 * loading      — bool: show loading skeleton
 */
export default function ArchitectReviewQueue({ items = [], dispositions = {}, summary = {}, onDispose, loading = false }) {
  const [collapsed, setCollapsed] = useState(false);

  if (loading) {
    return (
      <Card className="p-4 space-y-3 animate-pulse">
        <div className="h-4 w-48 rounded bg-secondary" />
        <div className="h-3 w-full rounded bg-secondary" />
        <div className="h-3 w-3/4 rounded bg-secondary" />
      </Card>
    );
  }

  if (!items || items.length === 0) return null;

  // Group items by bucket preserving insertion order
  const bucketOrder = ['architecture_gap', 'security_concern', 'cost_warning', 'low_confidence', 'assumptions'];
  const grouped = {};
  for (const item of items) {
    if (!grouped[item.bucket]) grouped[item.bucket] = [];
    grouped[item.bucket].push(item);
  }
  const orderedBuckets = bucketOrder.filter(b => grouped[b]);

  const isGated = summary.gated;
  const blockingCount = summary.blocking ?? 0;
  const unresolvedCount = summary.unresolved ?? items.filter(i => !dispositions[i.id]?.action).length;

  return (
    <section aria-labelledby="review-queue-heading" className="space-y-3">
      {/* Header */}
      <Card className={`p-4 ${isGated ? 'border-danger/30 bg-danger/5' : 'border-warning/20 bg-warning/5'}`}>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            {isGated
              ? <ShieldAlert className="w-5 h-5 text-danger shrink-0 mt-0.5" aria-hidden="true" />
              : <AlertTriangle className="w-5 h-5 text-warning shrink-0 mt-0.5" aria-hidden="true" />
            }
            <div>
              <h3 id="review-queue-heading" className="text-sm font-bold text-text-primary">
                Architect Review Queue
              </h3>
              <p className="text-xs text-text-muted mt-0.5">
                {isGated
                  ? `${blockingCount} high-severity item${blockingCount !== 1 ? 's' : ''} must be reviewed before generating deliverables.`
                  : unresolvedCount > 0
                    ? `${unresolvedCount} item${unresolvedCount !== 1 ? 's' : ''} pending review.`
                    : 'All items reviewed. Deliverables can be generated.'
                }
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {/* Summary pills */}
            {blockingCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-danger/10 border border-danger/30 px-2.5 py-1 text-xs font-medium text-danger">
                <Lock className="w-3 h-3" aria-hidden="true" />
                {blockingCount} blocker{blockingCount !== 1 ? 's' : ''}
              </span>
            )}
            {summary.risks_accepted > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-warning/10 border border-warning/30 px-2.5 py-1 text-xs font-medium text-warning">
                <AlertTriangle className="w-3 h-3" aria-hidden="true" />
                {summary.risks_accepted} risk{summary.risks_accepted !== 1 ? 's' : ''} accepted
              </span>
            )}
            {unresolvedCount === 0 && items.length > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-cta/10 border border-cta/20 px-2.5 py-1 text-xs font-medium text-cta">
                <CheckCircle2 className="w-3 h-3" aria-hidden="true" />
                All reviewed
              </span>
            )}
            <button
              type="button"
              onClick={() => setCollapsed(v => !v)}
              className="text-xs text-text-muted hover:text-text-primary transition-colors cursor-pointer focus:outline-none focus:ring-1 focus:ring-cta rounded px-2 py-1"
              aria-expanded={!collapsed}
              aria-controls="review-queue-body"
            >
              {collapsed ? 'Show' : 'Hide'}
            </button>
          </div>
        </div>
      </Card>

      {/* Body */}
      {!collapsed && (
        <div id="review-queue-body" className="space-y-3">
          {orderedBuckets.map(bucket => (
            <BucketSection
              key={bucket}
              bucket={bucket}
              items={grouped[bucket]}
              dispositions={dispositions}
              onDispose={onDispose}
            />
          ))}
        </div>
      )}

      {/* Deliverables gate banner */}
      {isGated && !collapsed && (
        <Card className="p-3 border-danger/30 bg-danger/5" role="alert" aria-live="polite">
          <div className="flex items-center gap-3">
            <Lock className="w-4 h-4 text-danger shrink-0" aria-hidden="true" />
            <p className="text-xs text-danger font-medium">
              Deliverables are locked until all high-severity items are accepted, edited, or marked as risks.
            </p>
          </div>
        </Card>
      )}
    </section>
  );
}
