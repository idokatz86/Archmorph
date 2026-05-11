import { Rocket } from 'lucide-react';

const DeployPanel = () => {
  return (
    <section
      role="status"
      aria-live="polite"
      aria-label="Coming soon - One-click deployment is under active development."
      className="w-full max-w-3xl mx-auto rounded-lg border border-border bg-surface p-8 text-center shadow-sm"
    >
      <div className="w-12 h-12 mx-auto mb-4 rounded-full bg-cta/10 flex items-center justify-center">
        <Rocket className="w-6 h-6 text-cta" aria-hidden="true" />
      </div>
      <h2 className="text-lg font-bold text-text-primary">Coming Soon</h2>
      <p className="text-sm text-text-muted mt-2 max-w-md mx-auto">
        One-click deployment is under active development. Deploy your generated IaC directly to Azure with built-in security checks and rollback.
      </p>
    </section>
  );
};

export default DeployPanel;
