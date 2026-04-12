// Re-export Prism with language components pre-loaded.
// prism-core sets the global *before* these side-effect imports execute.
import Prism from './prism-core';
import 'prismjs/components/prism-hcl';
import 'prismjs/components/prism-json';
import 'prismjs/components/prism-yaml';

export default Prism;
