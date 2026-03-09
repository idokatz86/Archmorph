import re

with open('/Users/idokatz/VSCode/Archmorph/frontend/src/components/__tests__/AdminDashboard.test.jsx', 'r') as f:
    content = f.read()

content = content.replace(
    "fetch.mockResolvedValue({ ok: false, status: 401, headers: new Headers({ 'content-type': 'application/json' }), json: () => Promise.resolve({ error: 'Your session has expired. Please sign in again.' }) })",
    "fetch.mockResolvedValue({ ok: false, status: 401, headers: new Headers({ 'content-type': 'application/json' }), json: () => Promise.resolve({ error: { message: 'Invalid admin key' } }) })"
)

content = content.replace(
    "expect(await screen.findByText('Your session has expired. Please sign in again.')).toBeInTheDocument()",
    "expect(await screen.findByText('Invalid admin key')).toBeInTheDocument()"
)

with open('/Users/idokatz/VSCode/Archmorph/frontend/src/components/__tests__/AdminDashboard.test.jsx', 'w') as f:
    f.write(content)

