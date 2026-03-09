import uvicorn
import main
import threading
import time
import requests

def run():
    uvicorn.run(main.app, host="127.0.0.1", port=8011, log_level="error")

t = threading.Thread(target=run, daemon=True)
t.start()
time.sleep(4)
print("Sending request...")
try:
    resp = requests.post("http://127.0.0.1:8011/api/diagrams/sample/export-package")
    print("STATUS:", resp.status_code)
    print("BODY:", resp.text)
except Exception as e:
    print("ERROR:", e)
