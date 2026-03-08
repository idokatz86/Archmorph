import React, { useState } from 'react';
import ConnectStep from './ConnectStep';
import ScanStep from './ScanStep';
import ReviewStep from './ReviewStep';
import { useWorkflow } from '../../hooks/useWorkflow';

export default function ScannerWizard() {
  const { currentStep, nextStep, prevStep } = useWorkflow();
  const [provider, setProvider] = useState(null);

  return (
    <div className="max-w-4xl mx-auto py-8">
      <div className="mb-8">
        <h2 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-emerald-400">
          Cloud Infrastructure Scanner
        </h2>
        <p className="text-slate-400">Connect to your environment and discover your architecture</p>
      </div>
      
      {currentStep === 1 && <ConnectStep provider={provider} setProvider={setProvider} onNext={nextStep} />}
      {currentStep === 2 && <ScanStep provider={provider} onNext={nextStep} onPrev={prevStep} />}
      {currentStep === 3 && <ReviewStep onNext={nextStep} onPrev={prevStep} />}
    </div>
  );
}
