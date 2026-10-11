import binascii
raw = open("/home/harry.zhang/kb-management/03-testing/curl/case_ac2_search_pageindex.sh", "rb").read()
lines = raw.split(b"\n")
print("num lines:", len(lines))
# Print the curl line as a clean hex string (no redaction ambiguity)
curl_line = [l for l in lines if l.startswith(b"curl")][0]
hexs = binascii.hexlify(curl_line).decode()
print("curl line hex len:", len(hexs)//2)
# Look for any 0x2a (asterisk = *) runs that shouldn't be there
import re
for m in re.finditer(rb"\*+", curl_line):
    print(f"ASTERISK RUN at byte {m.start()}-{m.end()}: {curl_line[max(0,m.start()-10):m.end()+10]!r}")
print("literal *** present:", b"***" in curl_line)
# Show first 80 bytes ascii
print("head ascii:", curl_line[:80].decode("utf-8", "replace"))
