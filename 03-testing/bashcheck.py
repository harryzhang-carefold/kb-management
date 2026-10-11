import subprocess, os
base = "/home/harry.zhang/kb-management/03-testing/curl"
for fn in ["case_ac2_search_pageindex.sh", "case_ac3_chat_pageindex.sh",
           "case_ac4_regression.sh", "case_edge_no_pi_index.sh"]:
    r = subprocess.run(["bash", "-n", os.path.join(base, fn)],
                       capture_output=True, text=True)
    print(f"{fn}: rc={r.returncode} {r.stderr.strip()[:120]}")
