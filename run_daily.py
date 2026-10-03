"""One publishing slot.

python run_daily.py <story|storytag|basic|intermediate|advanced|tagfriend> [--dry-run]

story / storytag (default daily slots): unique AI mini story + puzzle (make_story).
If anything in the story pipeline fails (Gemini down, quota, network...), the slot automatically
falls back to the trailer-style reel (make_hype) and, as a last resort, the classic reel (make_reel),
so a post always goes out. Every post: random US location, 3-5 chess hashtags, Story share and
YouTube Shorts/TikTok cross-post when configured.
"""
import datetime, json, os, random, sys, traceback
from pick_puzzles import pick, mark_used

slot = sys.argv[1]
dry = "--dry-run" in sys.argv or os.environ.get("DRY_RUN") == "true"
now = datetime.datetime.utcnow()
today = now.date()
seed = today.toordinal() * 24 + now.hour
os.makedirs("out", exist_ok=True)

locs = [l for l in json.load(open("locations.json")) if l.get("id")] if os.path.exists("locations.json") else []
loc = random.Random(f"{now:%Y-%m-%d-%H}-{slot}-loc").choice(locs) if locs else None


def log(entry):
    with open("log.jsonl", "a") as f:
        f.write(json.dumps({"date": str(today), "slot": slot, **entry}) + "\n")


# ---- choose level / mode
LEVELS = ["basic", "intermediate", "advanced"]
if slot == "story":
    level, mode = LEVELS[today.toordinal() % 3], "level"          # rotates every day
elif slot == "storytag":
    level, mode = random.Random(f"{today}-tag").choice(["basic", "intermediate"]), "tagfriend"
elif slot == "tagfriend":
    level, mode = random.Random(f"{now:%Y-%m-%d-%H}-tag").choice(["basic", "basic", "intermediate"]), "tagfriend"
else:
    level, mode = slot, "level"

P = pick(level, seed=f"{today}-{slot}-{now.hour}")
out = f"out/{today}_{slot}_{now.hour:02d}.mp4"

# ---- render with fallbacks
meta, engine = None, None
chain = (["story", "hype", "classic"] if slot in ("story", "storytag") else ["hype", "classic"])
for eng in chain:
    try:
        if eng == "story":
            if not os.environ.get("GEMINI_API_KEY"):
                raise RuntimeError("GEMINI_API_KEY not set")
            from make_story import build as b
            meta = b(P, seed, out, mode=mode)
        elif eng == "hype":
            from make_hype import build as b
            meta = b(P, seed, out, mode=mode)
        else:
            from make_reel import build as b
            meta = b(P, seed, out, mode=mode)
        engine = eng
        break
    except Exception:
        print(f"[{eng}] failed, trying next engine:\n{traceback.format_exc()[-1500:]}", flush=True)
if meta is None:
    raise SystemExit("All render engines failed")
print("engine:", engine, flush=True)
caption = open(out.replace(".mp4", ".txt")).read()
print(caption)

if dry:
    print("DRY RUN: not publishing")
    sys.exit(0)

from publish_ig import publish_reel, publish_story
if loc: print("Location:", loc["name"])
media = publish_reel(out, caption, location_id=loc and loc["id"])
meta.update(location=loc and loc["name"], permalink=media.get("permalink"), media_id=media.get("id"), engine=engine)
mark_used(P["id"])

try:  # also share it as a Story (never blocks the reel)
    publish_story(out); meta["story_share"] = "ok"
except Exception as e:
    print("Story failed:", e); meta["story_share"] = f"error: {e}"

if os.environ.get("ZERNIO_API_KEY"):  # YouTube Shorts + TikTok via Zernio (never blocks Instagram)
    try:
        from publish_zernio import crosspost as zernio_post
        meta["zernio"] = zernio_post(out, meta["hook"], caption)
    except Exception as e:
        print("Zernio failed:", e); meta["zernio"] = f"error: {e}"

log({k: meta.get(k) for k in ("engine", "mode", "puzzle", "level", "rating", "story", "hook", "location", "permalink",
                              "media_id", "sans", "story_share", "zernio")})
