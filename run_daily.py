"""One daily slot: pick puzzle -> render reel -> publish -> remember puzzle.

python run_daily.py <basic|intermediate|advanced> [--dry-run]
"""
import datetime, json, os, sys
from pick_puzzles import pick, mark_used
from make_reel import build

level = sys.argv[1]
dry = "--dry-run" in sys.argv or os.environ.get("DRY_RUN") == "true"
today = datetime.date.today()
seed = today.toordinal()                     # rotates hooks / mascot poses day by day

os.makedirs("out", exist_ok=True)
P = pick(level, seed=f"{today}-{level}")
out = f"out/{today}_{level}.mp4"
meta = build(P, seed, out)
caption = open(out.replace(".mp4", ".txt")).read()
print(caption)

if dry:
    print("DRY RUN: not publishing")
else:
    from publish_ig import publish_reel
    import random
    locs = [l for l in json.load(open("locations.json")) if l.get("id")] if os.path.exists("locations.json") else []
    loc = random.Random(f"{today}-{level}-loc").choice(locs) if locs else None
    if loc: print("Location:", loc["name"])
    media = publish_reel(out, caption, location_id=loc and loc["id"])
    meta["location"] = loc and loc["name"]
    meta["permalink"] = media.get("permalink")
    mark_used(P["id"])
    with open("log.jsonl", "a") as f:
        f.write(json.dumps({"date": str(today), **{k: meta[k] for k in ("puzzle", "level", "rating", "hook", "location", "permalink")}}) + "\n")
