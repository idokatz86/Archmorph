import React from 'react';

export default function ReviewStep({ onNext, onPrev }) {
  return (
    <div className="bg-slate-800 p-6 rounded-lg border border-slate-700">
      <h3 className="text-xl text-white mb-4">Step 3: Discovered Architecture</h3>
      
      <div className="bg-slate-900 border border-slate-700 p-4 rounded mb-6 text-slate-300">
        <p>📊 3 VPCs Discovered</p>
        <p>💻 12 EC2 Instances</p>
        <p>🗄️ 4 RDS Databases</p>
      </div>

      <div className="flex gap-4">
        <button onClick={onPrev} className="px-6 py-2 bg-slate-700 text-white rounded-md">Back</button>
        <button className="px-6 py-2 bg-emerald-600 text-white rounded-md">
          Proceed to Migration
        </button>
      </div>
    </div>
  );
}
