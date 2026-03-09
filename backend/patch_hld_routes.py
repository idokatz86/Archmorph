with open("routers/hld_routes.py", "r") as f:
    code = f.read()

code = code.replace("await asyncio.to_thread(\\n            diagrams_compat.generate_hld,", "await diagrams_compat.generate_hld(")

with open("routers/hld_routes.py", "w") as f:
    f.write(code)
print("hld routes patched")
