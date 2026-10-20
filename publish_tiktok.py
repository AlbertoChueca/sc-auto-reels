"""Send a reel to the TikTok inbox as a draft (official Content Posting API, 'upload' flow, free).
You then publish it from the TikTok app notification with one tap.

Env: TT_CLIENT_KEY, TT_CLIENT_SECRET, TT_REFRESH_TOKEN (scope video.upload).
TikTok may rotate the refresh token; if GH_TOKEN (a GitHub PAT) is set, the new one is saved
back into the TT_REFRESH_TOKEN secret automatically.
"""
import os, subprocess, requests

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


def _save_secret(name, value):
    if os.environ.get("GH_TOKEN") and os.environ.get("GITHUB_REPOSITORY"):
        subprocess.run(["gh", "secret", "set", name, "--repo", os.environ["GITHUB_REPOSITORY"]],
                       input=value.encode(), check=True)
        print(f"Saved new {name}", flush=True)
    else:
        print(f"::warning::TikTok returned a new refresh token but GH_PAT is not set; update {name} manually.")


def _access_token():
    r = requests.post(TOKEN_URL, headers={"Content-Type": "application/x-www-form-urlencoded"}, data={
        "client_key": os.environ["TT_CLIENT_KEY"], "client_secret": os.environ["TT_CLIENT_SECRET"],
        "grant_type": "refresh_token", "refresh_token": os.environ["TT_REFRESH_TOKEN"]}, timeout=60)
    j = r.json()
    if r.status_code >= 400 or "access_token" not in j:
        raise RuntimeError(f"TikTok token error {r.status_code}: {j}")
    if j.get("refresh_token") and j["refresh_token"] != os.environ["TT_REFRESH_TOKEN"]:
        print(f"::add-mask::{j['refresh_token']}")
        _save_secret("TT_REFRESH_TOKEN", j["refresh_token"])
    return j["access_token"]


def send_draft(video_path):
    token = _access_token()
    size = os.path.getsize(video_path)
    r = requests.post("https://open.tiktokapis.com/v2/post/publish/inbox/video/init/",
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
                      json={"source_info": {"source": "FILE_UPLOAD", "video_size": size,
                                            "chunk_size": size, "total_chunk_count": 1}}, timeout=60)
    j = r.json()
    if r.status_code >= 400 or j.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok init error {r.status_code}: {j}")
    with open(video_path, "rb") as f:
        up = requests.put(j["data"]["upload_url"], data=f, headers={
            "Content-Type": "video/mp4", "Content-Length": str(size),
            "Content-Range": f"bytes 0-{size - 1}/{size}"}, timeout=600)
    if up.status_code >= 400:
        raise RuntimeError(f"TikTok upload error {up.status_code}: {up.text}")
    print("TikTok: draft sent to inbox", j["data"].get("publish_id"), flush=True)
    return j["data"].get("publish_id")
