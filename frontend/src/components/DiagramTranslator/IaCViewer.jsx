import React, { useMemo, useState, useRef, useCallback } from 'react';
import Prism from '../../lib/prism';
import DOMPurify from 'dompurify';
import {
  FileCode, FileText, Download, Check, Sparkles, Bot,
  Plus, RotateCcw, Send, Loader2, CheckCircle, GitPullRequest,
} from 'lucide-react';
import { Button, Card } from '../ui';
import { ContextualHint } from '../ContextualHint';
import { toRenderableString } from '../../utils/toRenderableString';

const QUICK_ACTIONS = [
  { label: 'Add VNet & Subnets', msg: 'Add a Virtual Network with 3 subnets: frontend (10.0.1.0/24), backend (10.0.2.0/24), and data (10.0.3.0/24). Include NSGs for each subnet with appropriate rules.' },
  { label: 'Add Public IPs', msg: 'Add public IP addresses for the load balancer and application gateway. Use Standard SKU with static allocation.' },
  { label: 'Add Storage Account', msg: 'Add a general-purpose v2 storage account with blob containers, lifecycle management policy, and private endpoint.' },
  { label: 'Apply Naming Convention', msg: 'Apply Microsoft Cloud Adoption Framework (CAF) naming conventions to ALL resources. Use the pattern: {resource-type}-{project}-{environment}.' },
  { label: 'Add Monitoring', msg: 'Add Azure Monitor with Log Analytics workspace, diagnostic settings for all resources, and Application Insights.' },
  { label: 'Add Key Vault Policies', msg: 'Add access policies to the Key Vault for the current user with full key, secret, and certificate permissions. Also add managed identity access for compute resources.' },
  { label: 'Add Private Endpoints', msg: 'Add private endpoints for all PaaS services (storage accounts, Cosmos DB, SQL, Key Vault). Include Private DNS Zones for each service.' },
  { label: 'Add Bastion Host', msg: 'Add Azure Bastion with a dedicated AzureBastionSubnet (/26) for secure RDP/SSH access to VMs without public IPs.' },
];

const CHAT_QUICK_BUTTONS = [
  { label: 'VNet', msg: 'Add a Virtual Network with 3 subnets: frontend, backend, and data, with NSGs.' },
  { label: 'Storage', msg: 'Add a general-purpose v2 storage account with blob containers and private endpoint.' },
  { label: 'Monitoring', msg: 'Add Azure Monitor with Log Analytics workspace and Application Insights.' },
  { label: 'Naming', msg: 'Apply CAF naming conventions to ALL resources.' },
  { label: 'Bastion', msg: 'Add Azure Bastion for secure RDP/SSH access without public IPs.' },
];

