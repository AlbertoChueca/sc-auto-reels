"""Second agent: an AI producer that reviews and improves every reel before it is published.

Three checkpoints (all Gemini, a few cents per month in total):
  1. improve_script(): rewrites the story script for a stronger hook, clearer link to the puzzle and a better
     call to help Vektor, using what performed best on Instagram so far (performance.json from insights.py).
  2. check_images(): looks at the 4 generated scenes next to the real mascot and flags any that are off-model,
     contain text/letters, look broken or unsafe -> those scenes are redrawn once.
  3. review_video(): watches the finished reel (a small 480p copy), scores it, rewrites the first caption line
     and the comment prompt, and rejects the reel only if it is clearly broken (the pipeline then re-renders).
Every decision is logged to review_log.jsonl so you can read what the reviewer did.
Any reviewer error is ignored: the reel always continues with the original version.
"""
import base64, datetime, io, json, os, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REVIEW_LOG = os.path.join(HERE, "review_log.jsonl")
PERF = os.path.join(HERE, "performance.json")
MIN_SCORE = float(os.environ.get("REVIEW_MIN_SCORE", "4"))   # below this the reel is re-rendered

PRODUCER = """You are a senior producer of viral short-form videos for kids aged 8-12 (and their parents), working on
"Vektor", an ongoing animated chess series for the StreakChess app (Instagram Reels, TikTok, YouTube Shorts).
Your goals, in order: kid-safe and kind; instantly clear; a scroll-stopping first 1.5 seconds; a story kids care about
that naturally leads into the chess puzzle; the viewer feels Vektor needs THEIR help; viewers comment their answer,
share with a friend and follow to see Vektor's next day."""


class RejectReel(RuntimeError):
    """The finished reel is clearly broken; the caller should render it again."""


