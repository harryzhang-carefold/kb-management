import re
# Read the single-line ac2 script as raw bytes, show the curl line
raw = open("/home/harry.zhang/kb-management/03-testing/curl/case_ac2_search_pageindex.sh", "rb").read()
lines = raw.decode("utf-8").splitlines()
curl_line = [l for l in lines if l.strip().startswith("curl")][0]
print("curl line bytes:", len(curl_line))
print("has *** :", "***" in curl_line)
print("dquote parity:", curl_line.count('"') % 2 == 0, "count=", curl_line.count('"'))
print("squote parity:", curl_line.count("'") % 2 == 0, "count=", curl_line.count("'"))
print("repr:", repr(curl_line[:120]))
print("...tail:", repr(curl_line[-80:]))
