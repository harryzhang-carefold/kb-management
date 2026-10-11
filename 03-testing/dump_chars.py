raw = open("/home/harry.zhang/kb-management/03-testing/curl/case_ac2_search_pageindex.sh", "rb").read()
lines = raw.decode("utf-8").splitlines()
curl_line = [l for l in lines if l.strip().startswith("curl")][0]
# Print index + char for every quote and its neighbors, and any non-ascii
out = []
for i, ch in enumerate(curl_line):
    if ch in "\"'" or ord(ch) > 127 or ch == "\\":
        ctx = curl_line[max(0,i-6):i+7]
        out.append(f"  i={i:3d} {ch!r:6} (ord {ord(ch):4d}) ctx={ctx!r}")
print("\n".join(out))
print("TOTAL len:", len(curl_line))
