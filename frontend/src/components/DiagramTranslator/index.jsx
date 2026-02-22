import React, { useRef, useCallback, useEffect } from 'react';
import {
  Upload, ChevronRight, CheckCircle, XCircle, X,
  Loader2, Eye,
} from 'lucide-react';
import { Button, Card } from '../ui';
import { API_BASE } from '../../constants';
import useWorkflow from './useWorkflow';
import useSSE from '../../hooks/useSSE';
import UploadStep from './UploadStep';
import GuidedQuestions from './GuidedQuestions';
import AnalysisResults from './AnalysisResults';
import IaCViewer from './IaCViewer';
import CostPanel from './CostPanel';

const STEPS = [
  { id: 'upload', label: 'Upload', canNav: true },
  { id: 'analyzing', label: 'Analyzing', canNav: false },
  { id: 'questions', label: 'Customize' },
  { id: 'results', label: 'Results' },
  { id: 'iac', label: 'IaC Code' },
];

export default function DiagramTranslator() {
  const {
    state, set, addProgress, addChatMessage,
    setExportLoading, setHldExportLoading,
    updateAnswer, reset, copyWithFeedback,
  } = useWorkflow();

  const fileInputRef = useRef(null);
  const iacChatEndRef = useRef(null);
  const iacChatInputRef = useRef(null);

  // ── Cleanup blob URLs on unmount ──
  useEffect(() => {
    return () => {
      if (state.filePreviewUrl) URL.revokeObjectURL(state.filePreviewUrl);
    };
  }, []);

  // ── Drag & drop ──
  const handleDragOver = useCallback((e) => { e.preventDefault(); e.stopPropagation(); set({ dragOver: true }); }, [set]);
  const handleDragLeave = useCallback((e) => { e.preventDefault(); e.stopPropagation(); set({ dragOver: false }); }, [set]);
  const handleDrop = useCallback((e) => {
    e.preventDefault(); e.stopPropagation(); set({ dragOver: false });
    const file = e.dataTransfer?.files?.[0];
    if (file && (file.type.startsWith('image/') || file.name.match(/\.(svg|pdf)$/i))) {
      const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
      if (file.size > MAX_FILE_SIZE) {
        set({ error: 'File exceeds 10 MB limit. Please upload a smaller file.' });
        return;
      }
      if (state.filePreviewUrl) URL.revokeObjectURL(state.filePreviewUrl);
      set({
        selectedFile: file,
        filePreviewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : null,
      });
    }
  }, [set, state.filePreviewUrl]);

  const handleFileSelect = useCallback((file) => {
    if (!file) return;
    const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
    if (file.size > MAX_FILE_SIZE) {
      set({ error: 'File exceeds 10 MB limit. Please upload a smaller file.' });
      return;
    }
    if (state.filePreviewUrl) URL.revokeObjectURL(state.filePreviewUrl);
    set({
      selectedFile: file,
      filePreviewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : null,
    });
  }, [set, state.filePreviewUrl]);

  // ── Upload & Analyze ──
  const handleUpload = async (file) => {
    set({ error: null, step: 'analyzing', analyzeProgress: [] });

    addProgress('Connecting to analysis engine...');

    try {
      const formData = new FormData();
      formData.append('file', file);

      addProgress('Uploading diagram...');
      const uploadRes = await fetch(`${API_BASE}/projects/demo-project/diagrams`, { method: 'POST', body: formData });
      if (!uploadRes.ok) {
        const errData = await uploadRes.json().catch(() => ({}));
        throw new Error(errData.detail || `Upload failed (${uploadRes.status})`);
      }
      const { diagram_id } = await uploadRes.json();
      set({ diagramId: diagram_id });

      addProgress('Starting architecture analysis...');

      // Try async endpoint with SSE for real-time progress
      let useAsyncEndpoint = true;
      let asyncRes;
      try {
        asyncRes = await fetch(`${API_BASE}/diagrams/${diagram_id}/analyze-async`, { method: 'POST' });
        if (!asyncRes.ok || asyncRes.status !== 202) useAsyncEndpoint = false;
      } catch {
        useAsyncEndpoint = false;
      }

      if (useAsyncEndpoint) {
        // ── SSE real-time progress path ──
        const { job_id } = await asyncRes.json();
        set({ jobId: job_id });

        // Wait for SSE completion via a promise
        const result = await new Promise((resolve, reject) => {
          const url = `${API_BASE}/jobs/${job_id}/stream`;
          const es = new EventSource(url);

          es.addEventListener('progress', (e) => {
            try {
              const data = JSON.parse(e.data);
              if (data.message) addProgress(data.message);
            } catch { /* ignore */ }
          });

          es.addEventListener('complete', (e) => {
            try {
              const data = JSON.parse(e.data);
              es.close();
              resolve(data.result ?? data);
            } catch (err) {
              es.close();
              reject(err);
            }
          });

          es.addEventListener('error', (e) => {
            try {
              const data = JSON.parse(e.data);
              es.close();
              reject(new Error(data.error || data.message || 'Analysis failed'));
            } catch {
              // Connection error — SSE spec fires generic error
              es.close();
              reject(new Error('Connection to analysis stream lost'));
            }
          });

          es.addEventListener('cancelled', () => {
            es.close();
            reject(new Error('Analysis was cancelled'));
          });

          // Timeout safety net (5 minutes)
          setTimeout(() => { es.close(); reject(new Error('Analysis timed out')); }, 300000);
        });

        // Handle non-architecture diagram
        if (result?.detail?.error === 'not_architecture_diagram') {
          const msg = result.detail.message || 'Not an architecture diagram.';
          const imageType = result.detail.classification?.image_type || 'unknown';
          set({
            error: `🚫 ${msg}\n\nDetected image type: "${imageType}". Please upload a cloud architecture diagram.`,
            step: 'upload',
          });
          return;
        }

        addProgress('Analysis complete. ✓');
        await new Promise(r => setTimeout(r, 400));

        set({ analysis: result });

        const qRes = await fetch(`${API_BASE}/diagrams/${diagram_id}/questions`, { method: 'POST' });
        const qData = await qRes.json();
        const questions = qData.questions || [];
        const defaults = {};
        questions.forEach(q => { defaults[q.id] = q.default; });
        set({ questions, answers: defaults, step: 'questions' });
      } else {
        // ── Fallback: sync endpoint with simulated progress ──
        addProgress('Analyzing architecture with GPT-4o Vision...');

        const waitingMessages = [
          'Scanning diagram components...',
          'Identifying cloud services and icons...',
          'Detecting networking topology...',
          'Analyzing compute and storage layers...',
          'Evaluating security boundaries...',
          'Mapping data flow connections...',
          'Reviewing architecture patterns...',
          'Cross-referencing service catalog...',
          'Validating service dependencies...',
          'Finalizing architecture analysis...',
        ];

        let msgIndex = 0;
        const progressInterval = setInterval(() => {
          if (msgIndex < waitingMessages.length) {
            addProgress(waitingMessages[msgIndex]);
            msgIndex++;
          }
        }, 2500 + Math.random() * 1500);

        const analyzeRes = await fetch(`${API_BASE}/diagrams/${diagram_id}/analyze`, { method: 'POST' });
        clearInterval(progressInterval);
        const result = await analyzeRes.json();

        if (analyzeRes.status === 422 && result?.detail?.error === 'not_architecture_diagram') {
          const msg = result.detail.message || 'The uploaded image is not a valid architecture diagram.';
          const imageType = result.detail.classification?.image_type || 'unknown';
          set({
            error: `🚫 ${msg}\n\nDetected image type: "${imageType}". Please upload a cloud architecture diagram (AWS, GCP, or similar).`,
            step: 'upload',
          });
          return;
        }

        if (!analyzeRes.ok) throw new Error(result?.detail || 'Analysis failed');

        const provider = (result.source_provider || 'aws').toUpperCase();
        for (const zone of (result.zones || [])) {
          const svcNames = (zone.services || []).map(s => {
            if (typeof s === 'string') return s;
            return s.source || s.aws || s.gcp || s.source_service || s.name || '';
          }).filter(Boolean).slice(0, 3);
          const svcLabel = svcNames.length > 0 ? ` (${svcNames.join(', ')})` : '';
          addProgress(`Zone ${zone.number || zone.id}: ${zone.name}${svcLabel}...`);
          await new Promise(r => setTimeout(r, 200));
        }

        addProgress(`Mapping ${provider} services to Azure equivalents...`);
        addProgress('Analysis complete. ✓');
        await new Promise(r => setTimeout(r, 800));

        set({ analysis: result });

        const qRes = await fetch(`${API_BASE}/diagrams/${diagram_id}/questions`, { method: 'POST' });
        const qData = await qRes.json();
        const questions = qData.questions || [];
        const defaults = {};
        questions.forEach(q => { defaults[q.id] = q.default; });
        set({ questions, answers: defaults, step: 'questions' });
      }
    } catch (err) {
      set({ error: err.message, step: 'upload' });
    }
  };

  const handleLoadSample = async (sample) => {
    set({ step: 'analyzing', analyzeProgress: ['Loading sample diagram...'] });
    try {
      const res = await fetch(`${API_BASE}/samples/${sample.id}/analyze`, { method: 'POST' });
      if (!res.ok) throw new Error('Sample analysis failed');
      const result = await res.json();
      set({ diagramId: result.diagram_id, analysis: result });
      for (const zone of (result.zones || [])) {
        const svcNames = (zone.services || []).map(s => s.source || s.name || '').filter(Boolean).slice(0, 3);
        addProgress(`Zone ${zone.id}: ${zone.name} (${svcNames.join(', ')})...`);
        await new Promise(r => setTimeout(r, 300));
      }
      addProgress(`Mapping ${sample.provider.toUpperCase()} services to Azure equivalents...`);
      await new Promise(r => setTimeout(r, 400));
      addProgress('Sample loaded successfully \u2713');
      await new Promise(r => setTimeout(r, 600));
      const qRes = await fetch(`${API_BASE}/diagrams/${result.diagram_id}/questions`, { method: 'POST' });
      const qData = await qRes.json();
      const questions = qData.questions || [];
      const defaults = {};
      questions.forEach(q => { defaults[q.id] = q.default; });
      set({ questions, answers: defaults, step: 'questions' });
    } catch (err) {
      set({ error: 'Failed to load sample: ' + err.message, step: 'upload' });
    }
  };

  const handleApplyAnswers = async () => {
    set({ loading: true });
    try {
      const res = await fetch(`${API_BASE}/diagrams/${state.diagramId}/apply-answers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(state.answers),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        if (res.status === 404) {
          set({ error: 'Your session has expired (the backend was redeployed). Please re-upload your diagram.', step: 'upload', loading: false });
          return;
        }
        throw new Error(errData.detail || `Failed to apply answers (${res.status})`);
      }
      const refined = await res.json();
      set({ analysis: { ...state.analysis, ...refined }, step: 'results' });
    } catch (err) {
      set({ error: err.message });
    }
    set({ loading: false });
  };

  const handleGenerateIac = async (fmt) => {
    set({ loading: true, iacFormat: fmt });
    try {
      const [iacRes, costRes] = await Promise.all([
        fetch(`${API_BASE}/diagrams/${state.diagramId}/generate?format=${fmt}`, { method: 'POST' }),
        fetch(`${API_BASE}/diagrams/${state.diagramId}/cost-estimate`),
      ]);
      if (iacRes.status === 404) {
        set({ error: 'Your session has expired (the backend was redeployed). Please re-upload your diagram.', step: 'upload', loading: false });
        return;
      }
      if (!iacRes.ok) {
        const errData = await iacRes.json().catch(() => ({}));
        throw new Error(errData.detail || `IaC generation failed (${iacRes.status})`);
      }
      const iacData = await iacRes.json();
      const costData = costRes.ok ? await costRes.json() : null;
      set({ iacCode: iacData.code, costEstimate: costData, step: 'iac' });
    } catch (err) {
      set({ error: err.message });
    }
    set({ loading: false });
  };

  const handleHldExport = async (fmt) => {
    setHldExportLoading(fmt, true);
    try {
      const res = await fetch(`${API_BASE}/diagrams/${state.diagramId}/export-hld?format=${fmt}&include_diagrams=${state.hldIncludeDiagrams}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (res.status === 404) {
        set({ error: 'Your session has expired (the backend was redeployed). Please re-upload your diagram.', step: 'upload' });
        setHldExportLoading(fmt, false);
        return;
      }
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Export failed (${res.status})`);
      }
      const data = await res.json();
      const bytes = Uint8Array.from(atob(data.content_b64), c => c.charCodeAt(0));
      const blob = new Blob([bytes], { type: data.content_type });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = data.filename;
      a.click();
      URL.revokeObjectURL(url);
      copyWithFeedback('', `hld-${fmt}`);
    } catch (err) {
      set({ error: `HLD export failed: ${err.message}` });
    }
    setHldExportLoading(fmt, false);
  };

  const handleExportDiagram = async (format) => {
    setExportLoading(format, true);
    try {
      const res = await fetch(`${API_BASE}/diagrams/${state.diagramId}/export-diagram?format=${format}`, { method: 'POST' });
      if (res.status === 404) {
        set({ error: 'Your session has expired (the backend was redeployed). Please re-upload your diagram.', step: 'upload' });
        setExportLoading(format, false);
        return;
      }
      const data = await res.json();
      const content = typeof data.content === 'string' ? data.content : JSON.stringify(data.content, null, 2);
      const blob = new Blob([content], { type: 'application/octet-stream' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = data.filename || `archmorph-diagram.${format === 'excalidraw' ? 'excalidraw' : format === 'drawio' ? 'drawio' : 'vdx'}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      set({ error: `Export failed: ${err.message}` });
    }
    setExportLoading(format, false);
  };

  const handleIacChat = async () => {
    const text = state.iacChatInput.trim();
    if (!text || state.iacChatLoading) return;
    set({ iacChatInput: '' });
    addChatMessage({ role: 'user', content: text });
    set({ iacChatLoading: true });
    try {
      const res = await fetch(`${API_BASE}/diagrams/${state.diagramId}/iac-chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, code: state.iacCode || '', format: state.iacFormat }),
      });
      const data = await res.json();
      addChatMessage({
        role: 'assistant',
        content: data.reply || data.message || 'Done.',
        changes: data.changes_summary || [],
        services: data.services_added || [],
      });
      if (data.code && !data.error) {
        set({ iacCode: data.code });
      }
    } catch {
      addChatMessage({ role: 'assistant', content: 'Sorry, couldn\'t connect to the IaC assistant.' });
    }
    set({ iacChatLoading: false });
    setTimeout(() => iacChatEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
  };

  const handleGenerateHld = async () => {
    set({ hldLoading: true, error: null });
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 120_000);
      const res = await fetch(`${API_BASE}/diagrams/${state.diagramId}/generate-hld`, {
        method: 'POST',
        signal: controller.signal,
      });
      clearTimeout(timeout);
      if (res.status === 404) {
        set({ error: 'Your session has expired (the backend was redeployed). Please re-upload your diagram.', step: 'upload', hldLoading: false });
        return;
      }
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || `HLD generation failed (${res.status})`);
      if (data.hld) set({ hldData: data });
    } catch (err) {
      const msg = err.name === 'AbortError'
        ? 'HLD generation timed out. Please try again.'
        : 'HLD generation failed: ' + err.message;
      set({ error: msg });
    }
    set({ hldLoading: false });
  };

  const handleResetChat = () => {
    set({ iacChatMessages: [{ role: 'assistant', content: 'Chat reset. What would you like to change in your IaC code?' }] });
    if (state.diagramId) fetch(`${API_BASE}/diagrams/${state.diagramId}/iac-chat`, { method: 'DELETE' }).catch(() => {});
  };

  const handleOpenChatWithMessage = (msg) => {
    set({ iacChatOpen: true, iacChatInput: msg });
    setTimeout(() => iacChatInputRef.current?.focus(), 100);
  };

  // ── Render ──
  const steps = STEPS.map(s => ({
    ...s,
    canNav: s.id === 'upload' ? true
      : s.id === 'questions' || s.id === 'results' ? !!state.analysis
      : s.id === 'iac' ? !!state.iacCode
      : false,
  }));

  return (
    <div className="space-y-6">
      {/* Progress Steps */}
      <div className="flex items-center justify-center gap-2 text-xs font-medium">
        {steps.map((s, i, arr) => {
          const isActive = state.step === s.id;
          const isPast = arr.findIndex(x => x.id === state.step) > i;
          const clickable = s.canNav && !isActive && state.step !== 'analyzing';
          return (
            <React.Fragment key={s.id}>
              {clickable ? (
                <button
                  type="button"
                  onClick={() => set({ step: s.id })}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full transition-all duration-150 cursor-pointer border-none bg-transparent select-none ${
                    isPast ? 'text-cta hover:bg-cta/15 hover:scale-105' : 'text-text-muted hover:bg-cta/10 hover:text-cta'
                  }`}
                  title={`Go to ${s.label}`}
                >
                  {isPast ? <CheckCircle className="w-3.5 h-3.5" /> : <span className="w-5 h-5 rounded-full border border-current flex items-center justify-center text-[10px]">{i + 1}</span>}
                  <span className={`underline decoration-dotted underline-offset-2 ${isActive ? '' : 'hidden sm:inline'}`}>{s.label}</span>
                </button>
              ) : (
                <div
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full transition-colors ${
                    isActive ? 'bg-cta/15 text-cta' :
                    isPast ? 'text-cta' : 'text-text-muted'
                  }`}
                >
                  {isPast ? <CheckCircle className="w-3.5 h-3.5" /> : <span className="w-5 h-5 rounded-full border border-current flex items-center justify-center text-[10px]">{i + 1}</span>}
                  <span className={isActive ? '' : 'hidden sm:inline'}>{s.label}</span>
                </div>
              )}
              {i < arr.length - 1 && <ChevronRight className="w-4 h-4 text-text-muted" />}
            </React.Fragment>
          );
        })}
      </div>

      {/* Error */}
      {state.error && (
        <Card className="p-4 border-danger/30">
          <div className="flex items-center gap-3">
            <XCircle className="w-5 h-5 text-danger shrink-0" />
            <p className="text-sm text-danger">{state.error}</p>
            <button onClick={() => set({ error: null })} className="ml-auto cursor-pointer hover:bg-secondary rounded-lg p-1 transition-colors" aria-label="Dismiss error" title="Dismiss"><X className="w-4 h-4 text-text-muted" /></button>
          </div>
        </Card>
      )}

      {/* Step: Upload */}
      {state.step === 'upload' && (
        <UploadStep
          dragOver={state.dragOver}
          selectedFile={state.selectedFile}
          filePreviewUrl={state.filePreviewUrl}
          fileInputRef={fileInputRef}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onFileSelect={handleFileSelect}
          onUpload={handleUpload}
          onRemoveFile={() => {
            if (state.filePreviewUrl) URL.revokeObjectURL(state.filePreviewUrl);
            set({ selectedFile: null, filePreviewUrl: null });
          }}
          onLoadSample={handleLoadSample}
        />
      )}

      {/* Step: Analyzing */}
      {state.step === 'analyzing' && (
        <Card className="p-8">
          <div className="max-w-2xl mx-auto">
            <div className="flex items-center gap-3 mb-6">
              <Loader2 className="w-6 h-6 text-cta animate-spin" />
              <h2 className="text-xl font-bold text-text-primary">Analyzing Architecture...</h2>
            </div>
            <div className="space-y-1 font-mono text-xs">
              {state.analyzeProgress.map((msg, i) => (
                <div key={i} className="flex items-center gap-2 text-text-secondary animate-fade-in">
                  <CheckCircle className="w-3.5 h-3.5 text-cta shrink-0" />
                  <span>{msg}</span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}

      {/* Step: Questions */}
      {state.step === 'questions' && (
        <GuidedQuestions
          analysis={state.analysis}
          questions={state.questions}
          answers={state.answers}
          loading={state.loading}
          onUpdateAnswer={updateAnswer}
          onApplyAnswers={handleApplyAnswers}
          onSkip={() => set({ step: 'results' })}
        />
      )}

      {/* Step: Results */}
      {state.step === 'results' && state.analysis && (
        <AnalysisResults
          analysis={state.analysis}
          loading={state.loading}
          iacFormat={state.iacFormat}
          exportLoading={state.exportLoading}
          hldLoading={state.hldLoading}
          hldData={state.hldData}
          hldTab={state.hldTab}
          hldExportLoading={state.hldExportLoading}
          hldIncludeDiagrams={state.hldIncludeDiagrams}
          copyFeedback={state.copyFeedback}
          onSetStep={(step) => set({ step })}
          onGenerateIac={handleGenerateIac}
          onGenerateHld={handleGenerateHld}
          onExportDiagram={handleExportDiagram}
          onSetHldTab={(tab) => set({ hldTab: tab })}
          onSetHldIncludeDiagrams={(v) => set({ hldIncludeDiagrams: v })}
          onHldExport={handleHldExport}
          onCopyWithFeedback={copyWithFeedback}
        />
      )}

      {/* Step: IaC Code */}
      {state.step === 'iac' && state.iacCode && (
        <div className="space-y-6">
          <CostPanel costEstimate={state.costEstimate} />
          <IaCViewer
            iacCode={state.iacCode}
            iacFormat={state.iacFormat}
            copyFeedback={state.copyFeedback}
            iacChatOpen={state.iacChatOpen}
            iacChatMessages={state.iacChatMessages}
            iacChatInput={state.iacChatInput}
            iacChatLoading={state.iacChatLoading}
            iacChatEndRef={iacChatEndRef}
            iacChatInputRef={iacChatInputRef}
            onCopyWithFeedback={copyWithFeedback}
            onToggleChat={() => {
              set({ iacChatOpen: !state.iacChatOpen });
              setTimeout(() => iacChatInputRef.current?.focus(), 100);
            }}
            onOpenChatWithMessage={handleOpenChatWithMessage}
            onResetChat={handleResetChat}
            onSendChat={handleIacChat}
            onSetChatInput={(v) => set({ iacChatInput: v })}
          />
          <div className="flex items-center justify-between">
            <Button onClick={() => set({ step: 'results' })} variant="ghost" icon={Eye}>Back to Results</Button>
            {state.confirmReset ? (
              <div className="flex items-center gap-2 bg-secondary rounded-lg px-3 py-2 border border-border animate-fade-in">
                <span className="text-xs text-text-secondary">Discard current translation?</span>
                <Button onClick={reset} variant="danger" size="sm">Yes, Start Over</Button>
                <Button onClick={() => set({ confirmReset: false })} variant="ghost" size="sm">Cancel</Button>
              </div>
            ) : (
              <Button onClick={() => set({ confirmReset: true })} variant="secondary" icon={Upload}>New Translation</Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
