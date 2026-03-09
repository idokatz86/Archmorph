import re

with open('/Users/idokatz/VSCode/Archmorph/frontend/src/components/__tests__/AdminDashboard.test.jsx', 'r') as f:
    content = f.read()

# Fix the 503 error mock
content = content.replace(
    "fetch.mockResolvedValue({ ok: false, status: 503, json: () => Promise.resolve({}) })",
    "fetch.mockResolvedValue({ ok: false, status: 503, headers: new Headers({ 'content-type': 'application/json' }), json: () => Promise.resolve({ error: 'Admin API not configured on server' }) })"
)

with open('/Users/idokatz/VSCode/Archmorph/frontend/src/components/__tests__/AdminDashboard.test.jsx', 'w') as f:
    f.write(content)
