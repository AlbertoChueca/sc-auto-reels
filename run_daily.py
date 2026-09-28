"""One publishing slot.

python run_daily.py <basic|intermediate|advanced|tagfriend|carousel> [--dry-run]
- basic / intermediate / advanced: level puzzle reel (+ Story)
- tagfriend: "tag a friend" challenge reel with an easy-medium puzzle (+ Story)
- carousel: 5 puzzles (2 beginner, 2 intermediate, 1 advanced) + answers
Every post gets a random US location and 3-5 random chess hashtags.
"""
import datetime, json, os, random, sys
from pick_puzzles import pick, mark_used

slot = sys.argv[1]
dry = "--dry-run" in sys.argv or os.environ.get("DRY_RUN") == "true"
now = datetime.datetime.utcnow()
today = now.date()
seed = today.toordinal() * 24 + now.hour          # different hook/pose per slot, rotating daily
os.makedirs("out", exist_ok=True)

locs = [l for l in json.load(open("locations.json")) if l.get("id")] if os.path.exists("locations.json") else []
loc = random.Random(f"{now:%Y-%m-%d-%H}-{slot}-loc").choice(locs) if locs else None


def log(entry):
    with open("log.jsonl", "a") as f:
        f.write(json.dumps({"date": str(today), "slot": slot, **entry}) + "\n")


if slot == "carousel":
    from make_carousel import build_carousel
    puzzles, ids = [], set()
    for i, lvl in enumerate(["basic", "basic", "intermediate", "intermediate", "advanced"]):
        k = 0
        while True:
            P = pick(lvl, seed=f"{today}-car-{i}-{k}")
            if P["id"] not in ids:
                break
            k += 1
        puzzles.append(P); ids.add(P["id"])
    vids, caption = build_carousel(puzzles, f"out/{today}_carousel", seed)
    print(caption)
    if dry:
        print("DRY RUN: not publishing")
    else:
        from publish_ig import publish_carousel
        if loc: print("Location:", loc["name"])
        media = publish_carousel(vids, caption, location_id=loc and loc["id"])
        for P in puzzles:
            mark_used(P["id"])
        log({"puzzles": sorted(ids), "location": loc and loc["name"],
             "permalink": media.get("permalink"), "media_id": media.get("id")})
    sys.exit(0)

from make_reel import build
if slot == "tagfriend":
    level = random.Random(f"{now:%Y-%m-%d-%H}-tag").choice(["basic", "basic", "intermediate"])
    mode = "tagfriend"
else:
    level, mode = slot, "level"

P = pick(level, seed=f"{today}-{slot}-{now.hour}")
out = f"out/{today}_{slot}_{now.hour:02d}.mp4"
meta = build(P, seed, out, mode=mode)
caption = open(out.replace(".mp4", ".txt")).read()
print(caption)

if dry:
    print("DRY RUN: not publishing")
    sys.exit(0)

from publish_ig import publish_reel, publish_story
if loc: print("Location:", loc["name"])
media = publish_reel(out, caption, location_id=loc and loc["id"])
meta.update(location=loc and loc["name"], permalink=media.get("permalink"), media_id=media.get("id"))
mark_used(P["id"])

try:  # also share it as a Story (never blocks the reel)
    publish_story(out); meta["story"] = "ok"
except Exception as e:
    print("Story failed:", e); meta["story"] = f"error: {e}"

if os.environ.get("YT_REFRESH_TOKEN"):  # YouTube Shorts, official API (never blocks Instagram)
    try:
        from publish_youtube import upload_short
        meta["youtube"] = upload_short(out, meta["hook"], caption)
    except Exception as e:
        print("YouTube failed:", e); meta["youtube"] = f"error: {e}"

if os.environ.get("TT_REFRESH_TOKEN"):  # TikTok draft in inbox, official API (never blocks Instagram)
    try:
        from publish_tiktok import send_draft
        meta["tiktok"] = send_draft(out)
    except Exception as e:
        print("TikTok failed:", e); meta["tiktok"] = f"error: {e}"

if os.environ.get("UPLOADPOST_API_KEY"):  # YouTube Shorts + TikTok (never blocks Instagram)
    try:
        from publish_social import crosspost
        meta["crosspost"] = crosspost(out, meta["hook"], caption)
    except Exception as e:
        print("Cross-post failed:", e); meta["crosspost"] = f"error: {e}"

log({k: meta.get(k) for k in ("mode", "puzzle", "level", "rating", "hook", "location", "permalink",
                              "media_id", "sans", "story", "youtube", "tiktok", "crosspost")})
