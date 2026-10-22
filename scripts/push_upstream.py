#!/usr/bin/env python3
"""Push the approved KB branch with the existing deployment credential."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

REPOSITORY = "github.com/harryzhang-carefold/kb-management.git"
BRANCH = "feat/pageindex"
REMOTE_CREDENTIAL = r'''
import configparser, json
from urllib.parse import unquote, urlsplit
config = configparser.ConfigParser(interpolation=None)
config.read('/opt/carefold-agent/.git/config')
url = urlsplit(config.get('remote "origin"', 'url', fallback=''))
if url.hostname != 'github.com' or not url.password:
    raise SystemExit('The deployment GitHub credential is unavailable')
print(json.dumps({'username': unquote(url.username or 'oauth2'), 'password': unquote(url.password)}))
'''


def main() -> int:
    repository = Path(__file__).resolve().parent.parent
    origin = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=repository, text=True).strip()
    url = urlsplit(origin)
    if url.scheme != "https" or f"{url.hostname}{url.path}" != REPOSITORY:
        raise RuntimeError("origin must be the approved kb-management HTTPS repository")
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=repository, text=True).strip()
    if branch != BRANCH:
        raise RuntimeError(f"Run this command from the approved {BRANCH} branch")
    host = os.environ.get("CAREFOLD_DEPLOY_HOST", "yk@35.209.183.7")
    identity = os.environ.get("CAREFOLD_DEPLOY_IDENTITY_FILE", str(Path.home() / ".ssh/id_ed25519"))
    result = subprocess.run([
        "ssh", "-i", identity, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        host, "sudo", "-n", "python3", "-",
    ], input=REMOTE_CREDENTIAL, text=True, capture_output=True, timeout=45)
    if result.returncode:
        raise RuntimeError("Cannot read the existing deployment credential; check SSH and non-interactive sudo access")
    credential = json.loads(result.stdout)
    with tempfile.TemporaryDirectory(prefix="carefold-kb-push-") as directory:
        askpass = Path(directory) / "askpass.sh"
        askpass.write_text('#!/bin/sh\ncase "$1" in\n*sername*) printf "%s\\n" "$CAREFOLD_KB_PUSH_USERNAME";;\n*assword*) printf "%s\\n" "$CAREFOLD_KB_PUSH_PASSWORD";;\nesac\n')
        askpass.chmod(0o700)
        environment = {**os.environ, "GIT_ASKPASS": str(askpass), "GIT_TERMINAL_PROMPT": "0",
                       "CAREFOLD_KB_PUSH_USERNAME": credential["username"], "CAREFOLD_KB_PUSH_PASSWORD": credential["password"]}
        return subprocess.run(["git", "-c", "credential.helper=", "push", "origin", f"HEAD:{BRANCH}"],
                              cwd=repository, env=environment).returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, subprocess.SubprocessError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
