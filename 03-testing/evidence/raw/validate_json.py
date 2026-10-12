import json
for p in ["03-testing/evidence/PI-V2_result.json", "03-testing/evidence/PI-V2_state.json"]:
    d = json.load(open("/home/harry.zhang/kb-management/" + p, encoding="utf-8"))
    print("OK", p, "keys=", list(d.keys()))
