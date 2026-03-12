import React, { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { HelpCircle, ChevronRight, ChevronLeft, Check, Sparkles, ToggleLeft, ToggleRight, AlertTriangle } from 'lucide-react';
import { Badge, Button, Card } from '../ui';

/* ── Toggle Switch ── */
function Toggle({ checked, onChange, label }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className="flex items-center gap-3 w-full p-3 rounded-xl border border-border/50 hover:border-cta/30 bg-secondary/10 hover:bg-secondary/20 transition-all cursor-pointer group"
      role="switch"
      aria-checked={checked}
    >
      {checked ? (
        <ToggleRight className="w-7 h-7 text-cta shrink-0 transition-colors" />
      ) : (
        <ToggleLeft className="w-7 h-7 text-text-muted shrink-0 transition-colors group-hover:text-text-secondary" />
      )}
      <span className={`text-sm font-medium transition-colors ${checked ? 'text-cta' : 'text-text-secondary'}`}>{label}</span>
    </button>
  );
}

/* ── Selectable Option Card ── */
function OptionCard({ selected, onClick, label, description, multi }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative flex items-start gap-3 p-4 rounded-xl border-2 text-left transition-all duration-200 cursor-pointer w-full ${
        selected
          ? 'border-cta bg-cta/5 shadow-[0_0_0_1px_rgba(var(--color-cta-rgb,59,130,246),0.2)]'
          : 'border-border/50 bg-secondary/5 hover:border-cta/30 hover:bg-secondary/15'
      }`}
    >
      {/* Selection indicator */}
      <div className={`mt-0.5 shrink-0 w-5 h-5 rounded-${multi ? 'md' : 'full'} border-2 flex items-center justify-center transition-all duration-200 ${
        selected ? 'border-cta bg-cta' : 'border-text-muted/40'
      }`}>
        {selected && <Check className="w-3 h-3 text-white" />}
      </div>
      <div className="min-w-0">
        <span className={`text-sm font-medium ${selected ? 'text-cta' : 'text-text-primary'}`}>{label}</span>
        {description && <p className="text-xs text-text-muted mt-0.5 leading-relaxed">{description}</p>}
      </div>
    </button>
  );
}

export default function GuidedQuestions({
  analysis, questions, answers, loading,
  onUpdateAnswer, onApplyAnswers, onSkip,
  constraints = [], regionGroups = {},
}) {
  /* ── Apply inter-question constraints ── */
  const constrainedQuestions = useMemo(() => {
    if (!constraints.length) return questions;

    // Deep-copy questions so we don't mutate the original
    const result = questions.map(q => ({ ...q, options: [...(q.options || [])], constraintReasons: [] }));

    for (const rule of constraints) {
      const sourceAnswer = answers[rule.source];
      if (sourceAnswer === undefined || sourceAnswer === null || sourceAnswer === '') continue;

      // Check if the constraint matches the current answer
      const match = rule.match;
      let matched = false;
      if (match.type === 'value') {
        matched = sourceAnswer === match.value;
      } else if (match.type === 'contains') {
        matched = Array.isArray(sourceAnswer)
          ? sourceAnswer.includes(match.value)
          : sourceAnswer === match.value;
      }
      if (!matched) continue;

      // Apply the filter to the target question
      const target = result.find(q => q.id === rule.target);
      if (!target) continue;

      const filter = rule.filter;
      if (filter.type === 'region_group') {
        const allowed = regionGroups[filter.group] || [];
        target.options = target.options.filter(o => allowed.includes(typeof o === 'string' ? o : o.value));
      } else if (filter.type === 'allowed') {
        target.options = target.options.filter(o => filter.values.includes(typeof o === 'string' ? o : o.value));
      } else if (filter.type === 'excluded') {
        target.options = target.options.filter(o => !filter.values.includes(typeof o === 'string' ? o : o.value));
      }
      target.constraintReasons.push(rule.reason);
    }
    return result;
  }, [questions, answers, constraints, regionGroups]);

  /* ── Auto-clear answers that are no longer valid after constraint filtering ── */
  useEffect(() => {
    for (const q of constrainedQuestions) {
      const currentAnswer = answers[q.id];
      if (currentAnswer === undefined || currentAnswer === null || currentAnswer === '') continue;

      const validValues = (q.options || []).map(o => typeof o === 'string' ? o : o.value);

      if (q.type === 'single_choice') {
        if (!validValues.includes(currentAnswer)) {
          onUpdateAnswer(q.id, q.options.length > 0 ? (typeof q.options[0] === 'string' ? q.options[0] : q.options[0].value) : '');
        }
      } else if (q.type === 'multiple_choice' || q.type === 'multi_choice') {
        if (Array.isArray(currentAnswer)) {
          const filtered = currentAnswer.filter(v => validValues.includes(v));
          if (filtered.length !== currentAnswer.length) {
            onUpdateAnswer(q.id, filtered);
          }
        }
      }
    }
  }, [constrainedQuestions]); // eslint-disable-line react-hooks/exhaustive-deps

  const categories = useMemo(() => [...new Set(constrainedQuestions.map(q => q.category || 'General'))], [constrainedQuestions]);
  const [activeCatIdx, setActiveCatIdx] = useState(0);
  const contentRef = useRef(null);

  const activeCat = categories[activeCatIdx] || categories[0] || 'General';
  const catQuestions = useMemo(() => constrainedQuestions.filter(q => (q.category || 'General') === activeCat), [constrainedQuestions, activeCat]);

  const answered = useMemo(() => Object.keys(answers).filter(k => answers[k] !== undefined && answers[k] !== null && answers[k] !== ''), [answers]);
  const totalProgress = Math.round((answered.length / Math.max(constrainedQuestions.length, 1)) * 100);

  // Scroll to top of content when switching categories
  useEffect(() => {
    contentRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
  }, [activeCatIdx]);

  const goNext = useCallback(() => {
    if (activeCatIdx < categories.length - 1) setActiveCatIdx(i => i + 1);
    else onApplyAnswers();
  }, [activeCatIdx, categories.length, onApplyAnswers]);

  const goPrev = useCallback(() => {
    if (activeCatIdx > 0) setActiveCatIdx(i => i - 1);
  }, [activeCatIdx]);

  const isLast = activeCatIdx === categories.length - 1;

  return (
    <div className="space-y-5">
      {/* Header Card */}
      <Card className="p-6">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-10 h-10 rounded-xl bg-cta/10 flex items-center justify-center">
            <HelpCircle className="w-5 h-5 text-cta" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-text-primary">Customize Your Azure Architecture</h2>
            <p className="text-sm text-text-secondary mt-0.5">
              {analysis?.services_detected || 0} {(analysis?.source_provider || 'aws').toUpperCase()} services detected across {analysis?.zones?.length || 0} zones
            </p>
          </div>
        </div>

        {/* Overall progress */}
        <div className="mt-4">
          <div className="flex items-center justify-between text-xs mb-1.5">
            <span className="text-text-muted">{answered.length} of {constrainedQuestions.length} answered</span>
            <span className="font-medium text-cta">{totalProgress}%</span>
          </div>
          <div className="h-2 bg-secondary rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-cta to-cta/70 rounded-full transition-all duration-500 ease-out"
              style={{ width: `${totalProgress}%` }}
            />
          </div>
        </div>

        {/* Category stepper pills */}
        <div className="flex flex-wrap gap-2 mt-4">
          {categories.map((cat, idx) => {
            const catQs = constrainedQuestions.filter(q => (q.category || 'General') === cat);
            const catAnswered = catQs.filter(q => answered.includes(q.id)).length;
            const isActive = idx === activeCatIdx;
            const isDone = catAnswered === catQs.length;
            return (
              <button
                key={cat}
                onClick={() => setActiveCatIdx(idx)}
                className={`text-xs px-3 py-1.5 rounded-full border transition-all duration-200 cursor-pointer font-medium ${
                  isActive
                    ? 'border-cta bg-cta/15 text-cta shadow-sm'
                    : isDone
                      ? 'border-cta/30 text-cta/80 bg-cta/5'
                      : 'border-border/50 text-text-muted hover:border-cta/20 hover:text-text-secondary'
                }`}
              >
                {isDone && <Check className="w-3 h-3 inline mr-1 -mt-px" />}
                {cat ? cat.replace(/_/g, ' ') : 'General'} {catAnswered}/{catQs.length}
              </button>
            );
          })}
        </div>
      </Card>

      {/* Active category questions */}
      <Card className="overflow-hidden">
        <div className="px-6 py-4 border-b border-border/50 bg-secondary/10">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-cta" />
            <h3 className="text-sm font-semibold text-text-primary">{activeCat ? activeCat.replace(/_/g, ' ') : ''}</h3>
            <span className="text-xs text-text-muted ml-auto">{activeCatIdx + 1} of {categories.length}</span>
          </div>
        </div>
        <div ref={contentRef} className="p-6 space-y-6 max-h-[60vh] overflow-y-auto">
          {catQuestions.map((q, qi) => (
            <div key={q.id} className="space-y-3">
              <div className="flex items-start gap-2">
                <span className="text-xs font-bold text-cta/60 mt-0.5">{qi + 1}.</span>
                <div>
                  <p className="text-sm font-medium text-text-primary leading-snug">{q.question}</p>
                  {q.impact && (
                    <Badge className="mt-1.5" variant="outline">{q.impact}</Badge>
                  )}
                  {q.constraintReasons?.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {q.constraintReasons.map((reason, ri) => (
                        <span key={ri} className="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20">
                          <AlertTriangle className="w-3 h-3 shrink-0" />
                          {reason}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* Single choice → selectable cards */}
              {q.type === 'single_choice' && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pl-5">
                  {q.options?.map(raw => {
                    const opt = typeof raw === 'string' ? { value: raw, label: raw } : raw;
                    return (
                      <OptionCard
                        key={opt.value}
                        selected={answers[q.id] === opt.value}
                        onClick={() => onUpdateAnswer(q.id, opt.value)}
                        label={opt.label}
                        description={opt.description}
                      />
                    );
                  })}
                </div>
              )}

              {/* Multi choice → selectable cards with checkmarks */}
              {(q.type === 'multi_choice' || q.type === 'multiple_choice') && (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pl-5">
                  {q.options?.map(raw => {
                    const opt = typeof raw === 'string' ? { value: raw, label: raw } : raw;
                    const current = answers[q.id] || [];
                    const isSelected = current.includes(opt.value);
                    return (
                      <OptionCard
                        key={opt.value}
                        selected={isSelected}
                        multi
                        onClick={() => {
                          onUpdateAnswer(q.id, isSelected
                            ? current.filter(v => v !== opt.value)
                            : [...current, opt.value]);
                        }}
                        label={opt.label}
                        description={opt.description}
                      />
                    );
                  })}
                </div>
              )}

              {/* Boolean → toggle switch */}
              {(q.type === 'boolean' || q.type === 'yes_no') && (
                <div className="pl-5 max-w-sm">
                  <Toggle
                    checked={answers[q.id] === 'yes'}
                    onChange={(v) => onUpdateAnswer(q.id, v ? 'yes' : 'no')}
                    label={answers[q.id] === 'yes' ? 'Yes — Enabled' : 'No — Disabled'}
                  />
                </div>
              )}

              {qi < catQuestions.length - 1 && <hr className="border-border/30 ml-5" />}
            </div>
          ))}
        </div>
      </Card>

      {/* Navigation footer */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {activeCatIdx > 0 && (
            <Button onClick={goPrev} variant="ghost" icon={ChevronLeft}>Previous</Button>
          )}
          <Button onClick={onSkip} variant="ghost" icon={ChevronRight}>Skip All</Button>
        </div>
        <Button
          onClick={goNext}
          loading={isLast && loading}
          icon={isLast ? Check : ChevronRight}
        >
          {isLast ? 'Apply and View Results' : 'Next Category'}
        </Button>
      </div>
    </div>
  );
}
