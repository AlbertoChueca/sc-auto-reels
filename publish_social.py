"""Cross-post a reel to YouTube Shorts and TikTok through Upload-Post (audited apps, no API review needed).

Env: UPLOADPOST_API_KEY, UPLOADPOST_USER (the profile name created in upload-post.com),
     optional CROSSPOST_PLATFORMS (default "youtube,tiktok").
"""
import os, requests

URL = "https://api.upload-post.com/api/upload"


def crosspost(video_path, hook, caption):
    platforms = [p.strip() for p in os.environ.get("CROSSPOST_PLATFORMS", "youtube,tiktok").split(",") if p.strip()]
    title = f"{hook.title()} ♟️ Chess Puzzle #shorts"[:100]
    yt_desc = caption.replace("link in bio", "play free at https://streakchess.com")
    fields = [("user", os.environ["UPLOADPOST_USER"]), ("title", title), ("description", yt_desc),
              ("privacyStatus", "public"), ("categoryId", "20"),
              ("tiktok_title", caption[:2200]), ("privacy_level", "PUBLIC_TO_EVERYONE")]
    fields += [("platform[]", p) for p in platforms]
    fields += [("tags[]", t) for t in ("chess", "chess puzzle", "chess tactics", "streakchess")]
    with open(video_path, "rb") as f:
        r = requests.post(URL, headers={"Authorization": f"Apikey {os.environ['UPLOADPOST_API_KEY']}"},
                          data=fields, files={"video": (os.path.basename(video_path), f, "video/mp4")}, timeout=600)
    print("Upload-Post:", r.status_code, r.text[:500], flush=True)
    r.raise_for_status()
    return ",".join(platforms)
