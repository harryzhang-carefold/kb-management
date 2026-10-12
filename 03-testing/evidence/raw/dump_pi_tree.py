import json
p = "/home/harry.zhang/kb-management/03-testing/evidence/raw/PI-01_doc_final.json"
d = json.load(open(p))
doc = d["data"]["document"]
meta = doc["meta"]
tree = meta.get("pageindex_tree", {})
print("doc.status =", doc["status"], "chunk_count =", doc["chunk_count"])
print("meta keys =", sorted(meta.keys()))
print("index_type =", meta.get("index_type"), "pageindex_status =", meta.get("pageindex_status"))
print("tree keys =", sorted(tree.keys()))
print("tree.status =", tree.get("status"), "model =", tree.get("model"),
      "node_count =", tree.get("node_count"), "build_ms =", tree.get("build_ms"),
      "full_text_chars =", tree.get("full_text_chars"))
print("--- tree.root 全文 ---")
print(json.dumps(tree.get("root"), ensure_ascii=False, indent=1))
print("--- 夹具 markdown 标题（H1/H2/H3）---")
for line in open("/home/harry.zhang/kb-management/03-testing/fixtures_pi/pi_default_doc.md", encoding="utf-8"):
    if line.startswith("#"):
        print(repr(line.rstrip()))
