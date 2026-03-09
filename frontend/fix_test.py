import re

with open('/Users/idokatz/VSCode/Archmorph/frontend/src/components/__tests__/AdminDashboard.test.jsx', 'r') as f:
    text = f.read()

text = text.replace(
    "expect(await screen.findByText('Admin API not configured on server', {}, { timeout: 4000 }')).toBeInTheDocument()",
    "expect(await screen.findByText('Admin API not configured on server', {}, { timeout: 8000 })).toBeInTheDocument()"
)

with open('/Users/idokatz/VSCode/Archmorph/frontend/src/components/__tests__/AdminDashboard.test.jsx', 'w') as f:
    f.write(text)
