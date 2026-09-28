"""Publish a Reel to Instagram (Instagram API with Instagram Login, resumable upload).

Needs env var IG_TOKEN (long-lived token with instagram_business_content_publish).
"""
import os, sys, time, requests

API = os.environ.get("IG_API_VERSION", "v23.0")
GRAPH = f"https://graph.instagram.com/{API}"
RUPLOAD = f"https://rupload.facebook.com/ig-api-upload/{API}"


def _check(r):
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code}: {r.text}")
    return r.json()


def whoami(token):
    return _check(requests.get(f"{GRAPH}/me", params={"fields": "user_id,username", "access_token": token}))


def publish_reel(video_path, caption, token=None, location_id=None):
    token = token or os.environ["IG_TOKEN"]
    me = whoami(token)
    uid = me["user_id"]
    print(f"Publishing as @{me['username']}", flush=True)

    # 1) create a resumable Reels container
    data = {"media_type": "REELS", "upload_type": "resumable", "caption": caption,
            "share_to_feed": "true", "access_token": token}
    if location_id:
        data["location_id"] = str(location_id)
    r = requests.post(f"{GRAPH}/{uid}/media", data=data)
    if r.status_code >= 400 and location_id:
        print(f"Location {location_id} rejected ({r.text}); publishing without location", flush=True)
        data.pop("location_id"); r = requests.post(f"{GRAPH}/{uid}/media", data=data)
    c = _check(r)
    cid = c["id"]

    # 2) upload the local mp4 bytes
    size = os.path.getsize(video_path)
    with open(video_path, "rb") as f:
        _check(requests.post(f"{RUPLOAD}/{cid}", data=f, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)}))

    # 3) wait for Instagram to process the video
    for _ in range(60):
        st = _check(requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code,status", "access_token": token}))
        code = st.get("status_code")
        print("container status:", code, flush=True)
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Processing failed: {st}")
        time.sleep(10)
    else:
        raise RuntimeError("Timed out waiting for processing")

    # 4) publish
    p = _check(requests.post(f"{GRAPH}/{uid}/media_publish", data={"creation_id": cid, "access_token": token}))
    media = _check(requests.get(f"{GRAPH}/{p['id']}", params={"fields": "permalink", "access_token": token}))
    print("Published:", media.get("permalink"), flush=True)
    return media


def refresh_token(token):
    """Extends a long-lived token for another 60 days. Returns the (possibly new) token."""
    r = _check(requests.get("https://graph.instagram.com/refresh_access_token",
                            params={"grant_type": "ig_refresh_token", "access_token": token}))
    return r["access_token"]


if __name__ == "__main__":
    publish_reel(sys.argv[1], open(sys.argv[2]).read())
