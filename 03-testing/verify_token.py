import httpx, uuid
c = httpx.Client(base_url="http://127.0.0.1:9012/api/v1", timeout=30)
u = "replay2_" + uuid.uuid4().hex[:6]
r = c.post("/auth/register", json={"username": u, "email": u + "@example.com", "password": "Test123456!", "display_name": "r"})
print("register", r.status_code, r.text[:200])
r = c.post("/auth/login", json={"username": u, "password": "Test123456!"})
b = r.json()
tok = (b.get("data") or {}).get("access_token")
print("login", r.status_code, "tok_len=", len(tok) if tok else None)
open("/tmp/kb_token2.txt", "w").write(tok or "")
r2 = c.post("/auth/login", json={"username": "testpi_8de322f7", "password": "Test123456!"})
print("old_user_login", r2.status_code, r2.text[:150])
