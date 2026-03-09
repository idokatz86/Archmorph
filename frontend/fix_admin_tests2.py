import re

with open('/Users/idokatz/VSCode/Archmorph/frontend/src/components/__tests__/AdminDashboard.test.jsx', 'r') as f:
    content = f.read()

# Fix the 401 error mock
content = content.replace(
    "fetch.mockResolvedValue({ ok: false, status: 401, json: () => Promise.resolve({}) })",
    "fetch.mockResolvedValue({ ok: false, status: 401, headers: new Headers({ 'content-type': 'application/json' }), json: () => Promise.resolve({ error: 'Your session has expired. Please sign in again.' }) })"
)

with open('/Users/idokatz/VSCode/Archmorph/frontend/src/components/__tests__/AdminDashboard.test.jsx', 'w') as f:
    f.write(content)
