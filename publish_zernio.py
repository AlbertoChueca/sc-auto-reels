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


def tiktok_caption(hook, caption):
    """TikTok-native caption: short, searchable keywords (TikTok is a search engine), comment bait, 4-5 hashtags."""
    import random, re
    first = re.sub(r"\s+", " ", (hook or caption.split("\n")[0])).strip()
    hidden = "answer drops in the comments" in caption.lower() or "answer in the comments" in caption.lower()
    ask = "Comment your move 👇 answer drops tomorrow" if hidden else "Comment your move before the answer 👇"
    tags = ["#chesstok", "#chess", "#chesspuzzle"] + random.sample(["#chesstips", "#learnchess", "#chesstactics",
                                                                    "#chesstiktok", "#chessforkids"], 2)
    prev = next((l for l in caption.split("\n") if l.startswith("✅ Yesterday's answer")), "")
    return (f"{first}\n" + (f"{prev}\n" if prev else "") + f"{ask}\n"
            f"Daily chess puzzle + calculation tips to get better at chess. Train free on streakchess.com\n"
            + " ".join(tags))[:2200]


def _upload(video_path):
    size = os.path.getsize(video_path)
    pre = _check(requests.post(f"{API}/media/presign", headers=_h(), json={
        "filename": os.path.basename(video_path), "contentType": "video/mp4", "size": size}, timeout=60), "presign")
    with open(video_path, "rb") as f:
        up = requests.put(pre["uploadUrl"], data=f, headers={"Content-Type": "video/mp4"}, timeout=600)
    if up.status_code >= 400:
        raise RuntimeError(f"Zernio upload error {up.status_code}: {up.text[:300]}")
    return [{"type": "video", "url": pre["publicUrl"]}]


def crosspost(video_path, hook, caption):
    """One post per platform, each with a caption written for that platform."""
    media = _upload(video_path)
    acc = _accounts()
    if not acc:
        raise RuntimeError("No YouTube/TikTok account connected in Zernio")
    done, errors = [], []
    jobs = []
    if acc.get("youtube"):
        jobs.append(("youtube", caption.replace("link in bio", "link in bio: streakchess.com"),
                     {"title": f"{(hook or 'Daily chess puzzle').strip()} ♟️ #shorts"[:100], "visibility": "public",
                      "madeForKids": os.environ.get("YT_MADE_FOR_KIDS", "true").lower() == "true", "categoryId": "27"}))
    if acc.get("tiktok"):
        jobs.append(("tiktok", tiktok_caption(hook, caption),
                     {"privacy_level": "PUBLIC_TO_EVERYONE", "allow_comment": True, "allow_duet": True,
                      "allow_stitch": True, "content_preview_confirmed": True, "express_consent_given": True}))
    for platform, text, extra in jobs:
        body = {"content": text, "mediaItems": media, "publishNow": True,
                "platforms": [{"platform": platform, "accountId": acc[platform], "platformSpecificData": extra}],
                "tags": ["chess", "chess puzzle", "chess tips", "streakchess"]}
        try:
            res = _check(requests.post(f"{API}/posts", headers=_h(), json=body, timeout=120), f"post {platform}")
            print(f"Zernio {platform} post created:", (res.get("post", res) or {}).get("_id") if isinstance(res, dict) else res, flush=True)
            done.append(platform)
        except Exception as e:
            print(f"Zernio {platform} failed: {str(e)[:300]}", flush=True); errors.append(platform)
    if not done:
        raise RuntimeError(f"Zernio: all platforms failed ({', '.join(errors)})")
    return ",".join(done) + (f" (failed: {','.join(errors)})" if errors else "")
