import React, { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { HelpCircle, ChevronRight, ChevronLeft, Check, Sparkles, ToggleLeft, ToggleRight, AlertTriangle, Code2, Layers, ListChecks } from 'lucide-react';
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
  analysis, questions, allQuestions = [], assumptions = [], answers, loading,
  onUpdateAnswer, onApplyAnswers, onSkip,
  constraints = [], regionGroups = {},
}) {
  const [showAllQuestions, setShowAllQuestions] = useState(false);
  const displayedQuestions = showAllQuestions && allQuestions.length > 0 ? allQuestions : questions;

  /* ── Apply inter-question constraints ── */
  const constrainedQuestions = useMemo(() => {
    if (!constraints.length) return displayedQuestions;

    // Deep-copy questions so we don't mutate the original
    const result = displayedQuestions.map(q => ({ ...q, options: [...(q.options || [])], constraintReasons: [] }));

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
  }, [displayedQuestions, answers, constraints, regionGroups]);

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

  /* ── Expert / Guided mode toggle (persisted to localStorage) ── */
  const [expertMode, setExpertMode] = useState(() => {
    try { return localStorage.getItem('archmorph-expert-mode') === 'true'; } catch { return false; }
  });
  const toggleExpertMode = useCallback(() => {
    setExpertMode(prev => {
      const next = !prev;
      try { localStorage.setItem('archmorph-expert-mode', String(next)); } catch { /* noop */ }
      return next;
    });
  }, []);

  /* ── Smart defaults: build a map of AI-suggested defaults from question.default ── */
  const aiDefaults = useMemo(() => {
    const map = {};
    for (const q of constrainedQuestions) {
      if (q.default !== undefined && q.default !== null && q.default !== '') {
        map[q.id] = q.default;
      }
    }
    return map;
  }, [constrainedQuestions]);

  /* ── Helper: does current answer differ from AI default? ── */
  const differsFromDefault = useCallback((qId) => {
    const current = answers[qId];
    const def = aiDefaults[qId];
    if (def === undefined || current === undefined) return false;
    if (Array.isArray(current) && Array.isArray(def)) {
      return current.length !== def.length || current.some(v => !def.includes(v));
    }
    return current !== def;
  }, [answers, aiDefaults]);

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
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-3">
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
          {/* Expert / Guided toggle */}
          <div className="flex items-center gap-2">
            {allQuestions.length > questions.length && (
              <button
                type="button"
                onClick={() => setShowAllQuestions(prev => !prev)}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border/50 hover:border-cta/30 bg-secondary/10 hover:bg-secondary/20 transition-all cursor-pointer text-sm font-medium text-text-secondary"
                role="switch"
                aria-checked={showAllQuestions}
                aria-label="All questions"
              >
                {showAllQuestions ? <ListChecks className="w-4 h-4 text-cta" /> : <Layers className="w-4 h-4 text-text-muted" />}
                <span>{showAllQuestions ? 'All Questions' : 'Focused Questions'}</span>
              </button>
            )}
            <button
              type="button"
              onClick={toggleExpertMode}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border/50 hover:border-cta/30 bg-secondary/10 hover:bg-secondary/20 transition-all cursor-pointer text-sm font-medium"
              role="switch"
              aria-checked={expertMode}
              aria-label="Expert view"
            >
              {expertMode ? <Code2 className="w-4 h-4 text-cta" /> : <Sparkles className="w-4 h-4 text-text-muted" />}
              <span className={expertMode ? 'text-cta' : 'text-text-secondary'}>
                {expertMode ? 'Expert View' : 'Guided View'}
              </span>
            </button>
          </div>
        </div>

        {assumptions.length > 0 && (
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-2">
            <div className="rounded-lg border border-border/50 bg-secondary/10 px-3 py-2">
              <p className="text-xs text-text-muted">Assumptions</p>
              <p className="text-sm font-semibold text-text-primary">{assumptions.length}</p>
            </div>
            <div className="rounded-lg border border-border/50 bg-secondary/10 px-3 py-2">
              <p className="text-xs text-text-muted">Focused follow-ups</p>
              <p className="text-sm font-semibold text-text-primary">{questions.length}</p>
            </div>
            <div className="rounded-lg border border-border/50 bg-secondary/10 px-3 py-2">
              <p className="text-xs text-text-muted">Review mode</p>
              <p className="text-sm font-semibold text-text-primary">{showAllQuestions ? 'All' : 'Focused'}</p>
            </div>
          </div>
        )}

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

        {/* Category stepper pills (guided mode only) */}
        {!expertMode && (
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
        )}
      </Card>

      {/* ═══════════ EXPERT VIEW ═══════════ */}
      {expertMode ? (
        <>
          <Card className="overflow-hidden">
            <div className="px-6 py-3 border-b border-border/50 bg-secondary/10 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Code2 className="w-4 h-4 text-cta" />
                <h3 className="text-sm font-semibold text-text-primary">{showAllQuestions ? 'All Questions' : 'Focused Questions'}</h3>
              </div>
              <span className="text-xs text-text-muted">Press <kbd className="px-1.5 py-0.5 rounded bg-secondary text-text-secondary text-[10px] font-mono">Tab</kbd> to navigate, <kbd className="px-1.5 py-0.5 rounded bg-secondary text-text-secondary text-[10px] font-mono">Enter</kbd> to confirm</span>
            </div>
            <div className="p-6 max-h-[70vh] overflow-y-auto space-y-8">
              {categories.map(cat => {
                const qs = constrainedQuestions.filter(q => (q.category || 'General') === cat);
                return (
                  <div key={cat}>
                    {/* Sticky category header */}
                    <div className="sticky top-0 z-10 bg-surface/95 backdrop-blur-sm py-2 mb-3 border-b border-border/30">
                      <h4 className="text-xs font-bold text-cta uppercase tracking-wider">{cat ? cat.replace(/_/g, ' ') : 'General'}</h4>
                    </div>
                    {/* 2-column compact grid */}
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-6 gap-y-3">
                      {qs.map(q => (
                        <div key={q.id} className="flex items-center gap-3 py-2 min-h-[40px]">
                          {/* Label (60%) */}
                          <div className="w-[60%] flex items-center gap-1.5 min-w-0">
                            {differsFromDefault(q.id) && (
                              <span className="w-2 h-2 rounded-full bg-amber-400 shrink-0" title="Differs from AI suggestion" />
                            )}
                            <span className="text-sm text-text-primary truncate" title={q.question}>{q.question}</span>
                          </div>
                          {/* Input (40%) */}
                          <div className="w-[40%] shrink-0">
                            {q.type === 'single_choice' && (
                              <select
                                value={answers[q.id] || ''}
                                onChange={e => onUpdateAnswer(q.id, e.target.value)}
                                className="w-full text-sm px-2 py-1.5 rounded-lg border border-border/50 bg-surface text-text-primary focus:border-cta focus:ring-1 focus:ring-cta/30 outline-none transition-colors"
                              >
                                <option value="" disabled>Select…</option>
                                {q.options?.map(raw => {
                                  const opt = typeof raw === 'string' ? { value: raw, label: raw } : raw;
                                  return <option key={opt.value} value={opt.value}>{opt.label}</option>;
                                })}
                              </select>
                            )}
                            {(q.type === 'multi_choice' || q.type === 'multiple_choice') && (
                              <div className="flex flex-wrap gap-1">
                                {q.options?.map(raw => {
                                  const opt = typeof raw === 'string' ? { value: raw, label: raw } : raw;
                                  const current = answers[q.id] || [];
                                  const isSelected = current.includes(opt.value);
                                  return (
                                    <button
                                      key={opt.value}
                                      type="button"
                                      onClick={() => onUpdateAnswer(q.id, isSelected ? current.filter(v => v !== opt.value) : [...current, opt.value])}
                                      className={`text-xs px-2 py-1 rounded border transition-colors cursor-pointer ${
                                        isSelected ? 'border-cta bg-cta/15 text-cta' : 'border-border/50 text-text-muted hover:border-cta/30'
                                      }`}
                                    >
                                      {opt.label}
                                    </button>
                                  );
                                })}
                              </div>
                            )}
                            {(q.type === 'boolean' || q.type === 'yes_no') && (
                              <button
                                type="button"
                                onClick={() => onUpdateAnswer(q.id, answers[q.id] === 'yes' ? 'no' : 'yes')}
                                className={`flex items-center gap-2 text-sm px-3 py-1.5 rounded-lg border transition-colors cursor-pointer ${
                                  answers[q.id] === 'yes'
                                    ? 'border-cta bg-cta/10 text-cta'
                                    : 'border-border/50 text-text-muted hover:border-cta/30'
                                }`}
                                role="switch"
                                aria-checked={answers[q.id] === 'yes'}
                              >
                                {answers[q.id] === 'yes'
                                  ? <ToggleRight className="w-5 h-5" />
                                  : <ToggleLeft className="w-5 h-5" />}
                                {answers[q.id] === 'yes' ? 'Yes' : 'No'}
                              </button>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
          {/* Expert mode footer */}
          <div className="flex items-center justify-between">
            <Button onClick={onSkip} variant="ghost" icon={ChevronRight}>Skip All</Button>
            <Button onClick={onApplyAnswers} loading={loading} icon={Check}>
              Apply All &amp; Generate
            </Button>
          </div>
        </>
      ) : (
        /* ═══════════ GUIDED VIEW (original) ═══════════ */
        <>
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
        </>
      )}
    </div>
  );
}
