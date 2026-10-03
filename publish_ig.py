"""Publish a Reel to Instagram through the Instagram Graph API with Facebook Login (resumable upload).

Env IG_TOKEN: a Facebook *Page* access token (starts with "EAA") for the Page linked to @streakchess,
with instagram_basic, instagram_content_publish, pages_show_list, pages_read_engagement
(+ instagram_manage_comments, instagram_manage_messages, pages_manage_metadata for the comment bot).
A Page token generated from a long-lived user token does not expire.
"""
import os, sys, time, requests

API = os.environ.get("IG_API_VERSION", "v23.0")
GRAPH = f"https://graph.facebook.com/{API}"
RUPLOAD = f"https://rupload.facebook.com/ig-api-upload/{API}"


def _check(r):
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code}: {r.text}")
    return r.json()


def whoami(token):
    """Returns {"user_id": <IG business account id>, "username": ..., "page_id": ...}."""
    me = _check(requests.get(f"{GRAPH}/me", params={
        "fields": "id,name,instagram_business_account{id,username}", "access_token": token}))
    ig = me.get("instagram_business_account")
    if not ig:  # a user token was given instead of a Page token: look through the user's Pages
        pages = _check(requests.get(f"{GRAPH}/me/accounts", params={
            "fields": "id,name,instagram_business_account{id,username}", "access_token": token}))["data"]
        page = next((p for p in pages if p.get("instagram_business_account")), None)
        if not page:
            raise RuntimeError("No Facebook Page with a linked Instagram account was found for this token")
        me, ig = page, page["instagram_business_account"]
    return {"user_id": ig["id"], "username": ig.get("username"), "page_id": me["id"]}


def ig_safe(video_path):
    """Re-encode to Instagram's recommended spec (H.264 High, 30 fps, <=8 Mbps, AAC 48 kHz stereo, faststart).
    Big high-bitrate files (grain + many details) are what makes Instagram's upload fail with ProcessingFailedError."""
    import subprocess
    out = video_path.replace(".mp4", "_ig.mp4")
    if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(video_path):
        return out
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video_path,
                    "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p", "-r", "30",
                    "-preset", "slow", "-crf", "21", "-maxrate", "8M", "-bufsize", "16M", "-g", "60",
                    "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                    "-movflags", "+faststart", out], check=True)
    print(f"IG-ready file: {os.path.getsize(out) / 1e6:.1f} MB (was {os.path.getsize(video_path) / 1e6:.1f} MB)", flush=True)
    return out


def _container_upload_wait(uid, token, video_path, fields, label, tries=3):
    """Create a resumable container, upload the bytes, wait until FINISHED. Retries with a fresh container."""
    data = open(video_path, "rb").read()
    last = None
    for attempt in range(tries):
        try:
            r = requests.post(f"{GRAPH}/{uid}/media", data={**fields, "upload_type": "resumable", "access_token": token})
            if r.status_code >= 400 and fields.get("location_id"):
                print(f"Location rejected ({r.text[:200]}); continuing without location", flush=True)
                fields = {k: v for k, v in fields.items() if k != "location_id"}
                r = requests.post(f"{GRAPH}/{uid}/media", data={**fields, "upload_type": "resumable", "access_token": token})
            cid = _check(r)["id"]
            _check(requests.post(f"{RUPLOAD}/{cid}", data=data, timeout=600, headers={
                "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(len(data))}))
            for _ in range(90):
                st = _check(requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code,status", "access_token": token}))
                code = st.get("status_code")
                print(f"{label} status:", code, flush=True)
                if code == "FINISHED":
                    return cid
                if code in ("ERROR", "EXPIRED"):
                    raise RuntimeError(f"{label} processing failed: {st}")
                time.sleep(10)
            raise RuntimeError(f"Timed out waiting for {label}")
        except Exception as e:
            last = e
            print(f"{label} attempt {attempt + 1}/{tries} failed: {str(e)[:300]}", flush=True)
            time.sleep(20 * (attempt + 1))
    raise last


def publish_reel(video_path, caption, token=None, location_id=None):
    token = token or os.environ["IG_TOKEN"]
    me = whoami(token)
    uid = me["user_id"]
    print(f"Publishing as @{me['username']}", flush=True)
    video_path = ig_safe(video_path)
    fields = {"media_type": "REELS", "caption": caption, "share_to_feed": "true"}
    if location_id:
        fields["location_id"] = str(location_id)
    cid = _container_upload_wait(uid, token, video_path, fields, "reel")
    p = _check(requests.post(f"{GRAPH}/{uid}/media_publish", data={"creation_id": cid, "access_token": token}))
    media = _check(requests.get(f"{GRAPH}/{p['id']}", params={"fields": "id,permalink", "access_token": token}))
    print("Published:", media.get("permalink"), flush=True)
    return media


def publish_story(video_path, token=None):
    """Share the same video as an Instagram Story (Stories expire after 24h; no caption/links via API)."""
    token = token or os.environ["IG_TOKEN"]
    uid = whoami(token)["user_id"]
    cid = _container_upload_wait(uid, token, ig_safe(video_path), {"media_type": "STORIES"}, "story")
    p = _check(requests.post(f"{GRAPH}/{uid}/media_publish", data={"creation_id": cid, "access_token": token}))
    print("Story published:", p.get("id"), flush=True)
    return p


def _upload_video_container(uid, token, video_path, fields):
    c = _check(requests.post(f"{GRAPH}/{uid}/media", data={**fields, "upload_type": "resumable", "access_token": token}))
    cid = c["id"]
    size = os.path.getsize(video_path)
    with open(video_path, "rb") as f:
        _check(requests.post(f"{RUPLOAD}/{cid}", data=f, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)}))
    return cid


def _wait(cid, token, label):
    for _ in range(90):
        code = _check(requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code", "access_token": token})).get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"{label} processing failed: {code}")
        time.sleep(10)
    raise RuntimeError(f"Timed out waiting for {label}")


def publish_carousel(video_paths, caption, token=None, location_id=None):
    """Carousel of short video slides (max 10), uploaded with resumable upload."""
    token = token or os.environ["IG_TOKEN"]
    uid = whoami(token)["user_id"]
    children = []
    for i, v in enumerate(video_paths[:10]):
        cid = _upload_video_container(uid, token, v, {"media_type": "VIDEO", "is_carousel_item": "true"})
        _wait(cid, token, f"slide {i}")
        print(f"slide {i} ready", flush=True)
        children.append(cid)
    data = {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption, "access_token": token}
    if location_id:
        data["location_id"] = str(location_id)
    r = requests.post(f"{GRAPH}/{uid}/media", data=data)
    if r.status_code >= 400 and location_id:
        print(f"Location {location_id} rejected ({r.text}); publishing without location", flush=True)
        data.pop("location_id"); r = requests.post(f"{GRAPH}/{uid}/media", data=data)
    cid = _check(r)["id"]
    _wait(cid, token, "carousel")
    p = _check(requests.post(f"{GRAPH}/{uid}/media_publish", data={"creation_id": cid, "access_token": token}))
    media = _check(requests.get(f"{GRAPH}/{p['id']}", params={"fields": "id,permalink", "access_token": token}))
    print("Carousel published:", media.get("permalink"), flush=True)
    return media


def check_token(token):
    """Prints who the token publishes as. Page tokens from a long-lived user token never expire."""
    me = whoami(token)
    print(f"Token OK: @{me['username']} (IG {me['user_id']}, Page {me['page_id']})")
    return token


if __name__ == "__main__":
    publish_reel(sys.argv[1], open(sys.argv[2]).read())
