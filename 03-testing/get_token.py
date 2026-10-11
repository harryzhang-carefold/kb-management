import httpx, json, uuid
c = httpx.Client(base_url="http://127.0.0.1:9012/api/v1", timeout=30)
r = c.post("/auth/login", json={"username": "testpi_8de322f7", "password": "Test123456!"})
b = r.json()
tok = (b.get("data") or {}).get("access_token")
if not tok:
    # fallback: register fresh
    u = f"replay_{uuid.uuid4().hex[:6]}"
    c.post("/auth/register", json={"username": u, "email": f"{u}@example.com", "password": "Test123456!", "display_name": "r"})
    b = c.post("/auth/login", json={"username": u, "password": "Test123456!"}).json()
    tok = b["data"]["access_token"]
print(tok)
with open("/tmp/kb_token.txt", "w") as f:
    f.write(tok)
