import Prism from 'prismjs';

// PrismJS language component plugins reference a global `Prism` variable.
// When Rollup bundles them, the local binding gets renamed, so we must
// expose Prism on the global scope *before* any component is imported.
if (typeof window !== 'undefined') window.Prism = Prism;
if (typeof globalThis !== 'undefined') globalThis.Prism = Prism;

export default Prism;
