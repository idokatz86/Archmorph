import requests
resp = requests.post('http://127.0.0.1:8000/api/diagrams/sample-aws-eks-72ec79/export-package')
print("STATUS", resp.status_code)
print("BODY", resp.text)
