import React, { useState, useEffect, useRef } from 'react';
import { Users, Copy, Check, Crown, Eye, Edit3, Clock, Plus, Link2, MessageCircle } from 'lucide-react';
import { API_BASE } from '../constants';

const ROLES = {
  owner: { label: 'Owner', color: 'bg-amber-500/20 text-amber-400', icon: Crown },
  editor: { label: 'Editor', color: 'bg-cta/20 text-cta', icon: Edit3 },
  viewer: { label: 'Viewer', color: 'bg-text-muted/20 text-text-muted', icon: Eye },
};

const SAMPLE_PARTICIPANTS = [
  { id: 1, name: 'You', avatar: null, role: 'owner', online: true },
  { id: 2, name: 'Sarah K.', avatar: null, role: 'editor', online: true },
  { id: 3, name: 'James L.', avatar: null, role: 'editor', online: false },
  { id: 4, name: 'Mika T.', avatar: null, role: 'viewer', online: true },
];

const SAMPLE_ACTIVITY = [
  { id: 1, user: 'Sarah K.', action: 'updated', target: 'API Gateway config', time: '2m ago', icon: Edit3 },
  { id: 2, user: 'You', action: 'added', target: 'Redis cache layer', time: '5m ago', icon: Plus },
  { id: 3, user: 'James L.', action: 'commented on', target: 'VPC peering', time: '12m ago', icon: MessageCircle },
  { id: 4, user: 'Mika T.', action: 'viewed', target: 'Migration plan', time: '18m ago', icon: Eye },
  { id: 5, user: 'Sarah K.', action: 'added', target: 'Lambda → Azure Functions mapping', time: '25m ago', icon: Plus },
];

function getInitials(name) {
  return name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);
}

export default function CollabWorkspace() {
  const [participants] = useState(SAMPLE_PARTICIPANTS);
  const [activity] = useState(SAMPLE_ACTIVITY);
  const [shareCode] = useState('ARCH-7X9K2M');
  const [copied, setCopied] = useState(false);
  const timerRef = useRef(null);

  useEffect(() => () => clearTimeout(timerRef.current), []);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(shareCode);
    } catch {
      /* clipboard not available */
    }
    setCopied(true);
    timerRef.current = setTimeout(() => setCopied(false), 2000);
  };

  const onlineCount = participants.filter(p => p.online).length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-cta/15 flex items-center justify-center">
            <Users className="w-5 h-5 text-cta" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-text-primary">Collaboration</h2>
            <p className="text-xs text-text-muted">{onlineCount} online now</p>
          </div>
        </div>
      </div>

      {/* Share Code */}
      <div className="bg-secondary rounded-xl p-4 border border-border">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium text-text-muted uppercase tracking-wider">Share Code</span>
          <Link2 className="w-3.5 h-3.5 text-text-muted" />
        </div>
        <div className="flex items-center gap-2">
          <code className="flex-1 bg-surface rounded-lg px-3 py-2 text-sm font-mono text-cta tracking-widest">
            {shareCode}
          </code>
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-cta/10 text-cta text-sm font-medium hover:bg-cta/20 transition-colors cursor-pointer"
            aria-label="Copy share code"
          >
            {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      </div>

      {/* Participants */}
      <div className="bg-secondary rounded-xl border border-border overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <h3 className="text-sm font-semibold text-text-primary">Participants ({participants.length})</h3>
        </div>
        <ul className="divide-y divide-border" role="list">
          {participants.map(p => {
            const role = ROLES[p.role];
            const RoleIcon = role.icon;
            return (
              <li key={p.id} className="px-4 py-3 flex items-center gap-3 hover:bg-surface/50 transition-colors">
                <div className="relative">
                  <div className="w-8 h-8 rounded-full bg-cta/20 flex items-center justify-center text-xs font-bold text-cta">
                    {getInitials(p.name)}
                  </div>
                  <span
                    className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-secondary ${p.online ? 'bg-emerald-400' : 'bg-text-muted/40'}`}
                    aria-label={p.online ? 'Online' : 'Offline'}
                  />
                </div>
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium text-text-primary truncate block">{p.name}</span>
                </div>
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${role.color}`}>
                  <RoleIcon className="w-3 h-3" />
                  {role.label}
                </span>
              </li>
            );
          })}
        </ul>
      </div>

      {/* Activity Feed */}
      <div className="bg-secondary rounded-xl border border-border overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <h3 className="text-sm font-semibold text-text-primary">Recent Activity</h3>
        </div>
        <ul className="divide-y divide-border" role="list">
          {activity.map(a => {
            const Icon = a.icon;
            return (
              <li key={a.id} className="px-4 py-3 flex items-start gap-3">
                <div className="mt-0.5 w-7 h-7 rounded-lg bg-cta/10 flex items-center justify-center shrink-0">
                  <Icon className="w-3.5 h-3.5 text-cta" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-text-primary">
                    <span className="font-medium">{a.user}</span>{' '}
                    <span className="text-text-muted">{a.action}</span>{' '}
                    <span className="font-medium">{a.target}</span>
                  </p>
                  <p className="text-xs text-text-muted mt-0.5 flex items-center gap-1">
                    <Clock className="w-3 h-3" /> {a.time}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
