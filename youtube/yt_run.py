"""One run of the StreakChess long-video channel (called by .github/workflows/youtube-long.yml).

1. Pull YouTube Analytics for our past videos -> yt_performance.json (the autopilot's rewards).
2. Thumbnail/title rescue: a 3-10 day old video with clearly low click-through gets its alternative thumbnail + title.
3. Mondays: strategist rewrites the playbook. Always: yt_report.md.
4. Choose this video's experiment, write the plan, record the voice, render, upload as PRIVATE scheduled to go public
   ~24 h later (the veto window), set the thumbnail, add to the format playlist, log everything.

Env: DRY_RUN=1 (render only), YT_FORMAT=lesson|challenge|legendary (force), YT_MOCK=1 (offline test).
"""
import datetime, json, os, shutil, statistics, sys, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import yt_strategy as ST                                   # noqa: E402

DRY = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
OUT = os.path.join(ROOT, "out", "youtube")
THUMBS = os.path.join(HERE, "thumbs")
APP_URL = os.environ.get("APP_URL", "streakchess.com")
PUBLISH_HOUR_UTC = int(os.environ.get("YT_PUBLISH_HOUR_UTC", "21"))      # 21 UTC = 17:00 New York (summer)
PLAYLISTS = {"lesson": "Calculation Lessons", "challenge": "Puzzle Challenges", "legendary": "Legendary Games"}
SUMMARY = []


def say(*a):
    msg = " ".join(str(x) for x in a); print(msg, flush=True); SUMMARY.append(msg)


def log_entries():
    try:
        return [json.loads(l) for l in open(ST.LOG) if l.strip()]
    except FileNotFoundError:
        return []


def update_perf():
    import yt_api as API
    entries = [e for e in log_entries() if e.get("video_id")]
    if not entries:
        return "insights: no videos yet"
    try:
        perf = json.load(open(ST.PERF))
    except Exception:
        perf = {}
    start = min(e["date"] for e in entries)
    data = API.analytics([e["video_id"] for e in entries], start, datetime.date.today().isoformat())
    for e in entries:
        d = data.get(e["video_id"])
        if d is None:
            continue
        if d.get("ctr") is not None and d["ctr"] <= 1:          # API gives a fraction on some channels
            d["ctr"] = round(d["ctr"] * 100, 2)
        rec = perf.get(e["video_id"], {})
        rec.update(d, date=e["publish_date"], arms=e["arms"], title=rec.get("title", e["title"]))
        perf[e["video_id"]] = rec
    json.dump(perf, open(ST.PERF, "w"), indent=1)
    return f"insights: {len(data)} videos updated"


def rescue_thumbnails():
    """Swap to the B thumbnail + alt title when CTR is clearly below the channel's typical CTR (once per video)."""
    import yt_api as API
    try:
        perf = json.load(open(ST.PERF))
    except Exception:
        return "rescue: no data"
    ctrs = [r["ctr"] for r in perf.values() if r.get("ctr") and (r.get("impressions") or 0) > 300]
    if len(ctrs) < 4:
        return "rescue: not enough CTR data yet"
    med = statistics.median(ctrs); done = []
    today = datetime.date.today()
    for e in log_entries():
        vid = e.get("video_id"); r = perf.get(vid or "", {})
        age = (today - datetime.date.fromisoformat(e["publish_date"])).days
        if not vid or r.get("swapped") or not (3 <= age <= 10) or not r.get("ctr") or (r.get("impressions") or 0) < 300:
            continue
        if r["ctr"] < 0.75 * med:
            b = os.path.join(THUMBS, f"{vid}_b.jpg")
            try:
                if os.path.exists(b):
                    API.set_thumbnail(vid, b)
                if e.get("alt_title"):
                    API.set_title(vid, e["alt_title"])
                r["swapped"] = today.isoformat(); r["ctr_before_swap"] = r["ctr"]; done.append(vid)
            except Exception as ex:
                say("rescue failed for", vid, str(ex)[:200])
    json.dump(perf, open(ST.PERF, "w"), indent=1)
    return f"rescue: swapped {done or 'none'} (median CTR {med:.1f}%)"


