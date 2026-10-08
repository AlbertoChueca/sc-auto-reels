"""Story reel: a unique ~10s animated mini story starring the StreakChess knight (script + illustrated
scenes generated with Google Gemini), followed by the puzzle segment from make_hype.

python make_story.py puzzle.json seed out.mp4          (needs GEMINI_API_KEY)
STORY_MOCK=1 python make_story.py ...                   (offline test with placeholder scenes)
"""
import base64, io, json, math, os, random, re, subprocess, sys, time
import numpy as np
import requests
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
import make_reel as R
import make_hype as HY

HERE = os.path.dirname(os.path.abspath(__file__))
W, H, FPS, SR = 1080, 1920, 25, 24000
API = "https://generativelanguage.googleapis.com/v1beta/models"
TEXT_MODELS = [m for m in os.environ.get("GEMINI_TEXT_MODEL", "gemini-3.8-flash,gemini-3.5-flash,gemini-3-flash").split(",") if m]
IMAGE_MODELS = [m for m in os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image,gemini-2.5-flash-image").split(",") if m]


def _available():
    """Model names this API key can call with generateContent (used as a fallback when names change)."""
    try:
        r = requests.get(f"{API}?pageSize=200", headers={"x-goog-api-key": _key()}, timeout=60)
        return [m["name"].split("/")[-1] for m in r.json().get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])]
    except Exception:
        return []
STORY_LOG = os.path.join(HERE, "story_log.json")
REFS = ["happy.png", "angry.png", "thinking.png", "celebrate.png"]

CHARACTER = (
    "VEKTOR: a cartoon black chess knight piece with a bright orange-and-yellow flame mane, big round white "
    "cartoon eyes with black pupils, a dark gray body with thick black outlines and a round base. No arms or legs: "
    "he hops, slides and tilts like a chess piece. Personality: brave, funny, a bit dramatic, kind, never gives up. "
    "Style: bold flat 2D cartoon with clean thick outlines, vibrant colors, cinematic lighting, like a high-quality "
    "animated short.")

WORLD = """VEKTOR'S WORLD (keep it consistent, this is an ongoing series):
- Vektor is a young chess knight who lives in Chessville, a cozy town where chess pieces live, go to school and play chess.
- His big dream: become World Chess Champion one day. Every episode is one day of his journey to that dream.
- He gets stronger by solving puzzles every day (his daily training streak). Some days are hard, he makes mistakes,
  gets nervous, has funny little disasters, but he never gives up.
- Recurring friends (use 0-2 per episode): Coach King (wise, calm old king who trains him), Pip (a tiny cheerful pawn,
  his best friend), Bishop Blaze (his friendly rival, a bit show-off), Grandma Queen (sweet, super strong at blitz).
- Typical moments: training at sunrise, chess club, school, a tournament round, a lesson with Coach King, a blitz battle
  with Bishop Blaze, helping Pip, travelling to a new tournament, a rainy day of study, a celebration after improving.
- THE VIEWER IS VEKTOR'S TEAMMATE: every story ends with Vektor stuck on a chess position and asking the viewer for help.
  Solving the puzzle helps Vektor improve and get one step closer to his dream."""

