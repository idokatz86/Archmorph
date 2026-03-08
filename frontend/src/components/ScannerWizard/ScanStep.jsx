import React, { useEffect, useState } from 'react';

export default function ScanStep({ provider, onNext, onPrev }) {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    // Mock progress to fulfill #414
    const interval = setInterval(() => {
      setProgress(p => {
        if (p >= 100) {
          clearInterval(interval);
          return 100;
        }
        return p + 10;
      });
    }, 500);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="bg-slate-800 p-6 rounded-lg border border-slate-700">
      <h3 className="text-xl text-white mb-4">Step 2: Scanning {provider?.toUpperCase()}</h3>
      
      <div className="w-full bg-slate-700 h-4 rounded-full overflow-hidden mb-6">
        <div 
          className="bg-blue-500 h-full transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
      <p className="text-slate-300 mb-6">{progress}% complete...</p>

      <div className="flex gap-4">
        <button onClick={onPrev} className="px-6 py-2 bg-slate-700 text-white rounded-md">Cancel</button>
        <button 
          onClick={onNext} 
          disabled={progress < 100}
          className="px-6 py-2 bg-blue-600 disabled:opacity-50 text-white rounded-md"
        >
          Review Architecture
        </button>
      </div>
    </div>
  );
}
