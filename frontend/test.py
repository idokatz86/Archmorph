import re

with open('/Users/idokatz/VSCode/Archmorph/frontend/src/components/__tests__/AdminDashboard.test.jsx', 'r') as f:
    content = f.read()

print("Mocks found:")
for line in content.split('\n'):
    if 'mockResolvedValue' in line:
        print(line.strip())
