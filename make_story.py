"""Story reel: a unique ~10s animated mini story starring the StreakChess knight (script + illustrated
scenes generated with Google Gemini), followed by the puzzle segment from make_hype.

python make_story.py puzzle.json seed out.mp4          (needs GEMINI_API_KEY)
STORY_MOCK=1 python make_story.py ...                   (offline test with placeholder scenes)
"""
import base64, io, json, math, os, random, subprocess, sys, time
import numpy as np
import requests
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
import make_reel as R
import make_hype as HY

HERE = os.path.dirname(os.path.abspath(__file__))
W, H, FPS, SR = 1080, 1920, 30, 24000
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
    "STREAK: a cartoon black chess knight piece with a bright orange-and-yellow flame mane, big round white "
    "cartoon eyes with black pupils, a dark gray body with thick black outlines and a round base. No arms or legs: "
    "he hops, slides and tilts like a chess piece. Personality: competitive, dramatic, funny, a little cocky, "
    "obsessed with keeping his daily training streak. Style: bold flat 2D cartoon with clean thick outlines, "
    "vibrant colors, cinematic lighting, like a high-quality animated short.")

STORY_PROMPT = """You write 10-second micro stories for vertical chess reels starring a mascot.
{character}

Write ONE brand-new mini story (setup -> twist -> lead-in) that ends by leading into a chess puzzle.
The puzzle: {level} level, {side} to move, goal: {goal}.
Rules:
- Exactly 4 scenes. Total narration 22-32 words. Narration is a punchy, funny, energetic movie-trailer narrator in English.
- Each scene is a different moment/place/action. Make it visual and specific (places, props, weather, other chess pieces as characters).
- Scene 4 narration must hand over to the puzzle (e.g. "...and then he saw THIS.").
- Do NOT reuse any of these previous story ideas: {avoid}
- image_prompt: describe ONE vertical 9:16 frame: action, setting, camera framing (close-up / wide / low angle), lighting, mood.
  Always say "the knight mascot from the reference images". No text, letters or logos in the image.
- camera: one of push_in, pull_out, pan_left, pan_right, tilt_up, shake.
- sfx: one of whoosh, boom, none.
Return JSON: {{"title": str, "scenes": [{{"narration": str, "image_prompt": str, "camera": str, "sfx": str}}], "caption_hook": str}}"""


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


