import React from 'react';
import {
  CloudCog, ArrowRight, Shield, Zap, Globe, Code, FileText,
  BarChart3, CheckCircle2, ChevronDown, ChevronUp, Layers,
  GitBranch, MessageSquare, FileCode2, Activity,
} from 'lucide-react';

const FEATURES = [
  {
    icon: CloudCog,
    title: 'AI-Powered Translation',
    desc: 'GPT-4o vision analyzes your diagrams — PNG, SVG, Draw.io, or Visio — and maps 405+ cloud services across AWS, Azure, and GCP with confidence scores.',
  },
  {
    icon: Code,
    title: 'Terraform, Bicep & CloudFormation',
    desc: 'Generate production-ready IaC in all three formats with secure credential handling, Key Vault integration, and an interactive chat assistant to refine your code.',
  },
  {
    icon: FileText,
    title: 'HLD Documents & Runbooks',
    desc: 'Export 13-section High-Level Design docs (Word, PDF, PPTX) and step-by-step migration runbooks with rollback procedures.',
  },
  {
    icon: GitBranch,
    title: 'Architecture Versioning',
    desc: 'Track every change with version history, side-by-side diffs, and one-click restore. Terraform plan previews before you deploy.',
  },
  {
    icon: BarChart3,
    title: 'Cost Estimates & Optimization',
    desc: 'Region-aware pricing from the Azure Retail Prices API with SKU strategy multipliers. Get per-service cost breakdowns and optimization tips.',
  },
  {
    icon: Activity,
    title: 'Living Architecture',
    desc: 'Monitor deployed architectures with health scoring across 5 dimensions, drift detection, and cost anomaly alerts.',
  },
  {
    icon: Shield,
    title: 'Enterprise Security',
    desc: 'Zero Trust WAF, SAST scanning, secret detection, audit logging with risk levels, and GDPR-compliant EU data residency.',
  },
  {
    icon: MessageSquare,
    title: 'AI Assistant & Community',
    desc: 'Ask questions, report bugs, or request features through the GPT-4o chatbot. Community migration intelligence improves confidence scores over time.',
  },
  {
    icon: Globe,
    title: 'Multi-Cloud, Any Direction',
    desc: 'Translate between AWS, GCP, and Azure in any direction. 120+ cross-cloud mappings with fuzzy matching and synonym resolution.',
  },
];

const HOW_IT_WORKS = [
  { step: '1', title: 'Upload', desc: 'Drop any cloud diagram — PNG, SVG, Draw.io, Visio (.vsdx), or use a sample template' },
  { step: '2', title: 'Analyze', desc: 'GPT-4o identifies services, connections, and data flows with multi-pass analysis for complex diagrams' },
  { step: '3', title: 'Refine', desc: 'Answer guided migration questions, add services via natural language, and tune IaC with the chat assistant' },
  { step: '4', title: 'Export', desc: 'Download Terraform/Bicep/CloudFormation code, HLD documents, cost estimates, and migration runbooks' },
];

const STATS = [
  { value: '405+', label: 'Cloud services cataloged' },
  { value: '120+', label: 'Cross-cloud mappings' },
  { value: '3', label: 'IaC formats supported' },
  { value: '100%', label: 'Free — no limits' },
];

const FAQS = [
  {
    q: 'What cloud platforms do you support?',
    a: 'Archmorph translates between AWS, Google Cloud Platform (GCP), and Microsoft Azure in any direction. We catalog 405+ services — 145 AWS, 168 Azure, and 143 GCP — with 120+ cross-cloud mappings that improve automatically via community migration intelligence.',
  },
  {
    q: 'How accurate are the translations?',
    a: 'GPT-4o vision combined with our mapping engine achieves 90%+ accuracy on standard services. Confidence scores blend catalog mappings (70%), AI detection confidence (30%), and community success rates so you know exactly which mappings need human review.',
  },
  {
    q: 'Is my architecture data secure?',
    a: 'Yes. Diagrams are processed in-memory with a 2-hour TTL and automatically deleted. We use Azure OpenAI (EU region) — your data is never used for model training. Infrastructure includes Zero Trust WAF, SAST scanning, secret detection, and audit logging. GDPR compliant.',
  },
  {
    q: 'What output formats are available?',
    a: 'Infrastructure as Code in Terraform, Bicep, and CloudFormation. High-Level Design documents as Word, PDF, or PPTX. Architecture diagrams as Excalidraw, Draw.io, or Visio. Migration runbooks with task tracking and rollback procedures.',
  },
  {
    q: 'Can I use the generated code in production?',
    a: 'Yes. Generated IaC follows cloud best practices with secure credential handling (Key Vault / Secrets Manager), validated syntax, and security scanning. Use the built-in Terraform plan preview to review resources before deploying.',
  },
  {
    q: 'Is Archmorph really free?',
    a: 'Yes — 100% free with no usage limits. Unlimited analyses, IaC generation, HLD exports, and all features. No credit card required, no trial period, no hidden fees.',
  },
];

function FAQItem({ q, a }) {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="border border-border/50 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-4 text-left hover:bg-secondary/30 transition-colors"
      >
        <span className="text-sm font-medium text-text-primary pr-4">{q}</span>
        {open ? (
          <ChevronUp className="w-4 h-4 text-text-muted shrink-0" />
        ) : (
          <ChevronDown className="w-4 h-4 text-text-muted shrink-0" />
        )}
      </button>
      {open && (
        <div className="px-4 pb-4">
          <p className="text-sm text-text-secondary leading-relaxed">{a}</p>
        </div>
      )}
    </div>
  );
}