export default function IaCViewer({
  iacCode, previousIacCode, iacFormat, copyFeedback,
  iacChatOpen, iacChatMessages, iacChatInput, iacChatLoading,
  iacChatEndRef, iacChatInputRef,
  onCopyWithFeedback, onToggleChat, onOpenChatWithMessage,
  onResetChat, onSendChat, onSetChatInput, onDownload,
  onPushPr,
}) {
  const safeIacFormat = iacFormat === 'bicep' ? 'bicep' : 'terraform';
  const [pushOpen, setPushOpen] = useState(false);
  const [repo, setRepo] = useState('');
  const [baseBranch, setBaseBranch] = useState('main');
  const [targetPath, setTargetPath] = useState('');
  const [githubToken, setGithubToken] = useState('');
  const [pushLoading, setPushLoading] = useState(false);
  const [pushError, setPushError] = useState('');
  const [pushResult, setPushResult] = useState(null);

  // Guard against double-click / double-submit on the IaC chat send button (#910)
  const pendingRef = useRef(false);
  const handleSendChat = useCallback(() => {
    if (pendingRef.current) return;
    pendingRef.current = true;
    Promise.resolve()
      .then(() => onSendChat())
      .finally(() => { pendingRef.current = false; });
  }, [onSendChat]);

  // Compute which lines are new/changed compared to previous version
  const changedLineSet = useMemo(() => {
    if (!previousIacCode || previousIacCode === iacCode) return new Set();
    const oldLines = previousIacCode.split('\n');
    const newLines = iacCode.split('\n');
    const oldSet = new Set(oldLines.map(l => l.trim()));
    const changed = new Set();
    newLines.forEach((line, i) => {
      if (!oldSet.has(line.trim()) && line.trim() !== '') changed.add(i);
    });
    return changed;
  }, [iacCode, previousIacCode]);

  // Memoize syntax highlighting — avoids per-line Prism.highlight + DOMPurify on every render (#219)
  const highlightedLines = useMemo(() => {
    const grammar = safeIacFormat === 'terraform' ? Prism.languages.hcl : Prism.languages.json;
    const lang = safeIacFormat === 'terraform' ? 'hcl' : 'json';
    return iacCode.split('\n').map((line) => {
      const rawHighlighted = grammar ? Prism.highlight(line || ' ', grammar, lang) : (line || ' ');
      return DOMPurify.sanitize(rawHighlighted, { ALLOWED_TAGS: ['span'], ALLOWED_ATTR: ['class'] });
    });
  }, [iacCode, safeIacFormat]);

  const handlePushSubmit = async (event) => {
    event.preventDefault();
    if (!onPushPr || !repo.trim()) return;
    setPushLoading(true);
    setPushError('');
    setPushResult(null);
    try {
      const result = await onPushPr({
        repo: repo.trim(),
        baseBranch: baseBranch.trim() || 'main',
        targetPath: targetPath.trim() || undefined,
        githubToken: githubToken.trim() || undefined,
      });
      setPushResult(result || null);
    } catch (err) {
      setPushError(err?.message || 'Failed to create GitHub PR');
    } finally {
      setPushLoading(false);
    }
  };

  const prUrl = pushResult?.pr_url || pushResult?.pull_request_url;

  return (
    <>
      {/* IaC Code */}
      <Card className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <FileCode className="w-6 h-6 text-cta" />
            <div>
              <h2 className="text-xl font-bold text-text-primary">
                {safeIacFormat === 'terraform' ? 'Terraform' : 'Bicep'} Code
              </h2>
              <p className="text-xs text-text-muted">{highlightedLines.length} lines generated</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={() => onCopyWithFeedback(iacCode, 'iac-code')} variant="ghost" size="sm" icon={copyFeedback['iac-code'] ? Check : FileText}>
              {copyFeedback['iac-code'] ? 'Copied!' : 'Copy'}
            </Button>
            <Button onClick={() => {
              const blob = new Blob([iacCode], { type: 'text/plain' });
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url; a.download = safeIacFormat === 'terraform' ? 'main.tf' : 'main.bicep'; a.click();
              URL.revokeObjectURL(url);
              onDownload?.();
            }} variant="secondary" size="sm" icon={Download}>Download</Button>
            <Button onClick={() => setPushOpen(value => !value)} variant={pushOpen ? 'primary' : 'secondary'} size="sm" icon={GitPullRequest}>
              Push PR
            </Button>
          </div>
        </div>
        {pushOpen && (
          <form onSubmit={handlePushSubmit} className="mb-4 rounded-lg border border-border bg-secondary/40 p-3">
            <div className="grid gap-2 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,0.8fr)_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
              <label className="flex flex-col gap-1 text-xs font-medium text-text-secondary">
                Repository
                <input
                  value={repo}
                  onChange={event => setRepo(event.target.value)}
                  placeholder="owner/repo"
                  className="h-9 rounded-lg border border-border bg-primary px-3 text-sm text-text-primary placeholder:text-text-muted focus:border-cta focus:outline-none focus:ring-2 focus:ring-cta/50"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs font-medium text-text-secondary">
                Base
                <input
                  value={baseBranch}
                  onChange={event => setBaseBranch(event.target.value)}
                  placeholder="main"
                  className="h-9 rounded-lg border border-border bg-primary px-3 text-sm text-text-primary placeholder:text-text-muted focus:border-cta focus:outline-none focus:ring-2 focus:ring-cta/50"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs font-medium text-text-secondary">
                Path
                <input
                  value={targetPath}
                  onChange={event => setTargetPath(event.target.value)}
                  placeholder={safeIacFormat === 'terraform' ? 'infra/main.tf' : 'infra/main.bicep'}
                  className="h-9 rounded-lg border border-border bg-primary px-3 text-sm text-text-primary placeholder:text-text-muted focus:border-cta focus:outline-none focus:ring-2 focus:ring-cta/50"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs font-medium text-text-secondary">
                Token
                <input
                  type="password"
                  value={githubToken}
                  onChange={event => setGithubToken(event.target.value)}
                  placeholder="server default"
                  className="h-9 rounded-lg border border-border bg-primary px-3 text-sm text-text-primary placeholder:text-text-muted focus:border-cta focus:outline-none focus:ring-2 focus:ring-cta/50"
                />
              </label>
              <Button type="submit" variant="primary" size="sm" loading={pushLoading} disabled={!repo.trim()}>
                Create PR
              </Button>
            </div>
            {(pushError || prUrl) && (
              <div className="mt-3 text-xs">
                {pushError && <p className="text-danger">{pushError}</p>}
                {prUrl && (
                  <a href={prUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-cta hover:text-cta-hover">
                    <GitPullRequest className="h-3.5 w-3.5" aria-hidden="true" />
                    Open pull request
                  </a>
                )}
              </div>
            )}
          </form>
        )}
        <div className="bg-surface rounded-lg border border-border overflow-auto max-h-[600px]">
          <pre className="p-4 text-xs leading-relaxed">
            <code>
              {highlightedLines.map((html, i) => (
                <div key={i} className={`flex ${changedLineSet.has(i) ? 'bg-cta/10 border-l-2 border-cta' : ''}`}>
                  <span className="inline-block w-10 text-right pr-4 text-text-muted select-none opacity-50">{i + 1}</span>
                  <span dangerouslySetInnerHTML={{ __html: html }} />
                </div>
              ))}
            </code>
          </pre>
        </div>
      </Card>

      {/* IaC Chat Panel */}
      <ContextualHint id="iac-chat" content="Ask the AI to modify your infrastructure code" position="top">
      <Card className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-cta/15 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-cta" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-text-primary">IaC Assistant</h3>
              <p className="text-[10px] text-text-muted">Ask AI to add services, networking, storage & more</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {iacChatOpen && (
              <button onClick={onResetChat} className="p-1.5 hover:bg-surface rounded-lg transition-colors cursor-pointer" title="Reset chat">
                <RotateCcw className="w-3.5 h-3.5 text-text-muted" />
              </button>
            )}
            <button onClick={onToggleChat} className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer flex items-center gap-1.5 ${
              iacChatOpen ? 'bg-cta/15 text-cta border border-cta/30' : 'bg-surface border border-border text-text-secondary hover:border-cta/40 hover:text-cta'
            }`}>
              <Bot className="w-3.5 h-3.5" />
              {iacChatOpen ? 'Close Chat' : 'Open Chat'}
            </button>
          </div>
        </div>

        {!iacChatOpen && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            {QUICK_ACTIONS.map((q, i) => (
              <button key={i} onClick={() => onOpenChatWithMessage(q.msg)} className="px-3 py-2 bg-surface border border-border rounded-lg text-[11px] text-text-secondary hover:border-cta/40 hover:text-cta transition-all cursor-pointer text-left flex items-center gap-1.5">
                <Plus className="w-3 h-3 shrink-0" />
                {q.label}
              </button>
            ))}
          </div>
        )}

        {iacChatOpen && (
          <div className="border border-border rounded-xl overflow-hidden bg-primary" role="region" aria-label="IaC Chat Assistant">
            <div className="h-80 overflow-y-auto px-4 py-3 space-y-3" role="log" aria-live="polite">
              {iacChatMessages.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[88%] px-3 py-2 rounded-xl text-sm ${
                    msg.role === 'user' ? 'bg-cta/15 text-text-primary rounded-br-sm' : 'bg-secondary text-text-primary rounded-bl-sm'
                  }`}>
                    {msg.content.split('\n').map((line, li) => (
                      <p key={li} className={li > 0 ? 'mt-1.5' : ''}>
                        {line.split(/(\*\*.*?\*\*)/).map((part, pi) => {
                          const bold = part.match(/^\*\*(.*?)\*\*$/);
                          if (bold) return <strong key={pi} className="font-semibold">{bold[1]}</strong>;
                          return part;
                        })}
                      </p>
                    ))}
                    {msg.changes && msg.changes.length > 0 && (
                      <div className="mt-2 pt-2 border-t border-border/50">
                        <p className="text-[10px] font-semibold text-cta mb-1 flex items-center gap-1">
                          <CheckCircle className="w-3 h-3" /> Changes applied:
                        </p>
                        <ul className="space-y-0.5">
                          {msg.changes.map((c, ci) => (
                            <li key={ci} className="text-[10px] text-text-muted flex items-start gap-1"><span className="text-cta mt-0.5">+</span> {toRenderableString(c)}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {msg.services && msg.services.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {msg.services.map((s, si) => (
                          <span key={si} className="inline-flex items-center px-1.5 py-0.5 text-[9px] font-medium rounded bg-cta/10 text-cta border border-cta/20">{toRenderableString(s)}</span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ))}
              {iacChatLoading && (
                <div className="flex justify-start">
                  <div className="bg-secondary px-3 py-2 rounded-xl rounded-bl-sm flex items-center gap-2">
                    <Loader2 className="w-4 h-4 text-cta animate-spin" />
                    <span className="text-xs text-text-muted">Modifying code...</span>
                  </div>
                </div>
              )}
              <div ref={iacChatEndRef} />
            </div>

            <div className="px-3 py-3 border-t border-border bg-secondary/50">
              <div className="flex flex-wrap gap-1.5 mb-2">
                {CHAT_QUICK_BUTTONS.map((q, i) => (
                  <button key={i} onClick={() => { onSetChatInput(q.msg); iacChatInputRef.current?.focus(); }}
                    className="px-2 py-0.5 text-[10px] rounded-full border border-border text-text-muted hover:border-cta/40 hover:text-cta transition-colors cursor-pointer">
                    + {q.label}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <input ref={iacChatInputRef} type="text" value={iacChatInput}
                  onChange={e => onSetChatInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendChat(); } }}
                  placeholder="Ask to add VNet, storage, IPs, naming conventions..."
                  aria-label="IaC chat message"
                  className="flex-1 px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50 transition-colors"
                />
                <button onClick={handleSendChat} disabled={!iacChatInput.trim() || iacChatLoading}
                  aria-label="Send message"
                  className="p-2 rounded-lg bg-cta hover:bg-cta-hover text-surface disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors">
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        )}
      </Card>
      </ContextualHint>
    </>
  );
}
