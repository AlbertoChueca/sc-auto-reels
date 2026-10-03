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
        return ""
    rows = [r for r in perf.values() if r.get("views")]
    if len(rows) < 4:
        return ""
    rows.sort(key=lambda r: r["views"], reverse=True)
    avg = sum(r["views"] for r in rows) / len(rows)

    def line(r):
        eng = sum(r.get(k) or 0 for k in ("likes", "comments", "shares", "saved"))
        return (f'- "{r.get("story") or r.get("hook")}" ({r.get("level")}, {r.get("mode")}): {r["views"]} views, '
                f'{eng} interactions, avg watch {r.get("ig_reels_avg_watch_time", "?")} ms')
    top, low = rows[:3], rows[-3:]
    return (f"REAL INSTAGRAM RESULTS so far ({len(rows)} reels, average {avg:.0f} views):\nBest:\n"
            + "\n".join(map(line, top)) + "\nWorst:\n" + "\n".join(map(line, low))
            + "\nLean into what the best ones have in common; avoid what the worst ones did.")


# ------------------------------------------------------------------ 1. script
def improve_script(story, level, side, goal, episode):
    """Returns an improved story (same schema). Falls back to the original on any problem."""
    try:
        res = _ask([{"text": f"""{PRODUCER}

{learnings()}

Here is the draft script for episode {episode}. Puzzle that follows: {level} level, {side} to move, goal: {goal}.
DRAFT:
{json.dumps(story, ensure_ascii=False, indent=1)}

1) Score the draft 1-10 for: hook (first scene grabs attention in 1.5 s), clarity for a 9-year-old, story arc,
   link between the story and the chess puzzle, the final ask for the viewer's help, voice-friendliness
   (short spoken sentences, numbers as words, no chess notation), kid safety.
2) Rewrite it to fix every weakness. Keep EXACTLY the same JSON schema and rules: 4 scenes, total narration 24-34
   words, max 9 words per sentence, last scene asks the viewer to help Vektor, image prompts describe one vertical
   frame and say "the knight mascot from the reference images" for Vektor, no text in images, camera in
   [push_in, pull_out, pan_left, pan_right, tilt_up], sfx in [whoosh, boom, none], delivery = short acting direction.
   caption_hook: max 10 words, one emoji allowed, makes kids want to comment their answer.
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
        for k in ("title", "summary"):
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
        parts = [{"text": f"""{PRODUCER}
First image: the official Vektor mascot (reference). Then {len(imgs)} generated story scenes, in order.
For each scene check: Vektor clearly visible and on-model (black knight piece, orange-yellow flame mane, big white
cartoon eyes, no arms/legs); NO text, letters, numbers or logos anywhere; no broken anatomy / melted shapes;
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
subtitles readable and in sync with the voice, voice natural and matching the words, the chess board and moves easy
to follow, visuals consistent and attractive, call to action clear, likelihood kids comment/share/follow.
"critical" = true ONLY if the reel is clearly broken (silent, frozen/black, unreadable, wrong/garbled voice,
inappropriate content). Then write a better FIRST caption line (max 12 words, one emoji max, written for kids and
parents, invites commenting the answer) and a short comment prompt line (max 12 words).
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
