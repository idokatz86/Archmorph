from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
resp = client.post("/api/diagrams/sample-aws-eks-72ec79/export-package")
print("STATUS:", resp.status_code)
print("BODY:", resp.json())
