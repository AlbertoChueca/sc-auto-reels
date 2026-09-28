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
    media = _check(requests.get(f"{GRAPH}/{p['id']}", params={"fields": "id,permalink", "access_token": token}))
    print("Published:", media.get("permalink"), flush=True)
    return media


def publish_story(video_path, token=None):
    """Share the same video as an Instagram Story (Stories expire after 24h; no caption/links via API)."""
    token = token or os.environ["IG_TOKEN"]
    uid = whoami(token)["user_id"]
    c = _check(requests.post(f"{GRAPH}/{uid}/media", data={
        "media_type": "STORIES", "upload_type": "resumable", "access_token": token}))
    cid = c["id"]
    size = os.path.getsize(video_path)
    with open(video_path, "rb") as f:
        _check(requests.post(f"{RUPLOAD}/{cid}", data=f, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)}))
    for _ in range(60):
        code = _check(requests.get(f"{GRAPH}/{cid}", params={"fields": "status_code", "access_token": token})).get("status_code")
        print("story status:", code, flush=True)
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Story processing failed: {code}")
        time.sleep(10)
    else:
        raise RuntimeError("Timed out waiting for story processing")
    p = _check(requests.post(f"{GRAPH}/{uid}/media_publish", data={"creation_id": cid, "access_token": token}))
    print("Story published:", p.get("id"), flush=True)
    return p


def check_token(token):
    """Prints who the token publishes as. Page tokens from a long-lived user token never expire."""
    me = whoami(token)
    print(f"Token OK: @{me['username']} (IG {me['user_id']}, Page {me['page_id']})")
    return token


if __name__ == "__main__":
    publish_reel(sys.argv[1], open(sys.argv[2]).read())
