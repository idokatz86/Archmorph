import React, { useMemo } from 'react';
import Prism from 'prismjs';
import DOMPurify from 'dompurify';
import 'prismjs/components/prism-hcl';
import 'prismjs/components/prism-json';
import {
  FileCode, FileText, Download, Check, Sparkles, Bot,
  Plus, RotateCcw, Send, Loader2, CheckCircle,
} from 'lucide-react';
import { Button, Card } from '../ui';

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
  iacCode, iacFormat, copyFeedback,
  iacChatOpen, iacChatMessages, iacChatInput, iacChatLoading,
  iacChatEndRef, iacChatInputRef,
  onCopyWithFeedback, onToggleChat, onOpenChatWithMessage,
  onResetChat, onSendChat, onSetChatInput,
}) {
  // Memoize syntax highlighting — avoids per-line Prism.highlight + DOMPurify on every render (#219)
  const highlightedLines = useMemo(() => {
    const grammar = iacFormat === 'terraform' ? Prism.languages.hcl : Prism.languages.json;
    const lang = iacFormat === 'terraform' ? 'hcl' : 'json';
    return iacCode.split('\n').map((line) => {
      const rawHighlighted = grammar ? Prism.highlight(line || ' ', grammar, lang) : (line || ' ');
      return DOMPurify.sanitize(rawHighlighted, { ALLOWED_TAGS: ['span'], ALLOWED_ATTR: ['class'] });
    });
  }, [iacCode, iacFormat]);

  return (
    <>
      {/* IaC Code */}
      <Card className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <FileCode className="w-6 h-6 text-cta" />
            <div>
              <h2 className="text-xl font-bold text-text-primary">
                {iacFormat === 'terraform' ? 'Terraform' : 'Bicep'} Code
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
              a.href = url; a.download = iacFormat === 'terraform' ? 'main.tf' : 'main.bicep'; a.click();
              URL.revokeObjectURL(url);
            }} variant="secondary" size="sm" icon={Download}>Download</Button>
          </div>
        </div>
        <div className="bg-surface rounded-lg border border-border overflow-auto max-h-[600px]">
          <pre className="p-4 text-xs leading-relaxed">
            <code>
              {highlightedLines.map((html, i) => (
                <div key={i} className="flex">
                  <span className="inline-block w-10 text-right pr-4 text-text-muted select-none opacity-50">{i + 1}</span>
                  <span dangerouslySetInnerHTML={{ __html: html }} />
                </div>
              ))}
            </code>
          </pre>
        </div>
      </Card>

      {/* IaC Chat Panel */}
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
          <div className="border border-border rounded-xl overflow-hidden bg-primary">
            <div className="h-80 overflow-y-auto px-4 py-3 space-y-3">
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
                            <li key={ci} className="text-[10px] text-text-muted flex items-start gap-1"><span className="text-cta mt-0.5">+</span> {c}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {msg.services && msg.services.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {msg.services.map((s, si) => (
                          <span key={si} className="inline-flex items-center px-1.5 py-0.5 text-[9px] font-medium rounded bg-cta/10 text-cta border border-cta/20">{s}</span>
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
                  onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSendChat(); } }}
                  placeholder="Ask to add VNet, storage, IPs, naming conventions..."
                  className="flex-1 px-3 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-cta/50 transition-colors"
                />
                <button onClick={onSendChat} disabled={!iacChatInput.trim() || iacChatLoading}
                  className="p-2 rounded-lg bg-cta hover:bg-cta-hover text-surface disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer transition-colors">
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        )}
      </Card>
    </>
  );
}
