/**
 * ProfilePage — User profile management modal (Issue #247).
 *
 * Displays a form for editing display name, company, role, source cloud,
 * IaC format preferences. Includes account deletion with confirmation.
 */

import React, { useState, useEffect } from 'react';
import { X, Save, Trash2, Loader2, AlertTriangle, CheckCircle } from 'lucide-react';
import { useAuth } from './AuthProvider';
import api, { ApiError } from '../../services/apiClient';
import { Input, Select } from '../ui';
import { Dialog, DialogTitle } from '../../shared/ui';

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

    api.get('/me/profile')
      .then((data) => {
        setForm({
          display_name: data.display_name || data.name || '',
          company: data.company || '',
          role: data.role || null,
          preferred_source_cloud: data.preferred_source_cloud || null,
          preferred_iac_format: normalizeIacFormat(data.preferred_iac_format),
        });
      })
      .catch(() => {});
  }, [isOpen, isAuthenticated]);

  const handleSave = async () => {
    setSaving(true);
    setMessage(null);
    try {
      await api.put('/me/profile', form);
      setMessage({ type: 'success', text: 'Profile saved successfully' });
    } catch (error) {
      const text = error instanceof ApiError && error.status !== 0
        ? error.rawMessage
        : 'Network error';
      setMessage({ type: 'error', text: text || 'Failed to save profile' });
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await api.delete('/me/account');
      logout();
      onClose();
    } catch (error) {
      setMessage({
        type: 'error',
        text: error instanceof ApiError && error.status !== 0
          ? 'Failed to delete account'
          : 'Network error',
      });
    } finally {
      setDeleting(false);
      setDeleteConfirm(false);
    }
  };

  return (
    <Dialog
      open={isOpen}
      onClose={onClose}
      containerClassName="fixed inset-0 z-[100] flex items-center justify-center overflow-y-auto p-4 sm:p-6 pt-[max(1rem,env(safe-area-inset-top))] pb-[max(1rem,env(safe-area-inset-bottom))]"
      backdropClassName="fixed inset-0 bg-black/60 backdrop-blur-sm"
      backdropTestId="profile-backdrop"
      className="relative z-10 my-auto bg-surface border border-border rounded-2xl shadow-2xl w-full max-w-lg max-h-[calc(100dvh-2rem)] overflow-y-auto"
    >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <DialogTitle className="text-lg font-semibold text-text-primary">Profile Settings</DialogTitle>
          <button onClick={onClose} className="p-1 hover:bg-secondary rounded-lg transition-colors cursor-pointer" aria-label="Close profile settings">
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
          <Input
            id="profile-display-name"
            label="Display Name"
            type="text"
            value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            maxLength={200}
          />

          {/* Company */}
          <Input
            id="profile-company"
            label="Company"
            type="text"
            value={form.company}
            onChange={(e) => setForm({ ...form, company: e.target.value })}
            maxLength={200}
            placeholder="Your organization"
          />

          {/* Dropdowns */}
          <Select
            id="profile-role"
            label="Role"
            value={form.role || ''}
            onChange={(e) => setForm({ ...form, role: e.target.value || null })}
            options={ROLES}
            placeholder="Select your role"
          />
          <Select
            id="profile-source-cloud"
            label="Source Cloud"
            value={form.preferred_source_cloud || ''}
            onChange={(e) => setForm({ ...form, preferred_source_cloud: e.target.value || null })}
            options={SOURCE_CLOUDS}
            placeholder="Primary cloud you're migrating from"
          />
          <Select
            id="profile-iac-format"
            label="IaC Format"
            value={form.preferred_iac_format || ''}
            onChange={(e) => setForm({ ...form, preferred_iac_format: e.target.value || null })}
            options={IAC_FORMATS}
            placeholder="Preferred Infrastructure as Code format"
          />

          {/* Status message */}
          {message && (
            <div
              role={message.type === 'success' ? 'status' : 'alert'}
              className={`flex items-center gap-2 text-sm px-3 py-2 rounded-lg ${message.type === 'success' ? 'bg-cta/10 text-cta' : 'bg-danger/10 text-danger'}`}
            >
              {message.type === 'success' ? <CheckCircle className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
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
    </Dialog>
  );
}
