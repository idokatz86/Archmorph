import requests
resp = requests.post('http://127.0.0.1:8000/api/diagrams/sampleAwsIaaS123/export-package')
print("STATUS", resp.status_code)
print("BODY", resp.text)
