/**
 * ProfilePage — User profile management modal (Issue #247).
 *
 * Displays a form for editing display name, company, role, source cloud,
 * IaC format preferences. Includes account deletion with confirmation.
 */

import React, { useState, useEffect } from 'react';
import { X, Save, Trash2, Loader2, AlertTriangle } from 'lucide-react';
import { useAuth } from './AuthProvider';
import { API_BASE } from '../../constants';

const ROLES = [
  { value: 'cloud_architect', label: 'Cloud Architect' },
  { value: 'devops', label: 'DevOps Engineer' },
  { value: 'developer', label: 'Developer' },
  { value: 'manager', label: 'Manager' },
  { value: 'other', label: 'Other' },
];

const SOURCE_CLOUDS = [
  { value: 'aws', label: 'AWS' },
  { value: 'gcp', label: 'GCP' },
  { value: 'multi-cloud', label: 'Multi-Cloud' },
];

const IAC_FORMATS = [
  { value: 'terraform', label: 'Terraform' },
  { value: 'bicep', label: 'Bicep' },
];

const normalizeIacFormat = (format) => (format === 'terraform' || format === 'bicep' ? format : null);

function Select({ label, value, onChange, options, placeholder }) {
  return (
    <div>
      <label className="block text-xs font-medium text-text-muted mb-1">{label}</label>
      <select
        value={value || ''}
        onChange={(e) => onChange(e.target.value || null)}
        className="w-full px-3 py-2 text-sm bg-secondary border border-border rounded-lg text-text-primary focus:outline-none focus:ring-1 focus:ring-cta"
      >
        <option value="">{placeholder || 'Select...'}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}

export default function ProfilePage({ isOpen, onClose }) {
  const { user, isAuthenticated, logout } = useAuth();
  const [form, setForm] = useState({
    display_name: '',
    company: '',
    role: null,
    preferred_source_cloud: null,
    preferred_iac_format: null,
  });
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [message, setMessage] = useState(null);

  // Load profile on open
  useEffect(() => {
    if (!isOpen || !isAuthenticated) return;

    const token = localStorage.getItem('archmorph_session_token');
    fetch(`${API_BASE}/me/profile`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data) {
          setForm({
            display_name: data.display_name || data.name || '',
            company: data.company || '',
            role: data.role || null,
            preferred_source_cloud: data.preferred_source_cloud || null,
            preferred_iac_format: normalizeIacFormat(data.preferred_iac_format),
          });
        }
      })
      .catch(() => {});
  }, [isOpen, isAuthenticated]);

  if (!isOpen) return null;

  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const token = localStorage.getItem('archmorph_session_token');
      const res = await fetch(`${API_BASE}/me/profile`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(form),
      });
      if (res.ok) {
        setMessage({ type: 'success', text: 'Profile saved successfully' });
      } else {
        const data = await res.json().catch(() => null);
        setMessage({ type: 'error', text: data?.error?.message || 'Failed to save profile' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Network error' });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      const token = localStorage.getItem('archmorph_session_token');
      const res = await fetch(`${API_BASE}/me/account`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.ok) {
        logout();
        onClose();
      } else {
        setMessage({ type: 'error', text: 'Failed to delete account' });
      }
    } catch {
      setMessage({ type: 'error', text: 'Network error' });
    } finally {
      setDeleting(false);
      setDeleteConfirm(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="bg-surface border border-border rounded-2xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="text-lg font-semibold text-text-primary">Profile Settings</h2>
          <button onClick={onClose} className="p-1 hover:bg-secondary rounded-lg transition-colors cursor-pointer">
            <X className="w-5 h-5 text-text-muted" />
          </button>
        </div>

        {/* Form */}
        <div className="px-6 py-5 space-y-4">
          {/* User info header */}
          {user && (
            <div className="flex items-center gap-3 pb-4 border-b border-border">
              {user.avatar_url ? (
                <img src={user.avatar_url} alt="" className="w-12 h-12 rounded-full border border-border" />
              ) : (
                <div className="w-12 h-12 rounded-full bg-cta/20 text-cta flex items-center justify-center text-lg font-bold">
                  {(user.name || user.email || '?')[0].toUpperCase()}
                </div>
              )}
              <div>
                <p className="font-medium text-text-primary">{user.name || user.email || 'User'}</p>
                <p className="text-xs text-text-muted">{user.email}</p>
                <p className="text-[10px] text-text-muted mt-0.5 uppercase tracking-wider">
                  {user.provider} &middot; Free access
                </p>
              </div>
            </div>
          )}

          {/* Display name */}
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">Display Name</label>
            <input
              type="text"
              value={form.display_name}
              onChange={(e) => setForm({ ...form, display_name: e.target.value })}
              className="w-full px-3 py-2 text-sm bg-secondary border border-border rounded-lg text-text-primary focus:outline-none focus:ring-1 focus:ring-cta"
              maxLength={200}
            />
          </div>

          {/* Company */}
          <div>
            <label className="block text-xs font-medium text-text-muted mb-1">Company</label>
            <input
              type="text"
              value={form.company}
              onChange={(e) => setForm({ ...form, company: e.target.value })}
              className="w-full px-3 py-2 text-sm bg-secondary border border-border rounded-lg text-text-primary focus:outline-none focus:ring-1 focus:ring-cta"
              maxLength={200}
              placeholder="Your organization"
            />
          </div>

          {/* Dropdowns */}
          <Select label="Role" value={form.role} onChange={(v) => setForm({ ...form, role: v })} options={ROLES} placeholder="Select your role" />
          <Select label="Source Cloud" value={form.preferred_source_cloud} onChange={(v) => setForm({ ...form, preferred_source_cloud: v })} options={SOURCE_CLOUDS} placeholder="Primary cloud you're migrating from" />
          <Select label="IaC Format" value={form.preferred_iac_format} onChange={(v) => setForm({ ...form, preferred_iac_format: v })} options={IAC_FORMATS} placeholder="Preferred Infrastructure as Code format" />

          {/* Status message */}
          {message && (
            <div className={`text-sm px-3 py-2 rounded-lg ${message.type === 'success' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
              {message.text}
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="px-6 py-4 border-t border-border flex items-center justify-between">
          <div>
            {!deleteConfirm ? (
              <button
                onClick={() => setDeleteConfirm(true)}
                className="flex items-center gap-1.5 text-sm text-danger hover:bg-danger/10 px-3 py-1.5 rounded-lg transition-colors cursor-pointer"
              >
                <Trash2 className="w-4 h-4" />
                Delete Account
              </button>
            ) : (
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-danger" />
                <span className="text-xs text-danger">This is permanent!</span>
                <button
                  onClick={handleDelete}
                  disabled={deleting}
                  className="text-xs px-2 py-1 rounded bg-danger text-white hover:bg-danger/80 transition-colors cursor-pointer disabled:opacity-50"
                >
                  {deleting ? 'Deleting...' : 'Confirm Delete'}
                </button>
                <button
                  onClick={() => setDeleteConfirm(false)}
                  className="text-xs px-2 py-1 text-text-muted hover:text-text-primary cursor-pointer"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>

          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 px-4 py-2 bg-cta text-surface text-sm font-medium rounded-lg hover:bg-cta/90 transition-colors cursor-pointer disabled:opacity-50"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
