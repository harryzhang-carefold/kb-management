for fn in ["case_ac2_search_pageindex.sh", "case_ac4_regression.sh"]:
    print(f"\n=== {fn} ===")
    lines = open(f"/home/harry.zhang/kb-management/03-testing/curl/{fn}").read().splitlines()
    for i, ln in enumerate(lines, 1):
        ends_bs = ln.endswith("\\")
        # show lines that SHOULD end with backslash (multi-line curl) but don't
        has_curl_or_w = ("curl" in ln) or ln.strip().startswith(("-H", "-d", "-w"))
        flag = "  <== NO TRAILING \\" if (has_curl_or_w and not ends_bs and "curl -sS" in ln) else ""
        if i >= 10:
            print(f"{i}: ends_bs={ends_bs} :: {ln!r}{flag}")
