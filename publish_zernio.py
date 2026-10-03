"""Cross-post a reel to YouTube Shorts + TikTok through Zernio (free for up to 2 connected accounts).

Env: ZERNIO_API_KEY. Optional: ZERNIO_YT_ACCOUNT / ZERNIO_TT_ACCOUNT (account IDs);
if missing they are looked up automatically from the connected accounts.
"""
import os, requests

API = "https://zernio.com/api/v1"


def _h():
    return {"Authorization": f"Bearer {os.environ['ZERNIO_API_KEY']}"}


def _check(r, what):
    if r.status_code >= 400:
        raise RuntimeError(f"Zernio {what} error {r.status_code}: {r.text[:500]}")
    return r.json() if r.content else {}


def _accounts():
    ids = {"youtube": os.environ.get("ZERNIO_YT_ACCOUNT"), "tiktok": os.environ.get("ZERNIO_TT_ACCOUNT")}
    if all(ids.values()):
        return ids
    data = _check(requests.get(f"{API}/accounts", headers=_h(), timeout=60), "accounts")
    items = data.get("accounts", data if isinstance(data, list) else data.get("data", []))
    for a in items:
        p = (a.get("platform") or "").lower()
        if p in ids and not ids[p]:
            ids[p] = a.get("_id") or a.get("id")
    print("Zernio accounts:", {k: bool(v) for k, v in ids.items()}, flush=True)
    return {k: v for k, v in ids.items() if v}


def crosspost(video_path, hook, caption):
    size = os.path.getsize(video_path)
    pre = _check(requests.post(f"{API}/media/presign", headers=_h(), json={
        "filename": os.path.basename(video_path), "contentType": "video/mp4", "size": size}, timeout=60), "presign")
    with open(video_path, "rb") as f:
        up = requests.put(pre["uploadUrl"], data=f, headers={"Content-Type": "video/mp4"}, timeout=600)
    if up.status_code >= 400:
        raise RuntimeError(f"Zernio upload error {up.status_code}: {up.text[:300]}")
    media = [{"type": "video", "url": pre["publicUrl"]}]
    acc = _accounts()
    platforms = []
    if acc.get("youtube"):
        platforms.append({"platform": "youtube", "accountId": acc["youtube"], "platformSpecificData": {
            "title": f"{hook.title()} ♟️ Chess Puzzle #shorts"[:100], "visibility": "public",
            "madeForKids": os.environ.get("YT_MADE_FOR_KIDS", "true").lower() == "true", "categoryId": "27"}})
    if acc.get("tiktok"):
        platforms.append({"platform": "tiktok", "accountId": acc["tiktok"], "platformSpecificData": {
            "privacy_level": "PUBLIC_TO_EVERYONE", "allow_comment": True, "allow_duet": True,
            "allow_stitch": True, "content_preview_confirmed": True, "express_consent_given": True}})
    if not platforms:
        raise RuntimeError("No YouTube/TikTok account connected in Zernio")
    body = {"content": caption.replace("link in bio", "link in bio: streakchess.com"), "mediaItems": media,
            "publishNow": True, "platforms": platforms,
            "tags": ["chess", "chess puzzle", "chess tactics", "streakchess"]}
    res = _check(requests.post(f"{API}/posts", headers=_h(), json=body, timeout=120), "post")
    print("Zernio post created:", res.get("post", res).get("_id") if isinstance(res, dict) else res, flush=True)
    return ",".join(p["platform"] for p in platforms)
