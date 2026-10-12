import json
p = "/home/harry.zhang/kb-management/03-testing/evidence/raw/openapi_pi_v2.json"
d = json.load(open(p))
op = d["paths"]["/api/v1/knowledge-bases/{kb_id}/documents"]["post"]
media = op["requestBody"]["content"]["multipart/form-data"]
print("SCHEMA:", json.dumps(media["schema"], ensure_ascii=False))
# resolve refs
schemas = d.get("components", {}).get("schemas", {})
def resolve(s):
    if "$ref" in s:
        name = s["$ref"].split("/")[-1]
        return name, schemas.get(name, {})
    return None, s
name, sch = resolve(media["schema"])
print("RESOLVED NAME:", name)
print(json.dumps(sch, ensure_ascii=False, indent=1)[:2000])
# raw fragment for evidence
frag = {"path": "/api/v1/knowledge-bases/{kb_id}/documents", "method": "post",
        "requestBody": media}
open("/home/harry.zhang/kb-management/03-testing/evidence/raw/openapi_upload_fragment.json","w").write(
    json.dumps(frag, ensure_ascii=False, indent=1))
