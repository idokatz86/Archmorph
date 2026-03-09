import requests
import json
repo = "idokatz86/Archmorph"
url = f"https://api.github.com/repos/{repo}/issues?state=open&labels=enhancement"
res = requests.get(url)
print(res.status_code)
issues = res.json()
print([i["title"] for i in issues])