STORY_PROMPT = """You write 10-second micro episodes for vertical chess reels starring Vektor the knight.
AUDIENCE: kids aged 8-12 who play chess (their parents watch too). Think of a great kids' animated show: funny, exciting, warm.
{character}

{world}

This is episode {episode}. Recent episodes (continue the journey naturally, do not repeat them):
{recent}

{playbook}

Write ONE new episode: a moment of Vektor's day on his way to his dream (setup -> problem -> he needs help).
TODAY'S CREATIVE BRIEF (an experiment, follow it): opening hook style = {hook_style}; theme = {theme}.
The chess problem he faces IS the puzzle that follows: {level} level, {side} to move, goal: {goal}.
Rules:
- Exactly 4 scenes. Total narration {words} words. Narration is a fun, warm storyteller in English, like a favourite
  YouTuber for kids: simple words a 9-year-old knows, energetic but conversational, never babyish.
- The story must clearly be about chess and getting better at it (why this position matters today for Vektor:
  a tournament game, Coach King's challenge, a bet with Bishop Blaze, a puzzle he must crack to keep his streak...).
- Scene 4 narration: Vektor is stuck on the position and the narrator asks the viewer to help him,
  e.g. "Can you help Vektor find the winning move?" (vary the wording every episode).
- Positive and safe: no violence, scary horror, romance, brands or real people.
- Write numbers as words. Write narration to be SPOKEN: short sentences (max 9 words), natural rhythm, contractions,
  commas for breaths. No hashtags, emojis, abbreviations or chess notation in narration.
- Each scene is a different moment/place/action. Make it visual and specific (places, props, weather, the friends above).
- Do NOT reuse any of these previous episode ideas: {avoid}
- image_prompt: describe ONE vertical 9:16 frame: action, setting, camera framing (close-up / wide / low angle), lighting, mood.
  Always say "the knight mascot from the reference images" for Vektor. Other characters are cartoon chess pieces with
  faces, same art style. No text, letters or logos in the image.
- camera: one of push_in, pull_out, pan_left, pan_right, tilt_up.
- sfx: one of whoosh, boom, none (use boom at most once).
- delivery: 3-8 word acting direction for the voice actor for that scene, varied across scenes (e.g. "hushed, building
  suspense", "excited, almost laughing", "warm and proud", "worried, then hopeful").
- summary: one sentence describing what happened in this episode (for continuity).
- caption_hook: short Instagram first line inviting kids to help Vektor (max 10 words, one emoji allowed).
- screen_hook: the BIG on-screen text shown in the first 2 seconds (max 6 words, no emoji): a curiosity gap that
  stops the scroll (e.g. "Vektor has 10 seconds left", "His rival found a trap").
Return JSON: {{"title": str, "summary": str, "scenes": [{{"narration": str, "image_prompt": str, "camera": str, "sfx": str, "delivery": str}}], "caption_hook": str, "screen_hook": str}}"""


# ----------------------------------------------------------------- Gemini
def _key():
    return os.environ["GEMINI_API_KEY"]


def _post(model, body, tries=4):
    for k in range(tries):
        r = requests.post(f"{API}/{model}:generateContent", headers={"x-goog-api-key": _key(), "Content-Type": "application/json"},
                          json=body, timeout=180)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(15 * (k + 1)); continue
        if r.status_code >= 400:
            raise RuntimeError(f"Gemini {model} {r.status_code}: {r.text[:400]}")
        return r.json()
    raise RuntimeError(f"Gemini {model}: too many retries")


