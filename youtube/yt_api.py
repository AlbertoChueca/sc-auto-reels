"""YouTube Data API v3 + YouTube Analytics API v2 (plain HTTP, no extra libraries).

Credentials (GitHub secrets): YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN (get it once with yt_auth.py).
Scopes: youtube.upload, youtube (thumbnails / title updates), yt-analytics.readonly.
"""
import json, os, time
import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3"
ANALYTICS = "https://youtubeanalytics.googleapis.com/v2/reports"
_TOK = {}


def token():
    if _TOK.get("exp", 0) > time.time() + 60:
        return _TOK["t"]
    r = requests.post(TOKEN_URL, data={"client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
                                       "refresh_token": os.environ["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"YouTube login failed ({r.status_code}): {r.text[:300]}. If it says invalid_grant, the refresh "
                           f"token expired: set the OAuth app to 'In production' and run yt_auth.py again.")
    j = r.json(); _TOK.update(t=j["access_token"], exp=time.time() + j.get("expires_in", 3600))
    return _TOK["t"]


def _h(extra=None):
    h = {"Authorization": f"Bearer {token()}"}
    h.update(extra or {})
    return h


def _check(r, what):
    if r.status_code >= 400:
        raise RuntimeError(f"YouTube {what} failed {r.status_code}: {r.text[:500]}")
    return r.json() if r.text else {}


def upload(path, title, description, tags, publish_at, category="27", lang="en"):
    """Resumable upload as a PRIVATE video scheduled to go public at publish_at (RFC3339, UTC).
    Until then the owner can veto it in YouTube Studio. Returns the video id."""
    meta = {"snippet": {"title": title[:100], "description": description[:4900], "tags": tags[:15], "categoryId": category,
                        "defaultLanguage": lang, "defaultAudioLanguage": lang},
            "status": {"privacyStatus": "private", "publishAt": publish_at, "selfDeclaredMadeForKids": False,
                       "embeddable": True, "license": "youtube",
                       "containsSyntheticMedia": os.environ.get("YT_SYNTHETIC", "false").lower() == "true"}}
    size = os.path.getsize(path)
    r = requests.post(f"{UPLOAD}/videos?uploadType=resumable&part=snippet,status", data=json.dumps(meta), timeout=60,
                      headers=_h({"Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Length": str(size),
                                  "X-Upload-Content-Type": "video/mp4"}))
    if r.status_code >= 400:
        raise RuntimeError(f"YouTube upload start failed {r.status_code}: {r.text[:500]}")
    url = r.headers["Location"]; sent = 0; chunk = 16 * 1024 * 1024
    with open(path, "rb") as f:
        while True:
            f.seek(sent); data = f.read(chunk)
            for attempt in range(6):
                try:
                    rr = requests.put(url, data=data, timeout=300, headers=_h({
                        "Content-Length": str(len(data)), "Content-Range": f"bytes {sent}-{sent + len(data) - 1}/{size}"}))
                except requests.RequestException as e:
                    print("upload: retry after", e, flush=True); time.sleep(5 * (attempt + 1)); continue
                if rr.status_code in (500, 502, 503, 504):
                    time.sleep(5 * (attempt + 1)); continue
                break
            if rr.status_code in (200, 201):
                vid = rr.json()["id"]; print("upload: done", vid, flush=True)
                return vid
            if rr.status_code == 308:
                rng = rr.headers.get("Range")
                sent = int(rng.split("-")[1]) + 1 if rng else 0
                print(f"upload: {sent * 100 // size}%", flush=True); continue
            raise RuntimeError(f"YouTube upload failed {rr.status_code}: {rr.text[:500]}")


def set_thumbnail(video_id, jpg):
    r = requests.post(f"{UPLOAD}/thumbnails/set?videoId={video_id}", data=open(jpg, "rb").read(), timeout=120,
                      headers=_h({"Content-Type": "image/jpeg"}))
    return _check(r, "thumbnail")


def video(video_id):
    r = requests.get(f"{API}/videos", params={"part": "snippet,status,statistics", "id": video_id}, headers=_h(), timeout=30)
    items = _check(r, "videos.list").get("items") or []
    return items[0] if items else None


def set_title(video_id, title):
    v = video(video_id)
    if not v:
        return None
    sn = v["snippet"]; body = {"id": video_id, "snippet": {"title": title[:100], "description": sn.get("description", ""),
                                                          "tags": sn.get("tags", []), "categoryId": sn.get("categoryId", "27")}}
    r = requests.put(f"{API}/videos?part=snippet", json=body, headers=_h(), timeout=30)
    return _check(r, "title update")


def add_to_playlist(video_id, title):
    """Adds the video to the channel playlist called `title` (created if missing). Best effort."""
    try:
        r = requests.get(f"{API}/playlists", params={"part": "snippet", "mine": "true", "maxResults": 50}, headers=_h(), timeout=30)
        pl = next((p["id"] for p in _check(r, "playlists").get("items", []) if p["snippet"]["title"] == title), None)
        if not pl:
            r = requests.post(f"{API}/playlists?part=snippet,status", headers=_h(), timeout=30,
                              json={"snippet": {"title": title}, "status": {"privacyStatus": "public"}})
            pl = _check(r, "playlist create")["id"]
        r = requests.post(f"{API}/playlistItems?part=snippet", headers=_h(), timeout=30,
                          json={"snippet": {"playlistId": pl, "resourceId": {"kind": "youtube#video", "videoId": video_id}}})
        _check(r, "playlist add")
    except Exception as e:
        print("playlist: skipped:", str(e)[:200], flush=True)


def analytics(video_ids, start, end):
    """{video_id: {views, averageViewPercentage, averageViewDuration, subscribersGained, likes, comments, shares, ctr?}}"""
    if not video_ids:
        return {}
    base = ["views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage", "subscribersGained",
            "likes", "comments", "shares"]
    out = {}
    for metrics, extra in ((base, None), (["videoThumbnailImpressions", "videoThumbnailImpressionsClickRate"], "ctr")):
        for k in range(0, len(video_ids), 40):
            ids = video_ids[k:k + 40]
            r = requests.get(ANALYTICS, headers=_h(), timeout=60, params={
                "ids": "channel==MINE", "startDate": start, "endDate": end, "metrics": ",".join(metrics),
                "dimensions": "video", "filters": "video==" + ",".join(ids), "maxResults": 200})
            if r.status_code >= 400:
                if extra:                               # impressions/CTR not offered for this channel: fine
                    print("analytics: CTR not available:", r.text[:160], flush=True); break
                raise RuntimeError(f"analytics failed {r.status_code}: {r.text[:300]}")
            j = r.json(); cols = [c["name"] for c in j.get("columnHeaders", [])]
            for row in j.get("rows", []) or []:
                d = dict(zip(cols, row)); vid = d.pop("video")
                if extra:
                    out.setdefault(vid, {})["impressions"] = d.get("videoThumbnailImpressions")
                    out[vid]["ctr"] = d.get("videoThumbnailImpressionsClickRate")
                else:
                    out.setdefault(vid, {}).update(d)
    return out
