import React, { useState, useRef } from 'react';
import api from '../../services/apiClient';

// Helper component for Code Block with Copy
function CodeBlock({ label, value }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="mt-2 mb-4 bg-slate-50 border border-slate-200 rounded p-2 flex justify-between items-center text-sm font-mono text-slate-800">
      <span className="truncate">{value}</span>
      <button 
        onClick={handleCopy}
        aria-label={`Copy ${label} to clipboard`}
        className="ml-2 text-slate-500 hover:text-slate-800 flex-shrink-0 focus:outline-none"
      >
        {copied ? (
          <span className="text-green-600 font-bold" aria-live="polite">✓ Copied!</span>
        ) : (
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path></svg>
        )}
      </button>
    </div>
  );
}

export function CloudCredentialsModal({ provider, onClose, onSuccess }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // AWS states
  const [awsRoleArn, setAwsRoleArn] = useState("");

  // Azure states
  const [azureClient, setAzureClient] = useState("");
  const [azureSecret, setAzureSecret] = useState("");
  const [azureTenant, setAzureTenant] = useState("");
  const [azureSub, setAzureSub] = useState("");
  const [showSecret, setShowSecret] = useState(false);

  // GCP states
  const [gcpJson, setGcpJson] = useState("");
  const [gcpFileName, setGcpFileName] = useState("");
  const fileInputRef = useRef(null);

  const isAwsComplete = awsRoleArn.trim() !== "";
  const isAzureComplete = azureClient.trim() && azureSecret.trim() && azureTenant.trim() && azureSub.trim();
  const isGcpComplete = gcpJson.trim() !== "";
  
  const isFormValid = 
    (provider === 'aws' && isAwsComplete) ||
    (provider === 'azure' && isAzureComplete) ||
    (provider === 'gcp' && isGcpComplete);

  const handleFileUpload = (e) => {
    let file;
    if (e.target.files && e.target.files.length > 0) {
      file = e.target.files[0];
    } else if (e.dataTransfer && e.dataTransfer.files.length > 0) {
      file = e.dataTransfer.files[0];
    }
    
    if (!file) return;
    if (file.type !== "application/json" && !file.name.endsWith(".json")) {
      setError("Please upload a valid .json file.");
      return;
    }
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const json = JSON.parse(event.target.result);
        setGcpJson(JSON.stringify(json, null, 2));
        setGcpFileName(file.name);
        setError(null);
      } catch (err) {
        setError("Invalid JSON file uploaded.");
      }
    };
    reader.readAsText(file);
  };

  const handleConnect = async () => {
    setLoading(true);
    setError(null);
    try {
      const authRes = await api.post('/auth/login', { provider: 'anonymous', token: 'none' });
      const sessionToken = authRes.session_token;

      let payload = {};
      let endpoint = `/credentials/${provider}`;
      
      if (provider === 'aws') {
        payload = { auth_method: 'assume_role', role_arn: awsRoleArn };
      } else if (provider === 'azure') {
        payload = { auth_method: 'service_principal', client_id: azureClient, client_secret: azureSecret, tenant_id: azureTenant, subscription_id: azureSub };
      } else if (provider === 'gcp') {
        payload = { auth_method: 'service_account_json', service_account_json: JSON.parse(gcpJson) };
      }

      await api.auth('POST', endpoint, { token: sessionToken, body: payload });
      onSuccess(sessionToken);

    } catch (err) {
      setError(err?.message || "Failed to validate credentials. Please check your inputs.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-sm p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-5xl overflow-hidden relative flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-6 py-5 border-b bg-slate-50 flex justify-between items-center">
          <div>
            <h3 className="text-xl font-semibold text-slate-800">
              Connect {provider.toUpperCase()} Environment
            </h3>
            <p className="text-sm text-slate-500 mt-1">
              To detect infrastructure drift, Archmorph requires Administrator access to grant read-only permissions.
            </p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600 transition-colors">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
          </button>
        </div>

        {/* Two-Column Body */}
        <div className="flex-1 overflow-auto flex flex-col md:flex-row">
          {/* Left Column: Instructions */}
          <div className="w-full md:w-1/2 p-6 border-r border-slate-100 overflow-y-auto bg-slate-50/50">
            <h4 className="font-semibold text-slate-800 mb-4 text-sm uppercase tracking-wider">Step-by-step Instructions</h4>
            
            {provider === 'aws' && (
              <div className="text-sm text-slate-600 space-y-4">
                <div>
                  <p className="font-medium text-slate-800 mb-1">Step 1: Create an IAM Role</p>
                  <ol className="list-decimal pl-5 space-y-1">
                    <li>Log into your AWS Console and navigate to <strong>IAM &gt; Roles</strong>.</li>
                    <li>Click <strong>Create role</strong> and select <strong>AWS account</strong>.</li>
                    <li>Select <strong>Another AWS account</strong> and enter Archmorph's Account ID:
                      <CodeBlock label="Archmorph Account ID" value="123456789012" />
                    </li>
                    <li>Check <strong>Require external ID</strong> and enter your unique ID:
                      <CodeBlock label="External ID" value="ext-xxxx-xxxx" />
                    </li>
                  </ol>
                </div>
                <div>
                  <p className="font-medium text-slate-800 mb-1">Step 2: Attach Policies</p>
                  <ol className="list-decimal pl-5 space-y-1">
                    <li>In the Add permissions screen, search for and select the <strong>ReadOnlyAccess</strong> managed policy.</li>
                    <li>Click Next, name your role (e.g., <code>Archmorph-Drift-Role</code>), and save.</li>
                  </ol>
                </div>
                <div>
                  <p className="font-medium text-slate-800 mb-1">Step 3: Copy Role ARN</p>
                  <p className="pl-5">Click into your newly created role and copy the <strong>Role ARN</strong> to paste it in the form.</p>
                </div>
              </div>
            )}

            {provider === 'azure' && (
              <div className="text-sm text-slate-600 space-y-4">
                <div>
                  <p className="font-medium text-slate-800 mb-1">Step 1: Register an Application</p>
                  <ol className="list-decimal pl-5 space-y-1">
                    <li>In the Azure Portal, go to <strong>Microsoft Entra ID &gt; App registrations</strong>.</li>
                    <li>Click <strong>New registration</strong>, name it <code>Archmorph Drift</code>, and click Register.</li>
                    <li>Copy the <strong>Tenant ID</strong> and <strong>Client ID</strong> to the form.</li>
                  </ol>
                </div>
                <div>
                  <p className="font-medium text-slate-800 mb-1">Step 2: Generate a Client Secret</p>
                  <ol className="list-decimal pl-5 space-y-1">
                    <li>Navigate to <strong>Certificates & secrets</strong> in the left menu.</li>
                    <li>Click <strong>New client secret</strong>, set an expiration, and add it.</li>
                    <li><strong>Important:</strong> Copy the generated <strong>Value</strong> immediately and paste it into the Client Secret field.</li>
                  </ol>
                </div>
                <div>
                  <p className="font-medium text-slate-800 mb-1">Step 3: Assign the Reader Role</p>
                  <ol className="list-decimal pl-5 space-y-1">
                    <li>Go to <strong>Subscriptions</strong>, select your target subscription, and click <strong>Access control (IAM)</strong>.</li>
                    <li>Click <strong>Add role assignment</strong>, select the <strong>Reader</strong> role.</li>
                    <li>Assign access to <strong>User, group, or service principal</strong>, select your <code>Archmorph Drift</code> app, and save.</li>
                  </ol>
                </div>
              </div>
            )}

            {provider === 'gcp' && (
              <div className="text-sm text-slate-600 space-y-4">
                <div>
                  <p className="font-medium text-slate-800 mb-1">Step 1: Create a Service Account</p>
                  <ol className="list-decimal pl-5 space-y-1">
                    <li>In the GCP Console, go to <strong>IAM & Admin &gt; Service Accounts</strong>.</li>
                    <li>Click <strong>Create Service Account</strong>, name it <code>archmorph-drift</code>, and click Create.</li>
                  </ol>
                </div>
                <div>
                  <p className="font-medium text-slate-800 mb-1">Step 2: Grant Viewer Access</p>
                  <ol className="list-decimal pl-5 space-y-1">
                    <li>In the "Grant this service account access" step, assign the <strong>Viewer</strong> role.</li>
                    <li>Click Done.</li>
                  </ol>
                </div>
                <div>
                  <p className="font-medium text-slate-800 mb-1">Step 3: Generate and Download JSON Key</p>
                  <ol className="list-decimal pl-5 space-y-1">
                    <li>Click on your newly created service account and go to the <strong>Keys</strong> tab.</li>
                    <li>Click <strong>Add Key &gt; Create new key</strong>.</li>
                    <li>Select <strong>JSON</strong> and click Create. The file will download automatically.</li>
                  </ol>
                </div>
              </div>
            )}
          </div>

          {/* Right Column: Form Action */}
          <div className="w-full md:w-1/2 p-6 flex flex-col justify-between">
            <div className="space-y-5">
              <h4 className="font-semibold text-slate-800 text-sm uppercase tracking-wider mb-2">Connection Details</h4>

              {error && (
                <div className="p-4 bg-red-50 text-red-700 text-sm rounded-lg border border-red-200 flex items-start" aria-live="assertive">
                  <svg className="w-5 h-5 mr-2 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                  <span>{error}</span>
                </div>
              )}

              {provider === 'aws' && (
                <div>
                  <label className="block text-sm font-medium mb-1 text-slate-700">IAM Role ARN</label>
                  <input 
                    value={awsRoleArn} 
                    onChange={e => setAwsRoleArn(e.target.value)} 
                    aria-invalid={error ? "true" : "false"}
                    className="w-full border border-slate-300 rounded-lg px-4 py-3 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all" 
                    placeholder="arn:aws:iam::123456789012:role/Archmorph-Drift-Role" 
                  />
                </div>
              )}

              {provider === 'azure' && (
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium mb-1 text-slate-700">Directory (Tenant) ID</label>
                    <input 
                      value={azureTenant} onChange={e => setAzureTenant(e.target.value)} 
                      className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all" 
                      placeholder="e.g., a1b2c3d4-..." 
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1 text-slate-700">Application (Client) ID</label>
                    <input 
                      value={azureClient} onChange={e => setAzureClient(e.target.value)} 
                      className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all" 
                      placeholder="e.g., f5g6h7i8-..." 
                    />
                  </div>
                  <div>
                     <label className="block text-sm font-medium mb-1 text-slate-700">Subscription ID</label>
                     <input 
                       value={azureSub} onChange={e => setAzureSub(e.target.value)} 
                       className="w-full border border-slate-300 rounded-lg px-4 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all" 
                       placeholder="e.g., 1234abcd-..." 
                     />
                  </div>
                  <div>
                    <label className="block text-sm font-medium mb-1 text-slate-700">Client Secret Value</label>
                    <div className="relative">
                      <input 
                        type={showSecret ? "text" : "password"} 
                        value={azureSecret} onChange={e => setAzureSecret(e.target.value)} 
                        className="w-full border border-slate-300 rounded-lg pl-4 pr-10 py-2.5 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all" 
                        placeholder="Enter your secret value" 
                      />
                      <button 
                        type="button"
                        onClick={() => setShowSecret(!showSecret)}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 focus:outline-none"
                      >
                        {showSecret ? (
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.29 3.29m0 0a10.05 10.05 0 015.188-1.583c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0l-3.29-3.29"></path></svg>
                        ) : (
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {provider === 'gcp' && (
                <div>
                  <label className="block text-sm font-medium mb-2 text-slate-700">Upload JSON Key</label>
                  <div 
                    className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${gcpFileName ? 'border-green-400 bg-green-50' : 'border-slate-300 hover:border-blue-400 hover:bg-slate-50'}`}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => {
                      e.preventDefault();
                      handleFileUpload(e);
                    }}
                  >
                    <input 
                      type="file" 
                      accept=".json,application/json" 
                      ref={fileInputRef}
                      onChange={handleFileUpload} 
                      className="hidden" 
                    />
                    
                    {gcpFileName ? (
                      <div className="flex flex-col items-center">
                        <div className="w-10 h-10 bg-green-100 rounded-full flex items-center justify-center mb-2">
                          <svg className="w-6 h-6 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M5 13l4 4L19 7"></path></svg>
                        </div>
                        <p className="text-sm font-medium text-slate-800">{gcpFileName}</p>
                        <button onClick={(e) => { e.stopPropagation(); setGcpFileName(""); setGcpJson(""); }} className="mt-2 text-xs text-red-500 hover:text-red-700">Remove and upload new</button>
                      </div>
                    ) : (
                      <div className="cursor-pointer" onClick={() => fileInputRef.current?.click()}>
                        <svg className="mx-auto h-12 w-12 text-slate-400 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path></svg>
                        <p className="text-sm text-slate-700">Drag and drop your .json key file here</p>
                        <p className="text-xs text-slate-500 mt-1">or click to browse from your computer</p>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            <div className="mt-8 pt-6 border-t border-slate-100">
              <div className="mb-4 flex items-start text-xs text-slate-600 bg-slate-50 p-3 rounded">
                <span className="mr-2 text-base leading-none">🔒</span>
                <p>
                  <strong>Read-only access.</strong> Archmorph only requires read access to scan infrastructure states. We never request write permissions. All credentials are encrypted at rest using AES-256 and never shared.
                </p>
              </div>
              <div className="flex gap-3 justify-end">
                <button 
                  onClick={onClose} 
                  disabled={loading} 
                  className="px-5 py-2.5 bg-white border border-slate-300 text-slate-700 rounded-lg text-sm font-medium hover:bg-slate-50 transition-colors"
                >
                  Cancel
                </button>
                <button 
                  onClick={handleConnect} 
                  disabled={loading || !isFormValid} 
                  className="px-5 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors inline-flex items-center gap-2"
                >
                  {loading && (
                    <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                  )}
                  {loading ? 'Connecting...' : 'Connect Environment'}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