def write_story(level, side, goal, avoid, episode=1, recent=(), arms=None):
    import strategy
    arms = arms or {}
    pb = strategy.playbook_text()
    body = {"contents": [{"parts": [{"text": STORY_PROMPT.format(
                character=CHARACTER, world=WORLD, level=level, side=side, goal=goal, episode=episode,
                playbook=("WHAT WORKS FOR OUR AUDIENCE (from real results):\n" + pb) if pb else "",
                hook_style=arms.get("hook_style", "your best idea"), theme=arms.get("theme", "your best idea"),
                words=strategy.WORDS.get(arms.get("story_length"), "24-34"),
                recent="\n".join(f"- {r}" for r in recent) or "- (this is the first episode)",
                avoid="; ".join(avoid[-40:]) or "none")}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 1.1}}
    names = TEXT_MODELS + [m for m in _available() if "flash" in m and not any(x in m for x in ("image", "tts", "live", "audio", "lite"))]
    j, last = None, None
    for model in dict.fromkeys(names):
        try:
            j = _post(model, body); print("text model:", model, flush=True); break
        except RuntimeError as e:
            last = e
            if " 404" not in str(e) and " 400" not in str(e): raise
    if j is None: raise last
    txt = j["candidates"][0]["content"]["parts"][0]["text"]
    story = json.loads(txt)
    assert len(story["scenes"]) >= 3
    return story


def gen_image(prompt, refs):
    parts = [{"text": f"{CHARACTER}\n\nCreate this scene with exactly the same knight character as the reference images "
                      f"(same flame mane, eyes, colors and outline style). Vertical 9:16 composition, no text.\n\nScene: {prompt}"}]
    for p in refs:
        parts.append({"inline_data": {"mime_type": "image/png",
                                      "data": base64.b64encode(open(os.path.join(HERE, "assets", "mascot", p), "rb").read()).decode()}})
    last = None
    for model in dict.fromkeys(IMAGE_MODELS + [m for m in _available() if "image" in m]):
        try:
            j = _post(model, {"contents": [{"parts": parts}],
                              "generationConfig": {"responseModalities": ["TEXT", "IMAGE"], "imageConfig": {"aspectRatio": "9:16"}}})
            for part in j["candidates"][0]["content"]["parts"]:
                d = part.get("inlineData") or part.get("inline_data")
                if d:
                    print("image model:", model, flush=True)
                    return Image.open(io.BytesIO(base64.b64decode(d["data"]))).convert("RGB")
            last = RuntimeError(f"{model}: no image in response")
            continue
        except Exception as e:
            last = e
    raise last


def mock_story(rng):
    poses = ["thinking", "angry", "burnout", "levelup"]
    return {"title": "Mock story", "caption_hook": "He almost lost his streak...",
            "scenes": [{"narration": t, "image_prompt": p, "camera": c, "sfx": s, "delivery": dl} for (t, p, c, s), dl in zip([
                ("Day three hundred of Vektor's training.", poses[0], "push_in", "none"),
                ("Then the alarm didn't ring.", poses[1], "shake", "boom"),
                ("Eleven fifty-nine. One puzzle left.", poses[2], "pan_left", "whoosh"),
                ("Can you help Vektor find the move?", poses[3], "push_in", "boom")], ["proud, cozy", "sudden panic", "hushed, tense", "slow, dramatic reveal"])]}


def mock_image(pose, i):
    bgc = [(40, 30, 80), (120, 30, 30), (20, 60, 90), (90, 40, 10)][i % 4]
    im = Image.new("RGB", (900, 1600), bgc); d = ImageDraw.Draw(im)
    for k in range(12):
        d.ellipse([k * 90 - 100, 1100 + 30 * math.sin(k), k * 90 + 200, 1700], fill=tuple(min(255, c + 25) for c in bgc))
    m = Image.open(os.path.join(HERE, "assets", "mascot", f"{pose}.png")).convert("RGBA").resize((760, 760))
    im.paste(m, (70, 520), m)
    return im


# ----------------------------------------------------------------- animation
def cover(im, scale):
    w, h = int(W * scale), int(H * scale)
    r = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * r) + 1, int(im.height * r) + 1), Image.LANCZOS)
    x, y = (im.width - w) // 2, (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def grade(im):
    im = ImageEnhance.Contrast(im).enhance(1.08); im = ImageEnhance.Color(im).enhance(1.12)
    v = Image.new("L", (W, H), 0); ImageDraw.Draw(v).ellipse([-W * 0.35, -H * 0.2, W * 1.35, H * 1.2], fill=255)
    v = v.filter(ImageFilter.GaussianBlur(160))
    dark = Image.new("RGB", (W, H), (8, 6, 14))
    return Image.composite(im, dark, v.point(lambda p: 90 + p * 165 // 255))


def frame_for(big, cam, p, t):
    """big: pre-scaled (1.18x) image; p: 0..1 progress within the scene."""
    e = HY.eio(p)
    bw, bh = big.size
    z = {"push_in": 1.0 + 0.16 * e, "pull_out": 1.16 - 0.16 * e}.get(cam, 1.08)
    vw, vh = bw / 1.18 / z * 1.0, bh / 1.18 / z
    cx, cy = bw / 2, bh / 2
    if cam == "pan_left": cx = bw / 2 + (bw - vw) * 0.45 * (0.5 - e)
    if cam == "pan_right": cx = bw / 2 - (bw - vw) * 0.45 * (0.5 - e)
    if cam == "tilt_up": cy = bh / 2 + (bh - vh) * 0.45 * (0.5 - e)
    if cam == "shake":
        cx += 14 * math.sin(t * 53) * (1 - p); cy += 10 * math.cos(t * 47) * (1 - p)
    x0 = min(max(cx - vw / 2, 0), bw - vw); y0 = min(max(cy - vh / 2, 0), bh - vh)
    return big.crop((int(x0), int(y0), int(x0 + vw), int(y0 + vh))).resize((W, H), Image.BILINEAR)


def build(P, seed, out, mode="level", arms=None):
    arms = arms or {}
    rng = random.Random(f"{P.get('id')}-{seed}-story")
    import chess
    LV = R.LEVELS[P["level"]]
    if "fen" in P:
        b = chess.Board(P["fen"]); b.push(chess.Move.from_uci(P["moves"].split()[0])); sol = P["moves"].split()[1:]
    else:
        b = chess.Board()
        for m in P["pgn"].split(): b.push_san(m)
        sol = P["sol"]
    side = "Black" if b.turn == chess.BLACK else "White"
    b2 = b.copy()
    for u in sol: b2.push(chess.Move.from_uci(u))
    mate_n = (len(sol) + 1) // 2 if b2.is_checkmate() else None
    goal = f"mate in {mate_n}" if mate_n else "win material"

    # preflight: fail fast (before paying for images) if a required file is missing
    need = [HY.F900, os.path.join(HERE, "assets", "logo_h.png")] + [os.path.join(HERE, "assets", "mascot", p) for p in REFS + ["happy.png"]]
    missing = [p for p in need if not os.path.exists(p)]
    if missing:
        raise SystemExit("Missing files in the repository: " + ", ".join(os.path.relpath(p, HERE) for p in missing))
    mock = os.environ.get("STORY_MOCK") == "1"
    log = json.load(open(STORY_LOG)) if os.path.exists(STORY_LOG) else []
    episode = len(log) + 1
    recent = [f"{s.get('title')}: {s.get('summary', '')}" for s in log[-3:]]
    story = mock_story(rng) if mock else write_story(LV["name"].title(), side, goal, [s["title"] for s in log],
                                                     episode, recent, arms)
    review_on = (not mock or os.environ.get("REVIEWER") == "force") and os.environ.get("REVIEWER", "on") != "off"
    if review_on:                                   # 2nd agent: producer review of the script
        import reviewer
        story = reviewer.improve_script(story, LV["name"].title(), side, goal, episode, arms)
        import agents                               # writers' room: hook specialist + visual director
        story = agents.hook_pass(story)
        story = agents.visual_prompts_pass(story, CHARACTER)
    scenes = story["scenes"][:4]
    print("Story:", story["title"], flush=True)
    def one_image(i):
        for attempt in range(2):
            try:
                return mock_image(scenes[i]["image_prompt"], i) if mock else gen_image(scenes[i]["image_prompt"], REFS)
            except Exception as e:
                print(f"scene {i + 1} image failed ({attempt + 1}/2): {str(e)[:200]}", flush=True)
        return None
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as ex:                     # the 4 scenes are drawn at the same time
        got = list(ex.map(one_image, range(len(scenes))))
    if review_on and any(g is not None for g in got):     # 2nd agent: redraw off-model / broken scenes once
        redo = reviewer.check_images([g if g is not None else next(x for x in got if x is not None) for g in got],
                                     scenes, os.path.join(HERE, "assets", "mascot", "happy.png"))
        if redo:
            def redraw(i):
                try:
                    return i, gen_image(redo[i], REFS)
                except Exception as e:
                    print(f"scene {i + 1} redraw failed: {str(e)[:150]}", flush=True); return i, None
            with ThreadPoolExecutor(4) as ex:
                for i, im in ex.map(redraw, list(redo)):
                    if im is not None: got[i] = im
    imgs = []
    for i, im in enumerate(got):
        if im is None:
            others = [g for g in got if g is not None]
            if not others: raise RuntimeError("could not generate any scene image")
            im = imgs[-1] if imgs else others[0]           # keep the reel alive: reuse a neighbouring scene
        imgs.append(im)
        print(f"scene {i + 1} image ready", flush=True)

    # voice: story narration + puzzle segment are recorded with the SAME engine/voice.
    # The puzzle segment is rendered first; if the voice fails half way, both parts are redone with the next engine.
    import voice
    voice.reset()
    puzzle_mp4 = out.replace(".mp4", "_puzzle.mp4")
    story_mp4 = out.replace(".mp4", "_story.mp4")
    think = __import__("strategy").THINK_FACTOR.get(arms.get("think_time"), 1.0)
    hook0 = story.get("screen_hook") or re.sub(r"[^\w\s'?!,.-]", "", story.get("caption_hook", "")).strip()
    style = {**HY.DEFAULT_STYLE, "screen_hook": " ".join(hook0.split()[:7]),
             "follow_line": "Follow for Vektor's next day", "share_line": "Send this to a chess friend"}
    if review_on:                                   # growth marketer writes the end-card lines
        style.update(agents.growth_lines(story, mode))

    def render_puzzle(st):
        return HY.build(P, seed, puzzle_mp4, mode=mode, skip_hook=True, backdrop=imgs[-1], keep_voice=True,
                        cta_lead="You helped Vektor get stronger! ", think_factor=think, style=st)

    for attempt in range(3):
        try:
            A = voice.say_many([sc["narration"] for sc in scenes], speed=1.08,
                               styles=[sc.get("delivery") for sc in scenes], one_take=True)
            meta = render_puzzle(style)
            break
        except voice.VoiceError as e:
            nxt = voice.next_engine()
            print(f"voice changed during the reel ({e}); redoing story + puzzle with: {nxt}", flush=True)
            voice.reset(nxt)
    else:
        raise RuntimeError("could not record a consistent voice")
    durs = [max(len(a) / SR + 0.35, 2.0) for a in A]
    starts = np.cumsum([0] + durs[:-1]); total = float(sum(durs)) + 0.3

    n = int(SR * (total + 0.5)); vo = np.zeros(n, np.float32); fx = np.zeros(n, np.float32)
    def put(buf, a, at, g=1.0):
        i = int(at * SR)
        if i < 0: a = a[-i:]; i = 0
        if i >= n: return
        j = min(n, i + len(a)); buf[i:j] += a[: j - i] * g
    for i, a in enumerate(A):
        put(vo, a, starts[i] + 0.12)
        s = scenes[i].get("sfx", "none")
        if i:                                   # soft, musical scene change (tonal only, no noise)
            put(fx, R.shimmer([659.3, 784.0, 880.0, 587.3][i % 4]), starts[i] - 0.05, 0.7)
        if s == "boom": put(fx, R.soft_hit(), starts[i] + 0.02, 0.6)
    put(fx, HY.riser(1.6), total - 1.6, 0.9)
    tb = np.arange(n) / SR
    pad = sum(np.sin(2 * np.pi * f * tb) for f in (110, 164.8, 220)) * 0.03 * np.clip(tb / 1.5, 0, 1)
    mix = np.tanh((vo * 1.15 + fx + pad.astype(np.float32)) * 1.1) * 0.92

    words = []
    for i, sc in enumerate(scenes):            # timings from what the voice actually says
        for ts, w in voice.align(A[i], sc["narration"]):
            words.append((i, starts[i] + 0.12 + ts, w))
    bigs = [cover(grade(cover(im, 1.0)), 1.18) for im in imgs]
    LEAK = [None]

    def render_story(st):
        wav = out.replace(".mp4", "_s.wav"); sf.write(wav, mix, SR)
        cy = int(min(max(st.get("story_caption_y", 1270), 1000), HY.SAFE_BOTTOM - 120))
        hook_img = None
        if st.get("screen_hook"):
            hook_img = HY.phrase_img(st["screen_hook"].split(), 9, int(92 * st.get("caption_scale", 1.0)))
        proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                                 "-r", str(FPS), "-i", "-", "-i", wav, "-shortest"] + HY.enc_args(story_mp4),
                                stdin=subprocess.PIPE)
        for fi in range(int(total * FPS)):
            t = fi / FPS
            i = int(np.searchsorted(starts, t, side="right") - 1)
            p = (t - starts[i]) / durs[i]
            fr = frame_for(bigs[i], scenes[i].get("camera", "push_in"), min(p, 1), t).convert("RGBA")
            lt = t - starts[i]
            if i and lt < 0.35:   # warm light-leak between scenes (no white flash)
                k = 1 - lt / 0.35
                if LEAK[0] is None:                       # blurred once, then only its opacity changes
                    leak = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(leak)
                    ld.ellipse([-W * 0.4, -H * 0.2, W * 0.9, H * 0.6], fill=(255, 170, 70, 150))
                    LEAK[0] = leak.filter(ImageFilter.GaussianBlur(120))
                lk = LEAK[0].copy(); lk.putalpha(LEAK[0].getchannel("A").point(lambda v, k=k: int(v * k)))
                fr.alpha_composite(lk)
            # cinematic letterbox gradient top/bottom for legibility and a premium look
            fr.alpha_composite(HY.vignette())
            if i == 0 and t < 2.6 and hook_img is not None:   # on-screen hook: the first thing people read
                a_ = HY.eob(t / 0.25) * (1 if t < 2.3 else max(0, 1 - (t - 2.3) / 0.3))
                R.paste_center(fr, HY.band_img(hook_img.height + 70), W / 2, 470, a_)
                R.paste_center(fr, hook_img, W / 2, 470, a_)
            cur = [(ts, w) for si, ts, w in words if si == i and ts <= t]
            if cur:
                idx = len(cur) - 1; st_ = (idx // 3) * 3
                ph = HY.phrase_img([w for _, w in cur[st_:idx + 1]], t - cur[-1][0], int(86 * st.get("caption_scale", 1.0)))
                R.paste_center(fr, HY.band_img(ph.height + 80), W / 2, cy)
                R.paste_center(fr, ph, W / 2, cy)
            if i == 0 and lt < 2.6:   # series badge
                tag = R.pill(f"VEKTOR · DAY {episode}", 34, (20, 16, 28), fg=HY.YEL, padx=30, pady=12)
                R.paste_center(fr, tag, W / 2, 300, HY.eob(lt / 0.3))
            proc.stdin.write(HY.grain(fr, fi))
        proc.stdin.close(); proc.wait(); os.remove(wav)

    def join():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", story_mp4, "-i", puzzle_mp4, "-filter_complex",
                        "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]"]
                       + HY.enc_args(out, scale=False), check=True)

    render_story(style); join()
    art = {}
    if review_on:                     # 2nd agent (art director): checks copy + design on real frames, one revision
        new_style, art = reviewer.art_direct(out, story, style, starts, total)
        if new_style and new_style != style:
            print("art director: re-rendering with", {k: v for k, v in new_style.items() if style.get(k) != v}, flush=True)
            style = new_style
            meta = render_puzzle(style)            # voice takes are cached: no new recording
            render_story(style); join()
    cap_old = open(puzzle_mp4.replace(".mp4", ".txt")).read().split("\n", 1)[1]
    caption = f"{story.get('caption_hook', story['title'])}\n{cap_old}"
    review = {}
    if review_on:                                   # 2nd agent: watch the finished reel, polish the caption
        caption, review = reviewer.review_video(out, story, caption)   # raises RejectReel if clearly broken
        caption = agents.growth_caption(caption, story, review)         # growth marketer: final caption
    open(out.replace(".mp4", ".txt"), "w").write(caption)
    for f in (story_mp4, puzzle_mp4, puzzle_mp4.replace(".mp4", ".txt")):
        if os.path.exists(f): os.remove(f)
    if not mock:
        log.append({"title": story["title"], "summary": story.get("summary", ""), "puzzle": P.get("id")})
        json.dump(log[-200:], open(STORY_LOG, "w"), indent=0)
        for k, im in enumerate(imgs):
            im.save(out.replace(".mp4", f"_scene{k + 1}.jpg"), quality=88)
    meta.update(story=story["title"], hook=story.get("caption_hook", story["title"]), arms=arms,
                review_score=review.get("overall"), design_score=art.get("overall"))
    return meta


if __name__ == "__main__":
    P = json.load(open(sys.argv[1]))
    print(json.dumps(build(P, int(sys.argv[2]), sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "level"), indent=1))