def _log(kind, data):
    try:
        with open(REVIEW_LOG, "a") as f:
            f.write(json.dumps({"date": str(datetime.date.today()), "kind": kind, **data}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _ask(parts, temperature=0.6):
    """Gemini call returning parsed JSON."""
    import make_story as MS
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}}
    names = MS.TEXT_MODELS + [m for m in MS._available() if "flash" in m and not any(
        x in m for x in ("image", "tts", "live", "audio", "lite"))]
    last = None
    for model in dict.fromkeys(names):
        try:
            j = MS._post(model, body)
            txt = j["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(re.sub(r"^```(json)?|```$", "", txt.strip()))
        except Exception as e:
            last = e
            if " 404" not in str(e) and " 400" not in str(e):
                break
    raise last


def _jpeg_b64(im, size=512):
    im = im.copy(); im.thumbnail((size, size))
    b = io.BytesIO(); im.convert("RGB").save(b, "JPEG", quality=80)
    return base64.b64encode(b.getvalue()).decode()


# ------------------------------------------------------------------ learnings from real performance
def learnings():
    """Short text with what worked / didn't on Instagram (empty until insights are available)."""
    try:
        perf = json.load(open(PERF))
    except Exception:
        perf = {}
    import strategy
    pb = strategy.playbook_text()
    rows = [r for r in perf.values() if r.get("views")]
    if len(rows) < 4:
        return pb
    rows.sort(key=lambda r: r["views"], reverse=True)
    avg = sum(r["views"] for r in rows) / len(rows)

    def line(r):
        eng = sum(r.get(k) or 0 for k in ("likes", "comments", "shares", "saved"))
        return (f'- "{r.get("story") or r.get("hook")}" ({r.get("level")}, {r.get("mode")}): {r["views"]} views, '
                f'{eng} interactions, avg watch {r.get("ig_reels_avg_watch_time", "?")} ms')
    top, low = rows[:3], rows[-3:]
    return (f"REAL INSTAGRAM RESULTS so far ({len(rows)} reels, average {avg:.0f} views):\nBest:\n"
            + "\n".join(map(line, top)) + "\nWorst:\n" + "\n".join(map(line, low))
            + "\nLean into what the best ones have in common; avoid what the worst ones did."
            + (("\n\n" + pb) if pb else ""))


# ------------------------------------------------------------------ 1. script
def _plan_text(ep, recent):
    if not ep:
        return ""
    import series
    return (f"TODAY'S EPISODE PLAN (keep it): format = {ep['format']}; spotlight = {ep['spotlight']}; setting = {ep['setting']}.\n"
            f"SERIAL CONTINUITY (keep it): last episode = {ep.get('previously') or 'none'}; its teaser = {ep.get('teaser') or 'none'}. "
            f"Today's lesson (must stay, taught in the story and used on the puzzle): {ep['lesson'][1]} - {ep['lesson'][2]}. "
            f"Keep the fields previously, lesson_line, lesson_scene and teaser.\n"
            f"CAST (keep looks exactly): \n{series.cast_sheet()}\n"
            f"RECENT EPISODES - the new one must feel clearly DIFFERENT (plot, place, gag, emotion):\n"
            + "\n".join(f"- {r}" for r in list(recent)[-6:]) +
            "\nVektor must always be upright in every image prompt (never lying down, tipped over or fallen).")


def _brief(arms):
    if not arms:
        return ""
    import strategy
    return (f"This episode is an A/B experiment: keep its opening hook style ({arms.get('hook_style')}) and theme "
            f"({arms.get('theme')}) and narration length {strategy.WORDS.get(arms.get('story_length'), '24-34')} words; "
            f"improve everything else.")


def improve_script(story, level, side, goal, episode, arms=None, ep=None, recent=()):
    """Returns an improved story (same schema). Falls back to the original on any problem."""
    try:
        import agents
        res = _ask([{"text": f"""{PRODUCER}

{agents._brief('story')}

{learnings()}

{_brief(arms)}
{_plan_text(ep, recent)}
Here is the draft script for episode {episode}. Puzzle that follows: {level} level, {side} to move, goal: {goal}.
DRAFT:
{json.dumps(story, ensure_ascii=False, indent=1)}

1) Score the draft 1-10 for: hook (first scene grabs attention in 1.5 s), clarity for a 9-year-old, story arc,
   link between the story and the chess puzzle, the hand-over to the step-by-step method that follows, voice-friendliness
   (short spoken sentences, numbers as words, no chess notation), kid safety.
2) Rewrite it to fix every weakness. Keep EXACTLY the same JSON schema and rules: 4 scenes, total narration 24-34
   words, max 9 words per sentence, last scene has Vektor turn to the step-by-step method (no chess details in the story), image prompts describe one vertical
   frame and say "the knight mascot from the reference images" for Vektor, no text in images, camera in
   [push_in, pull_out, pan_left, pan_right, tilt_up], sfx in [whoosh, boom, none], delivery = short acting direction.
   caption_hook: max 10 words, one emoji allowed, makes kids want to comment their answer.
   screen_hook: big on-screen text for the first 2 seconds, max 6 words, no emoji, a curiosity gap that stops the scroll.
Return JSON: {{"scores": {{...}}, "overall": number, "changes": [str], "story": <the full improved story object>}}"""}])
        new = res.get("story") or {}
        sc = new.get("scenes") or []
        words = sum(len(s.get("narration", "").split()) for s in sc)
        ok = (len(sc) == 4 and all(s.get("narration") and s.get("image_prompt") for s in sc) and 16 <= words <= 42
              and not re.search(r"\b[a-h][1-8]\b|[KQRBN]x?[a-h][1-8]", " ".join(s["narration"] for s in sc)))
        _log("script", {"episode": episode, "overall": res.get("overall"), "scores": res.get("scores"),
                        "changes": res.get("changes"), "accepted": ok, "before": story.get("title"),
                        "after": new.get("title")})
        if not ok:
            print("reviewer: script rewrite rejected (format), keeping draft", flush=True)
            return story
        for k in ("title", "summary", "screen_hook", "previously", "lesson_line", "lesson_scene", "teaser"):
            new.setdefault(k, story.get(k))
        print(f"reviewer: script {res.get('overall')}/10 -> improved ({'; '.join((res.get('changes') or [])[:3])})", flush=True)
        return new
    except Exception as e:
        print("reviewer: script review skipped:", str(e)[:200], flush=True)
        return story


# ------------------------------------------------------------------ 2. images
def check_images(imgs, scenes, mascot_ref):
    """Returns {scene_index: better_image_prompt} for scenes that should be redrawn."""
    try:
        from PIL import Image
        ref = Image.open(mascot_ref).convert("RGBA")
        bg = Image.new("RGB", ref.size, (255, 255, 255)); bg.paste(ref, (0, 0), ref)
        import agents
        parts = [{"text": f"""{PRODUCER}
{agents._brief('visual')}
First image: the official Vektor mascot (reference). Then {len(imgs)} generated story scenes, in order.
For each scene check: Vektor clearly visible and on-model (black knight piece, orange-yellow flame mane, big white
cartoon eyes, no arms/legs) and STANDING UPRIGHT (lying down, tipped over, fallen or sideways = not ok); NO text, letters, numbers or logos anywhere; no broken anatomy / melted shapes;
matches its prompt; bright, readable on a phone; kid-safe.
Prompts: {json.dumps([s.get('image_prompt') for s in scenes], ensure_ascii=False)}
Return JSON: {{"scenes": [{{"index": 0, "ok": true, "problems": [str], "better_prompt": str}}]}}
Only mark ok=false for clear problems a viewer would notice."""},
                 {"inline_data": {"mime_type": "image/jpeg", "data": _jpeg_b64(bg, 384)}}]
        for im in imgs:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": _jpeg_b64(im)}})
        res = _ask(parts, 0.2)
        redo = {}
        for s in res.get("scenes", []):
            i = int(s.get("index", -1))
            if 0 <= i < len(imgs) and s.get("ok") is False:
                redo[i] = s.get("better_prompt") or scenes[i]["image_prompt"]
        _log("images", {"redo": {str(k): v for k, v in redo.items()},
                        "problems": {str(s.get("index")): s.get("problems") for s in res.get("scenes", []) if not s.get("ok", True)}})
        if redo:
            print(f"reviewer: redrawing scenes {[i + 1 for i in redo]}", flush=True)
        return redo
    except Exception as e:
        print("reviewer: image check skipped:", str(e)[:200], flush=True)
        return {}


# ------------------------------------------------------------------ 3. finished video
def review_video(path, story, caption):
    """Watches the reel. Returns (new_caption, report). Raises RejectReel if the reel is clearly broken."""
    small = path.replace(".mp4", "_review.mp4")
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-vf", "scale=360:640", "-r", "12",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-c:a", "aac", "-b:a", "48k", small],
                       check=True)
        data = base64.b64encode(open(small, "rb").read()).decode()
        first, rest = (caption.split("\n", 1) + [""])[:2]
        res = _ask([{"text": f"""{PRODUCER}
Watch this finished reel (story about Vektor + chess puzzle + call to action). Story title: {story.get('title')}.
Current Instagram caption first line: {first!r}

Check and score 1-10: hook in the first 1.5 s, story clarity, pacing (nothing too slow or too fast for kids),
any stray spoken words that are not part of the story (e.g. "say") or hiss/noise in the sound,
subtitles readable and in sync with the voice, voice natural and matching the words, the chess board and moves easy
to follow, visuals consistent and attractive, call to action clear, likelihood kids comment/share/follow.
"critical" = true ONLY if the reel is clearly broken (silent, frozen/black, unreadable, wrong/garbled voice,
inappropriate content). Then write a better FIRST caption line (max 12 words, one emoji max, written for chess players of every age,
kids and adults, invites commenting the answer) and a short comment prompt line (max 12 words).
Return JSON: {{"overall": number, "scores": {{...}}, "critical": bool, "issues": [str], "suggestions": [str],
"caption_first_line": str, "comment_prompt": str}}"""},
                    {"inline_data": {"mime_type": "video/mp4", "data": data}}], 0.4)
    except RejectReel:
        raise
    except Exception as e:
        print("reviewer: video review skipped:", str(e)[:200], flush=True)
        return caption, {}
    finally:
        if os.path.exists(small): os.remove(small)
    overall = float(res.get("overall") or 0)
    _log("video", {"story": story.get("title"), "overall": overall, "scores": res.get("scores"),
                   "critical": res.get("critical"), "issues": res.get("issues"), "suggestions": res.get("suggestions")})
    print(f"reviewer: reel scored {overall}/10" + (f" - issues: {'; '.join(res.get('issues', [])[:3])}" if res.get("issues") else ""), flush=True)
    if res.get("critical") and overall < MIN_SCORE:
        raise RejectReel(f"reviewer rejected the reel ({overall}/10): {'; '.join(res.get('issues', [])[:3])}")
    new_first = (res.get("caption_first_line") or "").strip()
    prompt = (res.get("comment_prompt") or "").strip()
    cap = caption
    if 3 <= len(new_first.split()) <= 14 and "#" not in new_first:
        cap = new_first + "\n" + rest
    if prompt and 3 <= len(prompt.split()) <= 14 and "#" not in prompt:
        cap = re.sub(r"Comment your move before watching the solution!|Comment the move and tag a friend to challenge them!",
                     prompt, cap, count=1)
    return cap, {"overall": overall, "issues": res.get("issues"), "suggestions": res.get("suggestions")}