export default function LandingPage({ onGetStarted }) {
  return (
    <div className="min-h-screen" data-testid="landing-page">
      {/* Hero */}
      <section className="relative overflow-hidden py-20 sm:py-28">
        <div className="absolute inset-0 bg-gradient-to-br from-cta/5 via-transparent to-amber-500/5" />
        <div className="relative max-w-4xl mx-auto px-4 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cta/10 text-cta text-xs font-medium mb-6">
            <Zap className="w-3 h-3" />
            AI-Powered Cloud Migration
          </div>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold text-text-primary leading-tight mb-6">
            Modernize Any Cloud{' '}
            <span className="text-cta">to Azure</span>
          </h1>
          <p className="text-lg text-text-secondary max-w-2xl mx-auto mb-8">
            Upload AWS or GCP architecture diagrams and get instant Azure equivalents
            with Terraform, Bicep, or CloudFormation code, HLD documents, cost estimates,
            and step-by-step migration runbooks — all powered by GPT-4o.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <button
              onClick={onGetStarted}
              className="flex items-center gap-2 px-8 py-3.5 bg-cta text-white rounded-xl font-semibold hover:bg-cta/90 transition-colors text-sm shadow-lg shadow-cta/20"
              data-testid="hero-cta"
            >
              Start Translating — It's Free
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-6 mt-8 text-xs text-text-muted">
            <span className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-cta" /> 100% free forever</span>
            <span className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-cta" /> No account required</span>
            <span className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-cta" /> GDPR compliant</span>
          </div>
        </div>
      </section>

      {/* Stats bar */}
      <section className="py-8 border-y border-border/50">
        <div className="max-w-5xl mx-auto px-4">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 text-center">
            {STATS.map((s, i) => (
              <div key={i}>
                <div className="text-2xl font-bold text-cta">{s.value}</div>
                <div className="text-xs text-text-muted mt-1">{s.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="py-20" id="features">
        <div className="max-w-6xl mx-auto px-4">
          <div className="text-center mb-12">
            <h2 className="text-2xl sm:text-3xl font-bold text-text-primary mb-3">
              End-to-end cloud migration platform
            </h2>
            <p className="text-text-muted max-w-lg mx-auto">
              From diagram analysis to production-ready infrastructure — everything you need to translate, plan, and execute cloud migrations.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {FEATURES.map((f, i) => {
              const Icon = f.icon;
              return (
                <div
                  key={i}
                  className="p-6 rounded-2xl border border-border/50 bg-secondary/10 hover:border-cta/20 hover:bg-secondary/20 transition-all group"
                >
                  <div className="w-10 h-10 rounded-xl bg-cta/10 flex items-center justify-center mb-4 group-hover:bg-cta/20 transition-colors">
                    <Icon className="w-5 h-5 text-cta" />
                  </div>
                  <h3 className="text-sm font-semibold text-text-primary mb-2">{f.title}</h3>
                  <p className="text-sm text-text-muted leading-relaxed">{f.desc}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="py-20 bg-secondary/20" id="how-it-works">
        <div className="max-w-4xl mx-auto px-4">
          <div className="text-center mb-12">
            <h2 className="text-2xl sm:text-3xl font-bold text-text-primary mb-3">
              How it works
            </h2>
            <p className="text-text-muted">Four steps from diagram to production-ready infrastructure</p>
          </div>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-6">
            {HOW_IT_WORKS.map((item, i) => (
              <div key={i} className="text-center">
                <div className="w-12 h-12 rounded-2xl bg-cta/10 flex items-center justify-center mx-auto mb-4">
                  <span className="text-lg font-bold text-cta">{item.step}</span>
                </div>
                <h3 className="text-sm font-semibold text-text-primary mb-1">{item.title}</h3>
                <p className="text-xs text-text-muted">{item.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="py-20" id="faq">
        <div className="max-w-3xl mx-auto px-4">
          <div className="text-center mb-10">
            <h2 className="text-2xl sm:text-3xl font-bold text-text-primary mb-3">
              Frequently asked questions
            </h2>
          </div>
          <div className="space-y-3">
            {FAQS.map((faq, i) => (
              <FAQItem key={i} q={faq.q} a={faq.a} />
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-20 bg-gradient-to-br from-cta/5 via-transparent to-amber-500/5">
        <div className="max-w-3xl mx-auto px-4 text-center">
          <Layers className="w-10 h-10 text-cta mx-auto mb-4" />
          <h2 className="text-2xl sm:text-3xl font-bold text-text-primary mb-4">
            Ready to modernize your architecture?
          </h2>
          <p className="text-text-muted mb-6">
            100% free — no account, no limits, no credit card. Start translating your cloud architecture now.
          </p>
          <button
            onClick={onGetStarted}
            className="inline-flex items-center gap-2 px-8 py-3.5 bg-cta text-white rounded-xl font-semibold hover:bg-cta/90 transition-colors text-sm shadow-lg shadow-cta/20"
            data-testid="bottom-cta"
          >
            Get Started — It's Free
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </section>
    </div>
  );
}
