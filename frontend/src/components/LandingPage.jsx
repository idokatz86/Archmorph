import React from 'react';
import {
  CloudCog, ArrowRight, Shield, Zap, Globe, Code, FileText,
  BarChart3, CheckCircle2, ChevronDown, ChevronUp, Users, Layers,
} from 'lucide-react';

const FEATURES = [
  {
    icon: CloudCog,
    title: 'AI-Powered Translation',
    desc: 'Upload AWS or GCP architecture diagrams and get instant Azure equivalents with AI-driven service mapping.',
  },
  {
    icon: Code,
    title: 'Infrastructure as Code',
    desc: 'Auto-generate production-ready Terraform and Bicep configurations for your translated architecture.',
  },
  {
    icon: FileText,
    title: 'High-Level Design Docs',
    desc: 'Generate comprehensive HLD documents with architecture decisions, security controls, and migration steps.',
  },
  {
    icon: BarChart3,
    title: 'Smart Analysis',
    desc: 'Get detailed service mappings with confidence scores, architecture patterns, and migration complexity assessment.',
  },
  {
    icon: Shield,
    title: 'Enterprise Security',
    desc: 'SOC 2 compliant infrastructure, GDPR ready, with audit logging and role-based access control.',
  },
  {
    icon: Globe,
    title: 'Multi-Cloud Support',
    desc: 'Translate from AWS, GCP, or multi-cloud architectures into optimized Azure deployments.',
  },
];

const HOW_IT_WORKS = [
  { step: '1', title: 'Upload', desc: 'Drop your existing cloud architecture diagram (PNG, JPG, or SVG)' },
  { step: '2', title: 'Analyze', desc: 'AI identifies services, dependencies, and architecture patterns' },
  { step: '3', title: 'Translate', desc: 'Get Azure service mappings with confidence scores and alternatives' },
  { step: '4', title: 'Export', desc: 'Download Terraform/Bicep code, HLD documents, and migration roadmaps' },
];

const FAQS = [
  {
    q: 'What cloud platforms do you support?',
    a: 'Archmorph currently translates architectures from AWS and Google Cloud Platform (GCP) to Microsoft Azure. We support 200+ services across all major cloud categories.',
  },
  {
    q: 'How accurate are the translations?',
    a: 'Our AI achieves 90%+ accuracy on standard service mappings. All outputs include confidence scores so you know which mappings need human review. Complex patterns may require architect validation.',
  },
  {
    q: 'Is my architecture data secure?',
    a: 'Yes. Diagrams are processed in-memory with a 2-hour TTL and automatically deleted. We use Azure OpenAI (EU region) for analysis — your data is never used for model training. We\'re GDPR compliant with SOC 2 Type II infrastructure.',
  },
  {
    q: 'What output formats are available?',
    a: 'You can export Infrastructure as Code (Terraform & Bicep), High-Level Design documents (Word, PDF, PPTX), and migration roadmaps.',
  },
  {
    q: 'Can I use the generated Terraform code in production?',
    a: 'The generated code follows Azure best practices and is production-ready for most scenarios. We recommend reviewing all generated configurations with your cloud team before deploying to production.',
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
            Translate Any Cloud Architecture{' '}
            <span className="text-cta">to Azure</span>
          </h1>
          <p className="text-lg text-text-secondary max-w-2xl mx-auto mb-8">
            Upload your AWS or GCP architecture diagrams and instantly get Azure equivalents
            with production-ready Terraform code, HLD documents, and migration roadmaps.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <button
              onClick={onGetStarted}
              className="flex items-center gap-2 px-6 py-3 bg-cta text-white rounded-xl font-medium hover:bg-cta/90 transition-colors text-sm"
              data-testid="hero-cta"
            >
              Start Translating — Free
              <ArrowRight className="w-4 h-4" />
            </button>

          </div>
          <div className="flex items-center justify-center gap-6 mt-8 text-xs text-text-muted">
            <span className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-cta" /> Free during beta</span>
            <span className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-cta" /> Unlimited analyses</span>
            <span className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-cta" /> GDPR compliant</span>
          </div>
        </div>
      </section>

      {/* Social proof */}
      <section className="py-8 border-y border-border/50">
        <div className="max-w-5xl mx-auto px-4">
          <div className="flex flex-wrap items-center justify-center gap-8 text-text-muted">
            <div className="flex items-center gap-2">
              <Users className="w-5 h-5" />
              <span className="text-sm font-medium">Trusted by cloud architects worldwide</span>
            </div>
            <div className="text-sm">200+ Azure services mapped</div>
            <div className="text-sm">Terraform & Bicep output</div>
            <div className="text-sm">EU data residency</div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="py-20" id="features">
        <div className="max-w-5xl mx-auto px-4">
          <div className="text-center mb-12">
            <h2 className="text-2xl sm:text-3xl font-bold text-text-primary mb-3">
              Everything you need for cloud migration
            </h2>
            <p className="text-text-muted max-w-lg mx-auto">
              From diagram analysis to production-ready infrastructure code, Archmorph handles the entire translation workflow.
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
            <p className="text-text-muted">Four simple steps to translate your cloud architecture</p>
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
            Ready to translate your architecture?
          </h2>
          <p className="text-text-muted mb-6">
            Join the beta — completely free while we shape the future of cloud migration.
          </p>
          <button
            onClick={onGetStarted}
            className="inline-flex items-center gap-2 px-6 py-3 bg-cta text-white rounded-xl font-medium hover:bg-cta/90 transition-colors text-sm"
            data-testid="bottom-cta"
          >
            Get Started Free
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </section>
    </div>
  );
}
