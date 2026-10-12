import json, sys
p = "/home/harry.zhang/kb-management/03-testing/evidence/raw/openapi_pi_v2.json"
d = json.load(open(p))
paths = d.get("paths", {})
print("=== PATHS ===")
for k in sorted(paths):
    print(k, sorted(paths[k].keys()))
# upload endpoint
for k in sorted(paths):
    if "documents" in k:
        for m, op in paths[k].items():
            print("---", m.upper(), k, op.get("summary"))
# find multipart upload request body
for k, v in paths.items():
    for m, op in v.items():
        rb = op.get("requestBody")
        if not rb:
            continue
        for ct, media in rb.get("content", {}).items():
            if "multipart/form-data" in ct:
                print("MULTIPART:", m.upper(), k, ct)
                props = media.get("schema", {}).get("properties", {})
                for pn, pv in props.items():
                    print("   field:", pn, "default=", pv.get("default"), "type=", pv.get("type"), "schema=", json.dumps(pv, ensure_ascii=False)[:200])
