import re

with open('/Users/idokatz/VSCode/Archmorph/frontend/src/components/__tests__/AdminDashboard.test.jsx', 'r') as f:
    text = f.read()

# Replace all fetch.mockResolvedValue stuff with api.post/get mocks
# Actually it's easier to just mock sleep in AdminDashboard.test.jsx:
