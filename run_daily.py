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
BATCH = os.environ.get("BATCH_INDEX", "")            # "Batch reels" workflow: several different reels in one go
seed = today.toordinal() * 24 + now.hour + (int(BATCH) * 7919 if BATCH.isdigit() else 0)
_B = f"-b{BATCH}" if BATCH else ""
os.makedirs("out", exist_ok=True)

locs = [l for l in json.load(open("locations.json")) if l.get("id")] if os.path.exists("locations.json") else []
loc = random.Random(f"{now:%Y-%m-%d-%H}-{slot}-loc{_B}").choice(locs) if locs else None


def log(entry):
    with open("log.jsonl", "a") as f:
        f.write(json.dumps({"date": str(today), "slot": slot, **entry}) + "\n")


# ---- choose level / mode
LEVELS = ["basic", "intermediate", "advanced"]
if slot in ("story", "benefit"):
    level, mode = LEVELS[today.toordinal() % 3], "level"          # rotates every day (benefit: used only as fallback)
elif slot == "storytag":
    level, mode = random.Random(f"{today}-tag").choice(["basic", "intermediate"]), "tagfriend"
elif slot == "tagfriend":
    level, mode = random.Random(f"{now:%Y-%m-%d-%H}-tag").choice(["basic", "basic", "intermediate"]), "tagfriend"
else:
    level, mode = slot, "level"

if os.environ.get("LEVEL_OVERRIDE", "auto") in LEVELS:      # manual run with a chosen difficulty
    level = os.environ["LEVEL_OVERRIDE"]
insights_msg = ""
try:                       # real Instagram results -> performance.json (the reviewer learns from them)
    import insights
    insights_msg = insights.update(); print(insights_msg, flush=True)
except Exception as e:
    insights_msg = f"insights skipped: {str(e)[:150]}"; print(insights_msg, flush=True)

agents_msg = ""
try:                       # writers' room: the 5 agents rewrite their notebooks once a day from results + comments
    import agents
    agents_msg = agents.daily_learning(); print(agents_msg, flush=True)
    import series
    try:
        _slog = json.load(open("story_log.json"))
    except Exception:
        _slog = []
    agents_msg += " | " + series.weekly_update(_slog)
except Exception as e:
    agents_msg = f"agents skipped: {str(e)[:150]}"; print(agents_msg, flush=True)

# ---- autopilot experiment: choose today's creative options (learns from past results)
arms, strat_msg = {}, ""
try:
    import strategy
    fixed = {}
    if os.environ.get("LEVEL_OVERRIDE", "auto") in LEVELS or slot not in ("story",):
        fixed["difficulty"] = level                       # manual choice / tag-a-friend keep their level
    fixed["reveal"] = "comments"                      # never show the answer in the video: it goes in the comments
    if os.environ.get("FORMAT_OVERRIDE") in ("story", "tip"):
        fixed["format"] = os.environ["FORMAT_OVERRIDE"]
    arms = strategy.choose(seed=f"{now:%Y-%m-%d-%H}-{slot}{_B}", fixed=fixed)
    level = arms.get("difficulty", level)
    if slot == "story":
        strat_msg = strategy.weekly_strategist()
    strategy.write_report()
    print("experiment:", {k: strategy.short(v) for k, v in arms.items()}, "|", strat_msg, flush=True)
except Exception as e:
    strat_msg = f"strategy skipped: {str(e)[:150]}"; print(strat_msg, flush=True)

P = pick(level, seed=f"{today}-{slot}-{now.hour}{_B}")
out = f"out/{today}_{slot}_{now.hour:02d}{_B}.mp4"

# ---- render with fallbacks
meta, engine = None, None
# Every slot gets the premium story reel (same as "Story reel test"). If the story pipeline has a transient
# problem it is retried once; only then does it fall back so a post always goes out.
chain = ["story", "story", "hype", "classic"]
if arms.get("format") == "tip" and slot in ("story", "storytag"):
    chain = ["tip"] + chain                      # calculation-tip reel (falls back to a story if anything fails)
# Benefit reels: on chosen weekdays the evening slot has Vektor explain a real benefit of StreakChess
# (illustrated scenes, only true facts from assets/app/facts.md). BENEFIT_DAYS=none disables them.
_bdays = {int(d) for d in os.environ.get("BENEFIT_DAYS", "2").split(",") if d.strip().isdigit()}   # 0=Mon .. 6=Sun
from zoneinfo import ZoneInfo as _ZI
_la_day = datetime.datetime.now(_ZI("America/Los_Angeles")).date()        # weekly benefit reel: Wednesday 5 PM PT
if slot == "benefit" or (slot == "storytag" and _la_day.weekday() in _bdays
                         and os.environ.get("LEVEL_OVERRIDE", "auto") == "auto"):
    chain = ["benefit"] + chain
    print("today's evening reel: StreakChess benefits", flush=True)
