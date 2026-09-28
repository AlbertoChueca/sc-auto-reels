"""One-time: exchange the TikTok authorization code for a refresh token and store it as a secret.
Run from Actions -> 'TikTok connect' with the ?code=... value from the redirect URL.
"""
import os, sys, urllib.parse, requests
from publish_tiktok import TOKEN_URL, _save_secret

code = urllib.parse.unquote(sys.argv[1].strip())
r = requests.post(TOKEN_URL, headers={"Content-Type": "application/x-www-form-urlencoded"}, data={
    "client_key": os.environ["TT_CLIENT_KEY"], "client_secret": os.environ["TT_CLIENT_SECRET"],
    "code": code, "grant_type": "authorization_code", "redirect_uri": os.environ["TT_REDIRECT_URI"]}, timeout=60)
j = r.json()
if "refresh_token" not in j:
    raise SystemExit(f"TikTok error: {j}")
print(f"::add-mask::{j['refresh_token']}")
print("Scopes granted:", j.get("scope"))
_save_secret("TT_REFRESH_TOKEN", j["refresh_token"])