def write_story(level, side, goal, avoid):
    body = {"contents": [{"parts": [{"text": STORY_PROMPT.format(character=CHARACTER, level=level, side=side, goal=goal,
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
            "scenes": [{"narration": t, "image_prompt": p, "camera": c, "sfx": s} for t, p, c, s in [
                ("Day 364 of Streak's training streak.", poses[0], "push_in", "none"),
                ("Then the alarm didn't ring.", poses[1], "shake", "boom"),
                ("Eleven fifty-nine. One puzzle left.", poses[2], "pan_left", "whoosh"),
                ("And then he saw THIS.", poses[3], "push_in", "boom")]]}


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


def build(P, seed, out, mode="level"):
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

    mock = os.environ.get("STORY_MOCK") == "1"
    log = json.load(open(STORY_LOG)) if os.path.exists(STORY_LOG) else []
    story = mock_story(rng) if mock else write_story(LV["name"].title(), side, goal, [s["title"] for s in log])
    scenes = story["scenes"][:4]
    print("Story:", story["title"], flush=True)
    imgs = []
    for i, sc in enumerate(scenes):
        imgs.append(mock_image(sc["image_prompt"], i) if mock else gen_image(sc["image_prompt"], REFS))
        print(f"scene {i + 1} image ready", flush=True)

    # voice
    A = []
    for sc in scenes:
        a = R.tts(sc["narration"], voice=HY.VOICE, speed=1.1)
        nz = np.nonzero(np.abs(a) > 0.01)[0]
        A.append(a[max(0, nz[0] - 200): nz[-1] + 1500] if len(nz) else a)
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
        if s == "boom": put(fx, HY.boom(), starts[i], 0.8)
        elif s == "whoosh": put(fx, R.whoosh(0.5), starts[i] - 0.15, 1.1)
        if i: put(fx, R.whoosh(0.35), starts[i] - 0.12, 0.7)
    put(fx, HY.riser(1.6), total - 1.6, 0.9)
    tb = np.arange(n) / SR
    pad = sum(np.sin(2 * np.pi * f * tb) for f in (110, 164.8, 220)) * 0.05 * np.clip(tb / 1.5, 0, 1)
    mix = np.tanh((vo * 1.15 + fx + pad.astype(np.float32)) * 1.1) * 0.92
    wav = out.replace(".mp4", "_s.wav"); sf.write(wav, mix, SR)
    hop = SR // FPS

    words = []
    for i, sc in enumerate(scenes):
        ws = sc["narration"].split(); L = sum(len(w) + 1 for w in ws); acc = 0
        for w in ws:
            words.append((i, starts[i] + 0.12 + (len(A[i]) / SR) * acc / L * 0.95, w)); acc += len(w) + 1

    bigs = [cover(grade(cover(im, 1.0)), 1.18) for im in imgs]
    story_mp4 = out.replace(".mp4", "_story.mp4")
    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-i", wav, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "24000", "-shortest", story_mp4],
                            stdin=subprocess.PIPE)
    for fi in range(int(total * FPS)):
        t = fi / FPS
        i = int(np.searchsorted(starts, t, side="right") - 1)
        p = (t - starts[i]) / durs[i]
        fr = frame_for(bigs[i], scenes[i].get("camera", "push_in"), min(p, 1), t).convert("RGBA")
        lt = t - starts[i]
        if i and lt < 0.12:   # whip flash between scenes
            fr = Image.blend(fr, Image.new("RGBA", (W, H), (255, 255, 255, 255)), 0.6 * (1 - lt / 0.12))
        cur = [(ts, w) for si, ts, w in words if si == i and ts <= t]
        if cur:
            idx = len(cur) - 1; st = (idx // 3) * 3
            ph = HY.phrase_img([w for _, w in cur[st:idx + 1]], t - cur[-1][0], 92)
            R.paste_center(fr, ph, W / 2, 1450)
        if i == 0 and lt < 2.5:   # top label
            tag = R.pill(story.get("title", "")[:28].upper(), 34, (20, 16, 28), fg=HY.YEL, padx=30, pady=12)
            R.paste_center(fr, tag, W / 2, 170, HY.eob(lt / 0.3))
        proc.stdin.write(fr.convert("RGB").tobytes())
    proc.stdin.close(); proc.wait(); os.remove(wav)

    # puzzle segment (no hook: the story is the hook)
    puzzle_mp4 = out.replace(".mp4", "_puzzle.mp4")
    meta = HY.build(P, seed, puzzle_mp4, mode=mode, skip_hook=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", story_mp4, "-i", puzzle_mp4, "-filter_complex",
                    "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                    "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", out], check=True)
    cap_old = open(puzzle_mp4.replace(".mp4", ".txt")).read().split("\n", 1)[1]
    open(out.replace(".mp4", ".txt"), "w").write(f"{story.get('caption_hook', story['title'])}\n{cap_old}")
    for f in (story_mp4, puzzle_mp4, puzzle_mp4.replace(".mp4", ".txt")):
        if os.path.exists(f): os.remove(f)
    if not mock:
        log.append({"title": story["title"], "puzzle": P.get("id")})
        json.dump(log[-200:], open(STORY_LOG, "w"), indent=0)
        for k, im in enumerate(imgs):
            im.save(out.replace(".mp4", f"_scene{k + 1}.jpg"), quality=88)
    meta.update(story=story["title"], hook=story.get("caption_hook", story["title"]))
    return meta


if __name__ == "__main__":
    P = json.load(open(sys.argv[1]))
    print(json.dumps(build(P, int(sys.argv[2]), sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "level"), indent=1))
