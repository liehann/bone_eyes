"""API keys: environment first, else the bone_eyes Infisical project.

Held in memory only. Needs `infisical login --domain https://infisical.app.phloots.com`
and the home LAN/VPN for the Infisical fallback.
"""
import json
import os
import ssl
import subprocess
import urllib.parse
import urllib.request

URL = "https://infisical.app.phloots.com"
PROJECT = "7e362222-14a2-44d0-b464-0fefbc624ff3"  # "bone_eyes"


def load(keys: list[str], env: str = "prod") -> dict[str, str]:
    found = {k: os.environ[k] for k in keys if os.environ.get(k)}
    missing = [k for k in keys if k not in found]
    if not missing:
        return found
    try:
        token = subprocess.run(["infisical", "user", "get", "token", "--plain"], check=True,
                               capture_output=True, text=True, timeout=15).stdout.strip()
        q = urllib.parse.urlencode({"workspaceId": PROJECT, "environment": env, "secretPath": "/"})
        req = urllib.request.Request(f"{URL}/api/v3/secrets/raw?{q}",
                                     headers={"Authorization": f"Bearer {token}"})
        # Self-signed cert on the instance for now (see the phloots-infisical skill).
        ctx = ssl._create_unverified_context()
        data = json.load(urllib.request.urlopen(req, context=ctx, timeout=15))
        for s in data["secrets"]:
            if s["secretKey"] in missing and s["secretValue"]:
                found[s["secretKey"]] = s["secretValue"]
    except Exception as e:  # offline, not logged in, ...
        print(f"secrets: Infisical unavailable ({type(e).__name__}); using environment only")
    return found
