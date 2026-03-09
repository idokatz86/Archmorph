from main import app
for r in app.routes:
    if hasattr(r, "path"):
        print(r.path, r.methods)
