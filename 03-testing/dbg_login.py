import httpx, uuid
c = httpx.Client(base_url="http://127.0.0.1:9012/api/v1", timeout=30)
u = f"edge_py_{uuid.uuid4().hex[:6]}"
r = c.post("/auth/register", json={"username": u, "email": f"{u}@example.com", "password": "Test123456!", "display_name": "x"})
print("register:", r.status_code, r.json().get("code"))
r = c.post("/auth/login", json={"username": u, "password": "Test123456!"})
b = r.json()
print("login:", r.status_code, b.get("code"), "has_token=" + str("access_token" in (b.get("data") or {})))
print("data keys:", list((b.get("data") or {}).keys()))
