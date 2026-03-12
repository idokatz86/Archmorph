const fs = require('fs');
const path = 'src/components/DiagramTranslator/__tests__/index.test.jsx';
let content = fs.readFileSync(path, 'utf8');

content = content.replace(/screen\.getByText\(/g, 'await screen.findByText(');

fs.writeFileSync(path, content);