errors = []
for eng in chain:
    try:
        if eng == "tip":
            if not os.environ.get("GEMINI_API_KEY"):
                raise RuntimeError("GEMINI_API_KEY not set")
            from make_tip import build as b
            meta = b(P, seed, out, mode=mode, arms=arms)
        elif eng == "benefit":
            if not os.environ.get("GEMINI_API_KEY"):
                raise RuntimeError("GEMINI_API_KEY not set")
            from make_benefit import build as b
            meta = b(seed, out)
        elif eng == "story":
            if not os.environ.get("GEMINI_API_KEY"):
                raise RuntimeError("GEMINI_API_KEY not set")
            from make_story import build as b
            meta = b(P, seed, out, mode=mode, arms=arms)
        elif eng == "hype":
            from make_hype import build as b
            meta = b(P, seed, out, mode=mode)
        else:
            from make_reel import build as b
            meta = b(P, seed, out, mode=mode)
        engine = eng
        break
    except Exception as e:
        errors.append(f"{eng}: {str(e)[:300]}")
        print(f"[{eng}] failed, trying next engine:\n{traceback.format_exc()[-1500:]}", flush=True)
if meta is None:
    raise SystemExit("All render engines failed")
print("engine:", engine, flush=True)
try:
    import voice as _v
    voice_used = _v.ENGINE_USED
    _st = getattr(_v, "ALIGN_STATS", {})
    subs_msg = (f"subtitles: {_st.get('asr', 0)} lines from speech recognition (exact words), "
                f"{_st.get('fallback', 0)} estimated" + (" ⚠️ speech recognition unavailable" if _st.get("fallback") else ""))
except Exception:
    voice_used, subs_msg = None, "subtitles: unknown"
print(subs_msg, flush=True)
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:  # visible on the run page in GitHub
    with open(summary, "a") as f:
        ok = engine in ("story", "benefit", "tip")
        f.write(f"## {'✅ Premium story reel' if ok else '⚠️ Fallback reel (story failed)'}\n\n"
                f"- Slot: `{slot}` · level: `{level}` · mode: `{mode}`\n- Engine: `{engine}` · voice: `{voice_used}`\n"
                + (f"- Story: {meta.get('story')}\n" if meta.get("story") else "")
                + (f"- Reviewer score: {meta.get('review_score')}/10\n" if meta.get("review_score") is not None else "")
                + (f"- Art director (copy + design): {meta.get('design_score')}/10\n" if meta.get("design_score") is not None else "")
                + f"- {subs_msg}\n" + f"- {insights_msg}\n" + f"- {agents_msg}\n"
                + (f"- Experiment: {', '.join(f'{k}={v.split(chr(58))[0]}' for k, v in arms.items())}\n" if arms else "")
                + (f"- {strat_msg}\n" if strat_msg else "")
                + "".join(f"- Error: `{e}`\n" for e in errors))
caption = open(out.replace(".mp4", ".txt")).read()
# Held-back answers are also revealed in the NEXT post's caption (works on Instagram, TikTok and YouTube alike).
try:
    _prev = None
    for _l in open("log.jsonl"):
        _e = json.loads(_l)
        if _e.get("reveal") is False and _e.get("sans") and _e.get("media_id"):
            _prev = _e
    _ann = json.load(open("answers_announced.json")) if os.path.exists("answers_announced.json") else []
    if _prev and _prev["media_id"] not in _ann and _prev.get("date") != str(today):
        _first, _rest = (caption.split("\n", 1) + [""])[:2]
        caption = f"{_first}\n✅ Yesterday's answer: {' '.join(_prev['sans'])}\n{_rest}"
        if not dry:
            json.dump((_ann + [_prev["media_id"]])[-200:], open("answers_announced.json", "w"))
except Exception as _e:
    print("previous answer skipped:", _e)
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
        from publish_ig import ig_safe
        meta["zernio"] = zernio_post(ig_safe(out), meta["hook"], caption)
    except Exception as e:
        print("Zernio failed:", e); meta["zernio"] = f"error: {e}"

meta["voice"] = voice_used
meta["arms"] = arms if engine in ("story", "tip") else {}
log({k: meta.get(k) for k in ("engine", "voice", "review_score", "design_score", "arms", "mode", "puzzle", "level", "rating", "story", "hook", "location", "permalink",
                              "media_id", "sans", "reveal", "story_share", "zernio")})
