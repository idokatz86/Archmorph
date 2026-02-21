import React from 'react';
import { HelpCircle, ChevronRight, Check } from 'lucide-react';
import { Badge, Button, Card } from '../ui';

export default function GuidedQuestions({
  analysis, questions, answers, loading,
  onUpdateAnswer, onApplyAnswers, onSkip,
}) {
  const answered = Object.keys(answers).filter(k => answers[k] !== undefined && answers[k] !== null && answers[k] !== '');
  const categories = [...new Set(questions.map(q => q.category || 'General'))];

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="flex items-center gap-3 mb-2">
          <HelpCircle className="w-6 h-6 text-cta" />
          <h2 className="text-xl font-bold text-text-primary">Customize Your Azure Architecture</h2>
        </div>
        <p className="text-sm text-text-secondary">
          We detected {analysis?.services_detected || 0} {(analysis?.source_provider || 'aws').toUpperCase()} services across {analysis?.zones?.length || 0} zones.
          Answer these questions to tailor the Azure translation to your needs.
        </p>
        {/* Progress Bar with category breakdown */}
        <div className="mt-4">
          <div className="flex items-center justify-between text-xs text-text-muted mb-1">
            <span>{answered.length} of {questions.length} answered</span>
            <span>{Math.round((answered.length / Math.max(questions.length, 1)) * 100)}%</span>
          </div>
          <div className="h-2 bg-secondary rounded-full overflow-hidden">
            <div className="h-full bg-cta transition-all duration-300" style={{ width: `${(answered.length / Math.max(questions.length, 1)) * 100}%` }} />
          </div>
          <div className="flex flex-wrap gap-2 mt-2">
            {categories.map(cat => {
              const catQs = questions.filter(q => (q.category || 'General') === cat);
              const catAnswered = catQs.filter(q => answered.includes(q.id)).length;
              return (
                <span key={cat} className={`text-[10px] px-2 py-0.5 rounded-full border ${
                  catAnswered === catQs.length ? 'border-cta/40 text-cta bg-cta/10' : 'border-border text-text-muted'
                }`}>
                  {cat.replace(/_/g, ' ')} {catAnswered}/{catQs.length}
                </span>
              );
            })}
          </div>
        </div>
      </Card>

      {/* Questions grouped by category */}
      {categories.map(cat => (
        <div key={cat} className="space-y-3">
          <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider px-1 flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-cta" />
            {cat.replace(/_/g, ' ')}
          </h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {questions.filter(q => (q.category || 'General') === cat).map(q => (
              <Card key={q.id} className="p-4 space-y-3">
                <div className="flex items-start gap-2">
                  <Badge>{q.category?.replace(/_/g, ' ')}</Badge>
                  {q.impact && <span className="text-[10px] text-text-muted uppercase">{q.impact}</span>}
                </div>
                <p className="text-sm font-medium text-text-primary">{q.question}</p>
                {q.type === 'single_choice' && (
                  <div className="space-y-1.5">
                    {q.options?.map(raw => {
                      const opt = typeof raw === 'string' ? { value: raw, label: raw } : raw;
                      return (
                        <label key={opt.value} className="flex items-center gap-3 p-2 rounded-lg hover:bg-secondary cursor-pointer transition-colors">
                          <input type="radio" name={q.id} value={opt.value} checked={answers[q.id] === opt.value} onChange={() => onUpdateAnswer(q.id, opt.value)} className="w-4 h-4 accent-cta cursor-pointer" />
                          <div>
                            <span className="text-sm text-text-primary">{opt.label}</span>
                            {opt.description && <p className="text-xs text-text-muted">{opt.description}</p>}
                          </div>
                        </label>
                      );
                    })}
                  </div>
                )}
                {(q.type === 'multi_choice' || q.type === 'multiple_choice') && (
                  <div className="space-y-1.5">
                    {q.options?.map(raw => {
                      const opt = typeof raw === 'string' ? { value: raw, label: raw } : raw;
                      return (
                        <label key={opt.value} className="flex items-center gap-3 p-2 rounded-lg hover:bg-secondary cursor-pointer transition-colors">
                          <input type="checkbox" checked={(answers[q.id] || []).includes(opt.value)} onChange={e => {
                            const current = answers[q.id] || [];
                            onUpdateAnswer(q.id, e.target.checked ? [...current, opt.value] : current.filter(v => v !== opt.value));
                          }} className="w-4 h-4 accent-cta cursor-pointer" />
                          <span className="text-sm text-text-primary">{opt.label}</span>
                        </label>
                      );
                    })}
                  </div>
                )}
                {(q.type === 'boolean' || q.type === 'yes_no') && (
                  <div className="flex items-center gap-3">
                    {['yes', 'no'].map(v => (
                      <label key={v} className="flex items-center gap-2 p-2 rounded-lg hover:bg-secondary cursor-pointer transition-colors">
                        <input type="radio" name={q.id} value={v} checked={answers[q.id] === v} onChange={() => onUpdateAnswer(q.id, v)} className="w-4 h-4 accent-cta cursor-pointer" />
                        <span className="text-sm text-text-primary capitalize">{v}</span>
                      </label>
                    ))}
                  </div>
                )}
              </Card>
            ))}
          </div>
        </div>
      ))}

      <div className="flex items-center justify-between">
        <Button onClick={onSkip} variant="ghost" icon={ChevronRight}>Skip Customization</Button>
        <Button onClick={onApplyAnswers} loading={loading} icon={Check}>Apply and View Results</Button>
      </div>
    </div>
  );
}
