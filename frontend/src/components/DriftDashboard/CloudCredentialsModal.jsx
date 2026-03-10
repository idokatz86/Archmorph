import React, { useState } from 'react';
import api from '../../services/apiClient';

export function CloudCredentialsModal({ provider, onClose, onSuccess }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [awsKey, setAwsKey] = useState("");
  const [awsSecret, setAwsSecret] = useState("");

  const [azureClient, setAzureClient] = useState("");
  const [azureSecret, setAzureSecret] = useState("");
  const [azureTenant, setAzureTenant] = useState("");
  const [azureSub, setAzureSub] = useState("");

  const [gcpJson, setGcpJson] = useState("");

  const handleConnect = async () => {
    setLoading(true);
    setError(null);
    try {
      // 1. Get an anonymous session token
      const authRes = await api.post('/auth/login', {
        provider: 'anonymous',
        token: 'none'
      });
      const sessionToken = authRes.session_token;

      // 2. Store credentials using this token
      let payload = {};
      let endpoint = `/credentials/${provider}`;
      if (provider === 'aws') {
        payload = { auth_method: 'access_key', access_key_id: awsKey, secret_access_key: awsSecret };
      } else if (provider === 'azure') {
        payload = { auth_method: 'service_principal', client_id: azureClient, client_secret: azureSecret, tenant_id: azureTenant, subscription_id: azureSub };
      } else if (provider === 'gcp') {
        try {
            payload = { auth_method: 'service_account_json', service_account_json: JSON.parse(gcpJson) };
        } catch(e) {
            throw new Error("Invalid GCP Service Account JSON.");
        }
      }

      await api.auth('POST', endpoint, { token: sessionToken, body: payload });
      
      // Call success callback with token
      onSuccess(sessionToken);

    } catch (err) {
      setError(err?.message || "Failed to validate credentials.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 text-left">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md overflow-hidden relative">
        <div className="px-6 py-4 border-b">
          <h3 className="text-lg font-semibold text-slate-800">
            Connect {provider.toUpperCase()} Environment
          </h3>
          <p className="text-sm text-slate-500 mt-1">Provide read-only credentials to scan your cloud infrastructure.</p>
        </div>

        <div className="p-6 space-y-4 max-h-[80vh] overflow-y-auto">
          {provider === 'aws' && (
            <>
              <div>
                <label className="block text-sm font-medium mb-1 text-slate-700">Access Key ID</label>
                <input value={awsKey} onChange={e => setAwsKey(e.target.value)} className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500" placeholder="AKIA..." />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1 text-slate-700">Secret Access Key</label>
                <input type="password" value={awsSecret} onChange={e => setAwsSecret(e.target.value)} className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500" placeholder="••••••••" />
              </div>
            </>
          )}

          {provider === 'azure' && (
            <>
              <div>
                <label className="block text-sm font-medium mb-1 text-slate-700">Client ID (App ID)</label>
                <input value={azureClient} onChange={e => setAzureClient(e.target.value)} className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500" placeholder="00000000-0000-0000-0000-000000000000" />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1 text-slate-700">Client Secret</label>
                <input type="password" value={azureSecret} onChange={e => setAzureSecret(e.target.value)} className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500" placeholder="••••••••" />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1 text-slate-700">Tenant ID</label>
                <input value={azureTenant} onChange={e => setAzureTenant(e.target.value)} className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500" placeholder="00000000-0000-0000-0000-000000000000" />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1 text-slate-700">Subscription ID</label>
                <input value={azureSub} onChange={e => setAzureSub(e.target.value)} className="w-full border border-slate-300 rounded px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500" placeholder="00000000-0000-0000-0000-000000000000" />
              </div>
            </>
          )}

          {provider === 'gcp' && (
            <div>
              <label className="block text-sm font-medium mb-1 text-slate-700">Service Account JSON</label>
              <textarea value={gcpJson} onChange={e => setGcpJson(e.target.value)} className="w-full border border-slate-300 rounded px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-blue-500" rows={5} placeholder='{ "type": "service_account", ... }' />
            </div>
          )}

          {error && <div className="p-3 bg-red-50 text-red-700 text-sm rounded border border-red-200">{error}</div>}
        </div>

        <div className="px-6 py-4 bg-slate-50 flex gap-3 justify-end border-t">
          <button onClick={onClose} disabled={loading} className="px-4 py-2 bg-white border border-slate-300 text-slate-700 rounded text-sm font-medium hover:bg-slate-50 transition-colors">
            Cancel
          </button>
          <button onClick={handleConnect} disabled={loading} className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors inline-flex items-center gap-2">
            {loading && (
              <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
              </svg>
            )}
            {loading ? 'Connecting...' : 'Connect & Scan'}
          </button>
        </div>
      </div>
    </div>
  );
}
