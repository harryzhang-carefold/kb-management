raw = open("/home/harry.zhang/kb-management/03-testing/replay_curl.sh").read()
for i, ln in enumerate(raw.splitlines(), 1):
    print(f"{i}: {ln!r}")