# ------------------------------------------------------------------ 4. art director (copy + design on real frames)
ART_DIRECTOR = """You are the ART DIRECTOR and COPY CHIEF of a top kids' edutainment channel (think the polish of
Duolingo, Pixar shorts and MrBeast-level hooks). You review real frames of a vertical reel before it goes live.
Phone reality: Instagram/TikTok UI covers the top ~250 px, the bottom ~420 px (caption, username, music) and a
column of buttons on the right; anything important there is lost."""


def _frames(path, times):
    from PIL import Image
    out = []
    for t in times:
        f = path.replace(".mp4", f"_f{t:.1f}.jpg")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{max(0, t):.2f}", "-i", path, "-frames:v", "1", f], check=False)
        if os.path.exists(f):
            out.append((t, Image.open(f).convert("RGB"))); os.remove(f)
    return out


def art_direct(path, story, style, starts, story_len):
    """Looks at key frames (hook, story, board, solution, end card) and returns (new_style or None, report).
    It can only tune safe design tokens and short copy, so it can never break the reel."""
    try:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                   capture_output=True, text=True).stdout.strip() or 0)
        times = [0.6, 1.8] + [float(s) + 1.2 for s in list(starts)[1:3]] + \
                [story_len + 6, story_len + (dur - story_len) * 0.7, dur - 1.0]
        fr = _frames(path, [t for t in times if t < dur])
        import agents
        parts = [{"text": f"""{ART_DIRECTOR}
{agents._brief('visual')}

Frames (in order) of today's reel. Story: "{story.get('title')}". Current tokens:
{json.dumps({k: style.get(k) for k in ('screen_hook', 'caption_scale', 'story_caption_y', 'follow_line', 'share_line')})}

Judge 1-10: scroll-stopping hook (on-screen text in the first frames), copy quality (short, punchy, kid-friendly,
clear for parents too), typography & readability on a phone, layout inside the safe zone, visual polish / premium
feel, clarity of the chess board, strength of the end card (follow + share + app), overall shareability.
Then propose improvements ONLY through these tokens (leave a token out to keep it):
- screen_hook: max 6 words, no emoji, a curiosity gap (it is shown big over the first scene)
- caption_scale: 0.85-1.2 (subtitle size)
- story_caption_y: 1050-1350 (vertical position of story subtitles, px from top of 1920)
- follow_line: max 6 words (end card, makes people follow for the next episode)
- share_line: max 7 words (end card, makes people send it to a friend)
Return JSON: {{"overall": number, "scores": {{...}}, "issues": [str], "changes": {{token: value}}, "why": [str]}}"""}]
        for t, im in fr:
            parts.append({"text": f"frame at {t:.1f}s"})
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": _jpeg_b64(im, 540)}})
        res = _ask(parts, 0.4)
    except Exception as e:
        print("reviewer: art direction skipped:", str(e)[:200], flush=True)
        return None, {}
    ch = res.get("changes") or {}
    new = dict(style)

    def words(v, n):
        v = re.sub(r"[^\w\s'?!,.-]", "", str(v or "")).strip()
        return v if 1 <= len(v.split()) <= n else None
    if words(ch.get("screen_hook"), 6): new["screen_hook"] = words(ch["screen_hook"], 6)
    if words(ch.get("follow_line"), 6): new["follow_line"] = words(ch["follow_line"], 6)
    if words(ch.get("share_line"), 7): new["share_line"] = words(ch["share_line"], 7)
    try:
        if ch.get("caption_scale") is not None: new["caption_scale"] = round(min(1.2, max(0.85, float(ch["caption_scale"]))), 2)
        if ch.get("story_caption_y") is not None: new["story_caption_y"] = int(min(1350, max(1050, float(ch["story_caption_y"]))))
    except Exception:
        pass
    overall = float(res.get("overall") or 0)
    _log("design", {"story": story.get("title"), "overall": overall, "scores": res.get("scores"), "issues": res.get("issues"),
                    "changes": {k: v for k, v in new.items() if style.get(k) != v}, "why": res.get("why")})
    print(f"art director: {overall}/10" + (f" - {'; '.join((res.get('issues') or [])[:3])}" if res.get("issues") else ""), flush=True)
    if new == style or overall >= 9.3:          # already great, or nothing valid to change
        return None, {"overall": overall}
    return new, {"overall": overall}
