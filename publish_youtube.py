"""Upload a reel to YouTube Shorts with the official YouTube Data API (free).

Env: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (OAuth, scope youtube.upload).
Note: until the Google Cloud project passes YouTube's API audit, uploads are forced to private.
"""
import json, os, requests


def _access_token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"}, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"YouTube token error {r.status_code}: {r.text}")
    return r.json()["access_token"]


def upload_short(video_path, hook, caption):
    token = _access_token()
    title = f"{hook.title()} ♟️ Chess Puzzle #shorts"[:100]
    desc = caption.replace("link in bio", "play free at https://streakchess.com")[:4900]
    meta = {"snippet": {"title": title, "description": desc, "categoryId": "27",
                        "tags": ["chess", "chess puzzle", "chess tactics", "streakchess", "shorts"]},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}
    size = os.path.getsize(video_path)
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
        data=json.dumps(meta), timeout=60)
    if init.status_code >= 400:
        raise RuntimeError(f"YouTube init error {init.status_code}: {init.text}")
    with open(video_path, "rb") as f:
        up = requests.put(init.headers["Location"], data=f,
                          headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4"}, timeout=600)
    if up.status_code >= 400:
        raise RuntimeError(f"YouTube upload error {up.status_code}: {up.text}")
    v = up.json()
    print(f"YouTube: https://youtube.com/shorts/{v['id']} ({v.get('status', {}).get('privacyStatus')})", flush=True)
    return v["id"]
