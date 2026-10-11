import re
for fn in ["case_ac2_search_pageindex.sh", "case_ac3_chat_pageindex.sh",
           "case_ac4_regression.sh", "case_edge_no_pi_index.sh"]:
    raw = open(fn, "rb").read()
    crlf = raw.count(b"\r\n")
    cr = raw.count(b"\r")
    lines = raw.decode("utf-8").splitlines()
    # count quotes per line
    for i, ln in enumerate(lines, 1):
        dq = ln.count('"')
        sq = ln.count("'")
        if dq % 2 != 0 or sq % 2 != 0:
            print(f"{fn}:{i} ODD dquotes={dq} sq={sq} :: {ln!r}")
    print(f"{fn}: CRLF={crlf} CR={cr} lines={len(lines)}")
