"""Replay the curl/*.sh scripts with a real token (passed via env, not argv).
This exercises the actual archived curl commands for re-test evidence."""
import os
import subprocess

tok = open("/tmp/kb_token.txt").read().strip()
env = dict(os.environ)
env["TOKEN"] = tok
base = "/home/harry.zhang/kb-management/03-testing/curl"
cases = [
    ("AC2 pageindex search", "case_ac2_search_pageindex.sh"),
    ("AC4 regression hybrid/vector/keyword", "case_ac4_regression.sh"),
    ("EDGE no-pi-index search+chat", "case_edge_no_pi_index.sh"),
]
for label, fn in cases:
    print(f"\n===== {label} ({fn}) =====")
    try:
        out = subprocess.run(["bash", os.path.join(base, fn)],
                             env=env, capture_output=True, text=True, timeout=120)
        # show http_code lines + first item lines
        for line in out.stdout.splitlines():
            if "HTTP_CODE" in line or "match_type" in line or "items" in line.lower() \
               or "event:" in line or "message" in line:
                print("  " + line[:180])
        if out.returncode != 0:
            print("  [rc=%d stderr=%s]" % (out.returncode, out.stderr[:200]))
    except subprocess.TimeoutExpired:
        print("  [TIMEOUT >120s]")
