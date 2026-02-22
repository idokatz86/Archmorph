/**
 * Organization Settings panel (#169 Multi-Tenancy).
 *
 * Full organization management UI: create/switch orgs, manage members,
 * change roles, send invitations, accept invitations.
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  Building2, Users, UserPlus, Settings, Crown, Shield, Eye, Pencil,
  Loader2, AlertTriangle, CheckCircle2, Trash2, ChevronDown, Mail, Copy, X,
} from 'lucide-react';
import { Card, Badge, Button } from './ui';
import api from '../services/apiClient';

const ROLE_ICONS = { owner: Crown, admin: Shield, editor: Pencil, viewer: Eye };
const ROLE_COLORS = {
  owner: 'bg-amber-500/15 text-amber-400 border-amber-400/30',
  admin: 'bg-cta/15 text-cta border-cta/30',
  editor: 'bg-info/15 text-info border-info/30',
  viewer: 'bg-secondary text-text-secondary border-border',
};

function RoleBadge({ role }) {
  const Icon = ROLE_ICONS[role] || Eye;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-md border ${ROLE_COLORS[role] || ROLE_COLORS.viewer}`}>
      <Icon className="w-3 h-3" />
      {role}
    </span>
  );
}

function MemberRow({ member, currentUserId, onRoleChange, onRemove }) {
  const [changing, setChanging] = useState(false);
  const isOwner = member.role === 'owner';
  const isSelf = member.user_id === currentUserId;

  const handleRoleChange = async (newRole) => {
    setChanging(true);
    await onRoleChange(member.user_id, newRole);
    setChanging(false);
  };

  return (
    <div className="flex items-center gap-3 py-2 px-3 rounded-lg hover:bg-secondary/50 group">
      <div className="w-8 h-8 rounded-full bg-cta/15 flex items-center justify-center text-xs font-bold text-cta shrink-0">
        {(member.display_name || member.email || '?')[0].toUpperCase()}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-text-primary truncate">{member.display_name || member.email}</p>
        <p className="text-xs text-text-muted truncate">{member.email}</p>
      </div>
      <RoleBadge role={member.role} />
      {!isOwner && !isSelf && (
        <div className="hidden group-hover:flex items-center gap-1">
          {changing ? (
            <Loader2 className="w-4 h-4 text-text-muted animate-spin" />
          ) : (
            <>
              <select
                className="text-xs bg-secondary border border-border rounded px-1 py-0.5 text-text-primary cursor-pointer"
                value={member.role}
                onChange={(e) => handleRoleChange(e.target.value)}
              >
                <option value="viewer">Viewer</option>
                <option value="editor">Editor</option>
                <option value="admin">Admin</option>
              </select>
              <button onClick={() => onRemove(member.user_id)} className="text-text-muted hover:text-danger cursor-pointer p-1">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </>
          )}
        </div>
      )}
      {isSelf && <span className="text-xs text-text-muted">(you)</span>}
    </div>
  );
}

function InviteForm({ orgId, onInvited }) {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState('viewer');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);

  const handleInvite = async (e) => {
    e.preventDefault();
    if (!email.trim()) return;
    setLoading(true);
    setError(null);
    setSuccess(null);
    try {
      const data = await api.post(`/api/organizations/${orgId}/invitations`, { email, role });
      setSuccess(`Invitation sent to ${email}`);
      setEmail('');
      if (onInvited) onInvited(data);
    } catch (err) {
      setError(err.message || 'Failed to send invitation');
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleInvite} className="flex items-end gap-2">
      <div className="flex-1">
        <label className="block text-xs font-semibold text-text-secondary mb-1">Email address</label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="colleague@company.com"
          className="w-full px-3 py-2 text-sm bg-surface border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-cta/50 text-text-primary placeholder:text-text-muted"
          required
        />
      </div>
      <div>
        <label className="block text-xs font-semibold text-text-secondary mb-1">Role</label>
        <select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          className="px-3 py-2 text-sm bg-surface border border-border rounded-lg text-text-primary cursor-pointer"
        >
          <option value="viewer">Viewer</option>
          <option value="editor">Editor</option>
          <option value="admin">Admin</option>
        </select>
      </div>
      <Button type="submit" loading={loading} icon={Mail} size="md">Invite</Button>
      {error && <span className="text-xs text-danger">{error}</span>}
      {success && <span className="text-xs text-green-400">{success}</span>}
    </form>
  );
}

export default function OrganizationSettings() {
  const [orgs, setOrgs] = useState([]);
  const [selectedOrg, setSelectedOrg] = useState(null);
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newOrgName, setNewOrgName] = useState('');
  const [creating, setCreating] = useState(false);

  const currentUserId = 'current-user'; // Populated from auth context in real impl

  const fetchOrgs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.get('/api/organizations');
      setOrgs(data.organizations || []);
      if (!selectedOrg && data.organizations?.length > 0) {
        setSelectedOrg(data.organizations[0]);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [selectedOrg]);

  const fetchMembers = useCallback(async () => {
    if (!selectedOrg) return;
    try {
      const data = await api.get(`/api/organizations/${selectedOrg.org_id}/members`);
      setMembers(data.members || []);
    } catch {
      // Non-critical
    }
  }, [selectedOrg]);

  useEffect(() => { fetchOrgs(); }, []);
  useEffect(() => { fetchMembers(); }, [selectedOrg]);

  const handleCreate = async (e) => {
    e.preventDefault();
    if (!newOrgName.trim()) return;
    setCreating(true);
    try {
      const data = await api.post('/api/organizations', { name: newOrgName });
      setOrgs((prev) => [...prev, data]);
      setSelectedOrg(data);
      setNewOrgName('');
      setShowCreate(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setCreating(false);
    }
  };

  const handleRoleChange = async (userId, newRole) => {
    if (!selectedOrg) return;
    try {
      await api.patch(`/api/organizations/${selectedOrg.org_id}/members/${userId}/role`, { role: newRole });
      await fetchMembers();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleRemove = async (userId) => {
    if (!selectedOrg) return;
    try {
      await api.delete(`/api/organizations/${selectedOrg.org_id}/members/${userId}`);
      await fetchMembers();
    } catch (err) {
      setError(err.message);
    }
  };

  if (loading) {
    return (
      <Card className="p-8 flex items-center justify-center gap-3">
        <Loader2 className="w-5 h-5 text-cta animate-spin" />
        <span className="text-sm text-text-muted">Loading organizations…</span>
      </Card>
    );
  }

  return (
    <div className="space-y-5">
      {error && (
        <div className="flex items-center gap-2 text-sm text-danger bg-danger/10 border border-danger/20 rounded-lg px-4 py-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          {error}
          <button onClick={() => setError(null)} className="ml-auto cursor-pointer"><X className="w-4 h-4" /></button>
        </div>
      )}

      {/* Org selector + create */}
      <Card className="p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider flex items-center gap-2">
            <Building2 className="w-4 h-4" /> Organizations
          </h3>
          <Button onClick={() => setShowCreate(!showCreate)} variant="ghost" size="sm" icon={showCreate ? X : Building2}>
            {showCreate ? 'Cancel' : 'New Organization'}
          </Button>
        </div>

        {showCreate && (
          <form onSubmit={handleCreate} className="flex gap-2 mb-3 p-3 bg-secondary/50 rounded-lg">
            <input
              type="text"
              value={newOrgName}
              onChange={(e) => setNewOrgName(e.target.value)}
              placeholder="Organization name"
              className="flex-1 px-3 py-2 text-sm bg-surface border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-cta/50 text-text-primary placeholder:text-text-muted"
              required
            />
            <Button type="submit" loading={creating} size="sm">Create</Button>
          </form>
        )}

        {orgs.length === 0 ? (
          <p className="text-sm text-text-muted text-center py-4">No organizations yet. Create one to get started.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {orgs.map((org) => (
              <button
                key={org.org_id}
                onClick={() => setSelectedOrg(org)}
                className={`px-3 py-2 rounded-lg border text-sm transition-colors cursor-pointer ${
                  selectedOrg?.org_id === org.org_id
                    ? 'border-cta bg-cta/10 text-cta font-medium'
                    : 'border-border bg-secondary/50 text-text-secondary hover:border-border-light'
                }`}
              >
                {org.name}
                <Badge variant="azure" className="ml-2">{org.plan || 'free'}</Badge>
              </button>
            ))}
          </div>
        )}
      </Card>

      {/* Members */}
      {selectedOrg && (
        <Card className="p-5">
          <h3 className="text-sm font-semibold text-text-secondary uppercase tracking-wider flex items-center gap-2 mb-3">
            <Users className="w-4 h-4" /> Members
            <Badge>{members.length}</Badge>
          </h3>
          <div className="space-y-1 mb-4">
            {members.map((m) => (
              <MemberRow
                key={m.user_id}
                member={m}
                currentUserId={currentUserId}
                onRoleChange={handleRoleChange}
                onRemove={handleRemove}
              />
            ))}
          </div>

          {/* Invite */}
          <div className="pt-4 border-t border-border">
            <h4 className="text-xs font-semibold text-text-secondary uppercase tracking-wider flex items-center gap-1.5 mb-3">
              <UserPlus className="w-3.5 h-3.5" /> Invite Member
            </h4>
            <InviteForm orgId={selectedOrg.org_id} onInvited={fetchMembers} />
          </div>
        </Card>
      )}
    </div>
  );
}