def publish_time(now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    t = (now + datetime.timedelta(hours=24)).replace(minute=0, second=0, microsecond=0)
    while t.hour != PUBLISH_HOUR_UTC:
        t += datetime.timedelta(hours=1)
    return t


def description(plan, chapters):
    import yt_render as RN
    lines = [plan.get("description", "").strip(), "",
             f"🧠 Train your calculation every day (free): https://{APP_URL}", "",
             "Chapters:"]
    lines += [f"{RN.fmt_ts(t)} {name}" for t, name in chapters]
    lines.append("")
    if plan["format"] in ("lesson", "challenge"):
        lines.append("Puzzles from the Lichess open puzzle database (CC0).")
    lines += ["", "#chess #chesstactics #chesspuzzle"]
    return "\n".join(lines)


def main():
    today = datetime.date.today()
    if not DRY and not os.environ.get("YT_MOCK") and not os.environ.get("YT_REFRESH_TOKEN"):
        say("YouTube credentials missing (YT_CLIENT_ID / YT_CLIENT_SECRET / YT_REFRESH_TOKEN): nothing done. "
            "See youtube/LEEME_YOUTUBE.md")
        return None
    if not os.environ.get("YT_MOCK") and not DRY:
        for step in (update_perf, rescue_thumbnails):
            try:
                say(step())
            except Exception as e:
                say(f"{step.__name__} skipped:", str(e)[:300])
    try:
        if not os.environ.get("YT_MOCK"):
            say(ST.weekly_strategist())
    except Exception as e:
        say("strategist skipped:", str(e)[:300])
    ST.write_report()

    fixed = {"format": os.environ.get("YT_FORMAT")} if os.environ.get("YT_FORMAT") in ST.DEFAULT_ARMS["format"] else None
    arms = ST.choose(seed=f"{today}-yt", fixed=fixed)
    say("experiment:", json.dumps({k: ST.short(v) for k, v in arms.items()}))
    import yt_script as SC, yt_render as RN
    used_games = [e.get("sources", {}).get("game") for e in log_entries()]
    plan = SC.build(arms, seed=f"{today}-yt", used_games=used_games)
    words = SC.word_count(plan)
    say(f"plan: {plan['format']} · {len(plan['chapters'])} chapters · {words} words · title: {plan['title']}")
    shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT, exist_ok=True)
    json.dump(plan, open(os.path.join(OUT, "plan.json"), "w"), indent=1)
    res = RN.render(plan, OUT)
    mins = res["duration"] / 60
    say(f"render: {mins:.1f} min, {len(res['chapters'])} chapters")
    if mins < 6 and not os.environ.get("YT_MOCK"):
        raise SystemExit(f"video too short ({mins:.1f} min): not publishing")
    desc = description(plan, res["chapters"])
    open(os.path.join(OUT, "description.txt"), "w").write(desc)
    entry = {"date": today.isoformat(), "format": plan["format"], "arms": arms, "title": plan["title"],
             "alt_title": plan["alt_title"], "duration_min": round(mins, 1), "words": words, "sources": plan["sources"]}
    if DRY or os.environ.get("YT_MOCK"):
        say("dry run: video not uploaded (see the workflow artifacts)")
        return entry
    import yt_api as API
    when = publish_time()
    vid = API.upload(res["video"], plan["title"], desc, plan["tags"] or ["chess", "chess tactics"], when.strftime("%Y-%m-%dT%H:%M:%SZ"))
    try:
        API.set_thumbnail(vid, res["thumbs"][0])
    except Exception as e:
        say("thumbnail failed (custom thumbnails need a verified channel):", str(e)[:200])
    os.makedirs(THUMBS, exist_ok=True)
    shutil.copy(res["thumbs"][1], os.path.join(THUMBS, f"{vid}_b.jpg"))
    API.add_to_playlist(vid, PLAYLISTS[plan["format"]])
    entry.update(video_id=vid, publish_date=when.date().isoformat(), publish_at=when.isoformat())
    with open(ST.LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    note = (f"## Nuevo vídeo programado: {plan['title']}\n\n"
            f"- Se publica solo el **{when.strftime('%Y-%m-%d %H:%M')} UTC** ({mins:.1f} min, formato {plan['format']}).\n"
            f"- Revisarlo: https://studio.youtube.com/video/{vid}/edit\n"
            f"- **Para vetarlo**: en YouTube Studio cambia la visibilidad a Privado (sin programar) o bórralo.\n"
            f"- Título alternativo (si el CTR sale bajo se cambia solo): {plan['alt_title']}\n")
    open(os.path.join(OUT, "notify.md"), "w").write(note)
    say(f"uploaded {vid}, public at {when.isoformat()}")
    return entry


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        SUMMARY.append("FAILED:\n" + traceback.format_exc()[-1500:]); raise
    finally:
        s = os.environ.get("GITHUB_STEP_SUMMARY")
        if s:
            with open(s, "a") as f:
                f.write("### StreakChess YouTube\n\n" + "\n".join(f"- {x}" for x in SUMMARY) + "\n")
