"""Renders a long-video plan (yt_script) to a 1920x1080 MP4, plus two thumbnails and the YouTube chapters.

Approach: the whole narration is recorded first (so the total length is known), then the video is built as a list
of still "shots" (one image + how many frames it lasts) that ffmpeg joins at 25 fps. Moving pieces are a few
extra frames each. This keeps a 10-minute render to a few minutes on a GitHub runner.
"""
import json, math, os, re, subprocess, sys, tempfile
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import chess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import make_reel as R                                      # noqa: E402

W, H, FPS, SR = 1920, 1080, 25, 24000
MOCK = bool(os.environ.get("YT_MOCK"))
F_BIG = os.path.join(ROOT, "fonts", "Nunito-900.ttf")
F_TXT = os.path.join(ROOT, "fonts", "Poppins-Bold.ttf")
NAVY, PURPLE, GOLD, ORANGE, YELLOW, WHITE = (20, 17, 40), (143, 135, 241), (232, 192, 96), (242, 98, 46), (255, 216, 77), (255, 255, 255)
SOFT = (196, 190, 235)
BX, BY = 70, 68                                            # board position (board is 944 px: make_reel.SQ * 8)
PX0, PX1 = 1090, 1860                                      # right panel
COACH = ("You are the voice of StreakChess, a friendly, sharp chess coach explaining at the board to one student. "
         "Sound like a real person: clear, confident, warm, curious, natural rhythm and pitch, a little energy, "
         "never robotic, never a flat announcer, never over the top.")


def fnt(path, size, _c={}):
    k = (path, size)
    if k not in _c:
        _c[k] = ImageFont.truetype(path, size)
    return _c[k]


def wrap(text, f, maxw):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if f.getlength(t) > maxw and cur:
            lines.append(cur); cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def text_block(d, text, path, size, box, fill=WHITE, align="center", max_lines=4, stroke=0, min_size=30, lh=1.18):
    """Draw wrapped text centred inside box=(x0, y0, x1, y1), shrinking the font until it fits."""
    x0, y0, x1, y1 = box
    while True:
        f = fnt(path, size); lines = wrap(text, f, x1 - x0)
        h = int(size * lh) * len(lines)
        if (len(lines) <= max_lines and h <= y1 - y0) or size <= min_size:
            break
        size -= 4
    y = y0 + (y1 - y0 - h) / 2
    for ln in lines[:max_lines]:
        w = f.getlength(ln)
        x = x0 + ((x1 - x0 - w) / 2 if align == "center" else 0)
        d.text((x, y), ln, font=f, fill=fill, stroke_width=stroke, stroke_fill=NAVY)
        y += int(size * lh)


_BG = {}


def background():
    if "bg" not in _BG:
        y, x = np.mgrid[0:H, 0:W]
        d = np.clip(np.sqrt(((x - W * 0.3) / W) ** 2 + ((y - H * 0.4) / H) ** 2) / 0.8, 0, 1)[..., None]
        c1, c2 = np.array([58, 48, 128]), np.array(NAVY)
        _BG["bg"] = Image.fromarray((c1 * (1 - d) ** 1.4 + c2 * (1 - (1 - d) ** 1.4)).astype(np.uint8), "RGB").convert("RGBA")
    return _BG["bg"].copy()


_LOGO = {}


def logo(width):
    if width not in _LOGO:
        im = Image.open(os.path.join(ROOT, "assets", "logo_h_white.png")).convert("RGBA")
        _LOGO[width] = im.resize((width, int(im.height * width / im.width)), Image.LANCZOS)
    return _LOGO[width]


def pill(d, text, x, y, size=30, bg=GOLD, fg=NAVY, center=False):
    f = fnt(F_TXT, size); w = f.getlength(text)
    if center:
        x = x - (w + 48) / 2
    d.rounded_rectangle([x, y, x + w + 48, y + size + 26], (size + 26) // 2, fill=bg)
    d.text((x + 24, y + 9), text, font=f, fill=fg)


def board_layer(fen, flip, hl=(), red=None, hide=None, arrows=()):
    b = chess.Board(fen)
    im = R.draw_board(b, flip, highlights=hl, red=red, hide=hide)
    for u in arrows:
        m = chess.Move.from_uci(u); R.draw_arrow(im, m.from_square, m.to_square, flip)
    return im


def compose(chapter, shot, progress):
    """One full frame. shot keys: kind, fen, flip, hl, red, arrows, sub, card, title, subtitle, seconds, left, total, prompt,
    float=(piece_img, x, y) for a moving piece, hide=square."""
    im = background(); d = ImageDraw.Draw(im)
    kind = shot["kind"]
    if kind == "title":
        d.text((W / 2 - fnt(F_TXT, 30).getlength(chapter.upper()) / 2, 300), chapter.upper(), font=fnt(F_TXT, 30), fill=GOLD)
        text_block(d, shot["title"], F_BIG, 120, (180, 360, W - 180, 640), max_lines=3)
        if shot.get("subtitle"):
            text_block(d, shot["subtitle"], F_TXT, 40, (200, 660, W - 200, 740), fill=SOFT, max_lines=1)
        lg = logo(360); im.alpha_composite(lg, (int(W / 2 - lg.width / 2), 860))
    elif shot.get("fen"):
        bl = board_layer(shot["fen"], shot.get("flip"), shot.get("hl", ()), shot.get("red"), shot.get("hide"), shot.get("arrows", ()))
        if shot.get("float"):
            pimg, fx, fy = shot["float"]; bl.alpha_composite(pimg, (int(fx), int(fy)))
        card = R.card(bl)
        sh = Image.new("RGBA", card.size, (0, 0, 0, 0)); ImageDraw.Draw(sh).rounded_rectangle([0, 0, card.width - 1, card.height - 1], 34, fill=(0, 0, 0, 120))
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)), (BX - 22 + 8, BY - 22 + 14))
        im.alpha_composite(card, (BX - 22, BY - 22))
        pill(d, chapter, PX0, 70, 28)
        if kind == "countdown":
            pill(d, shot["prompt"], (PX0 + PX1) / 2, 200, 40, bg=WHITE, fg=NAVY, center=True)
            cx, cy, r = (PX0 + PX1) / 2, 520, 170
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 50), width=22)
            frac = shot["left"] / max(1, shot["total"])
            col = ORANGE if shot["left"] <= 3 else YELLOW
            if frac > 0:
                d.arc([cx - r, cy - r, cx + r, cy + r], -90, -90 + 360 * frac, fill=col, width=22)
            n = str(shot["left"]); f = fnt(F_BIG, 150)
            d.text((cx - f.getlength(n) / 2, cy - 105), n, font=f, fill=WHITE)
            text_block(d, "Pause the video if you need more time", F_TXT, 36, (PX0, 740, PX1, 830), fill=SOFT, max_lines=2)
        else:
            if shot.get("card"):
                text_block(d, shot["card"], F_BIG, 76, (PX0, 200, PX1, 560), fill=YELLOW, max_lines=4)
            if shot.get("sub"):
                text_block(d, shot["sub"], F_TXT, 40, (PX0, 600 if shot.get("card") else 260, PX1, 960), max_lines=6)
        lg = logo(230); im.alpha_composite(lg, (PX1 - lg.width, H - lg.height - 40))
    else:                                                    # talking slide without board
        pill(d, chapter, 120, 70, 28)
        if shot.get("card"):
            text_block(d, shot["card"], F_BIG, 110, (160, 200, W - 160, 600), fill=YELLOW, max_lines=3)
            text_block(d, shot.get("sub", ""), F_TXT, 46, (220, 640, W - 520, 960), max_lines=5)
        else:
            text_block(d, shot.get("sub", ""), F_BIG, 78, (180, 220, W - 520, 900), max_lines=6)
        m = R.mascot("thinking" if shot.get("card") else "happy", 380)
        im.alpha_composite(m, (W - 450, H - 470))
        lg = logo(230); im.alpha_composite(lg, (120, H - lg.height - 50))
    d.rectangle([0, H - 8, W, H], fill=(255, 255, 255, 25))
    d.rectangle([0, H - 8, int(W * progress), H], fill=GOLD)
    return im.convert("RGB")


# ------------------------------------------------------------------ audio
def music(n_samples):
    """Very soft ambient pad (Am - F - C - G), tonal only, under the narration."""
    t = np.arange(n_samples) / SR
    chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (130.81, 196.0, 261.63), (196.0, 246.94, 293.66)]
    bar = 8.0; out = np.zeros(n_samples, np.float32)
    for k in range(int(n_samples / SR / bar) + 1):
        a, b = int(k * bar * SR), min(n_samples, int((k + 1) * bar * SR + SR * 1.5))
        if a >= n_samples:
            break
        tt = np.arange(b - a) / SR
        env = np.clip(tt / 1.5, 0, 1) * np.clip((bar + 1.5 - tt) / 1.5, 0, 1)
        s = sum(np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * f * 2 * tt) for f in chords[k % 4])
        out[a:b] += (s * env / 4).astype(np.float32)
    lfo = 0.85 + 0.15 * np.sin(2 * np.pi * t / 13)
    return out * lfo.astype(np.float32)


def record(plan):
    """Synthesize every spoken line. Returns {(ci, bi): clip}. One engine for the whole video."""
    import voice as V
    V.NARRATOR = COACH
    if os.environ.get("YT_VOICE"):
        V.GEMINI_VOICE = os.environ["YT_VOICE"]
    jobs = [(ci, bi, b["text"], "punchy, intriguing, a hint of suspense" if ci == 0 else
             "clear, confident and warm, like a coach explaining at the board")
            for ci, c in enumerate(plan["chapters"]) for bi, b in enumerate(c["beats"]) if b.get("text")]
    if MOCK:
        return {(ci, bi): np.zeros(int(SR * (0.4 + len(t.split()) / 2.6)), np.float32) for ci, bi, t, _ in jobs}
    force = None
    for attempt in range(3):
        V.reset(force); out = {}
        try:
            for k in range(0, len(jobs), 12):                     # 12 lines per batch (3 recorded in parallel)
                part = jobs[k:k + 12]
                clips = V.say_many([j[2] for j in part], styles=[j[3] for j in part])
                for j, c in zip(part, clips):
                    out[(j[0], j[1])] = c
                print(f"voice: {min(k + 12, len(jobs))}/{len(jobs)} lines", flush=True)
            return out
        except V.VoiceError as e:
            print("voice engine failed mid-video, redoing with another voice:", e, flush=True)
            force = V.next_engine()
    raise RuntimeError("voice failed")


# ------------------------------------------------------------------ timeline
def _sec(n_frames):
    return n_frames / FPS


def render(plan, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    clips = record(plan)
    # pass 1: timeline (shots without pixels), audio events, chapter starts
    shots, events, chapters = [], [], []
    f = 0
    for ci, c in enumerate(plan["chapters"]):
        chapters.append((f, c["title"]))
        for bi, b in enumerate(c["beats"]):
            clip = clips.get((ci, bi))
            if b["t"] == "title":
                n = int(2.2 * FPS)
                shots.append((dict(kind="title", title=b["text"], subtitle=b.get("sub")), n, c["title"]))
                events.append((f, R.shimmer(), 0.9, False)); f += n
            elif b["t"] == "say":
                n = math.ceil((len(clip) / SR + 0.35) * FPS)
                shots.append((dict(kind="say", fen=b.get("fen"), flip=b.get("flip"), sub=b["text"], card=b.get("card"),
                                   arrows=b.get("arrows", ()), hl=[chess.parse_square(s) for s in b.get("hl", [])]), n, c["title"]))
                events.append((f + 3, clip, 1.0, True)); f += n
            elif b["t"] == "countdown":
                for left in range(b["seconds"], 0, -1):
                    shots.append((dict(kind="countdown", fen=b["fen"], flip=b["flip"], prompt=b["prompt"], left=left,
                                       total=b["seconds"]), FPS, c["title"]))
                    events.append((f, R.tick(left <= 3), 0.8, False)); f += FPS
                shots.append((dict(kind="countdown", fen=b["fen"], flip=b["flip"], prompt=b["prompt"], left=0,
                                   total=b["seconds"]), int(0.6 * FPS), c["title"]))
                events.append((f, R.soft_hit(), 0.7, False)); f += int(0.6 * FPS)
            elif b["t"] == "move":
                bd = chess.Board(b["fen"]); mv = chess.Move.from_uci(b["uci"])
                piece = bd.piece_at(mv.from_square); after = bd.copy(); after.push(mv)
                x0, y0 = R.sq_xy(mv.from_square, b["flip"]); x1, y1 = R.sq_xy(mv.to_square, b["flip"])
                pimg = R.piece_img(piece, R.SQ); steps = 8
                for k in range(1, steps + 1):
                    e = R.ease_in_out(k / steps)
                    shots.append((dict(kind="move", fen=b["fen"], flip=b["flip"], hide=mv.from_square, hl=[mv.from_square],
                                       float=(pimg, x0 + (x1 - x0) * e, y0 + (y1 - y0) * e), sub=b.get("text"),
                                       card=None if b.get("text") else b.get("label")), 1, c["title"]))
                f += steps
                events.append((f, R.place(), 0.9, False))
                red = after.king(after.turn) if after.is_check() else None
                hold = math.ceil((len(clip) / SR + 0.3) * FPS) if clip is not None else int(0.45 * FPS)
                shots.append((dict(kind="move", fen=after.fen(), flip=b["flip"], hl=[mv.from_square, mv.to_square], red=red,
                                   sub=b.get("text"), card=None if b.get("text") else b.get("label")), hold, c["title"]))
                if clip is not None:
                    events.append((f + 2, clip, 1.0, True))
                f += hold
    total = f
    # chapters: YouTube needs >= 10 s each and the first at 0:00
    merged = []
    for fr, t in chapters:
        if merged and fr - merged[-1][0] < 11 * FPS:
            continue
        merged.append((fr, t if merged else "Intro"))
    if total - merged[-1][0] < 11 * FPS and len(merged) > 1:
        merged.pop()
    # pass 2: audio
    n = int(total / FPS * SR) + SR
    voice_track = np.zeros(n, np.float32); sfx = np.zeros(n, np.float32)
    for fr, a, g, is_voice in events:
        s = int(fr / FPS * SR); a = a[: n - s]
        (voice_track if is_voice else sfx)[s:s + len(a)] += a * g
    bed = music(n) * 0.035
    cd = np.zeros(n, np.float32)
    for (sh, nf, _), fr in zip(shots, np.cumsum([0] + [s[1] for s in shots])[:-1]):
        if sh["kind"] == "countdown":
            cd[int(fr / FPS * SR): int((fr + nf) / FPS * SR)] = 1
    cd = np.convolve(cd, np.ones(SR // 2) / (SR // 2), "same")
    talking = np.convolve((np.abs(voice_track) > 0.02).astype(np.float32), np.ones(SR // 4) / (SR // 4), "same")
    mix = voice_track + sfx * 0.6 + bed * (1 + 1.2 * cd) * (1 - 0.45 * np.clip(talking, 0, 1))
    mix = mix / max(1.0, float(np.max(np.abs(mix))) / 0.95)
    wav = os.path.join(out_dir, "audio.wav"); sf.write(wav, mix, SR)
    # pass 3: frames
    fd = tempfile.mkdtemp(dir=out_dir); lst = []
    fr = 0; last_key = None; last_png = None
    for i, (sh, nf, chap) in enumerate(shots):
        key = json.dumps({k: v for k, v in sh.items() if k not in ("float",)}, default=str) + chap
        if sh.get("float") or key != last_key:
            png = os.path.join(fd, f"{i:06d}.png")
            compose(chap, sh, fr / total).save(png, compress_level=1)
            last_png, last_key = png, key
        lst.append((last_png, nf)); fr += nf
        if i % 200 == 0:
            print(f"render: {i}/{len(shots)} shots", flush=True)
    with open(os.path.join(fd, "list.txt"), "w") as fl:
        for p, nf in lst:
            fl.write(f"file '{p}'\nduration {nf / FPS:.4f}\n")
        fl.write(f"file '{lst[-1][0]}'\n")
    mp4 = os.path.join(out_dir, "video.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", os.path.join(fd, "list.txt"),
                    "-i", wav, "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                    "-tune", "stillimage", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", mp4],
                   check=True)
    subprocess.run(["rm", "-rf", fd])
    # first frame of each critical shot for the reviewer
    stamps = [(fr / FPS, t) for fr, t in merged]
    thumbs = thumbnails(plan, out_dir)
    return {"video": mp4, "duration": total / FPS, "chapters": stamps, "thumbs": thumbs}


# ------------------------------------------------------------------ thumbnails
def thumbnails(plan, out_dir):
    """Main + alternative thumbnail (1280x720). Never shows the answer."""
    th = plan["thumb"]; style = plan["arms"].get("thumb_style", "board_text")
    alt_style = {"board_text": "question", "question": "big_number", "big_number": "board_text"}[style]
    a = os.path.join(out_dir, "thumb_a.jpg"); b = os.path.join(out_dir, "thumb_b.jpg")
    thumb(th, style, th["text"]).save(a, quality=90)
    thumb(th, alt_style, th["alt_text"]).save(b, quality=90)
    return [a, b]


def thumb(th, style, text):
    TW, TH = 1280, 720
    im = Image.new("RGBA", (TW, TH)); bg = background().resize((TW, TH)); im.alpha_composite(bg)
    d = ImageDraw.Draw(im)
    card = R.card(board_layer(th["fen"], th.get("flip"))).resize((640, 640), Image.LANCZOS)
    words = text.upper()
    if style == "big_number":
        num = th.get("number") or (str(th["rating"]) if th.get("rating") else "1 MOVE")
        im.alpha_composite(card.rotate(-6, Image.BICUBIC, expand=True), (640, 30))
        text_block(d, num.split()[0], F_BIG, 260, (30, 40, 640, 330), fill=YELLOW, max_lines=1, stroke=10)
        text_block(d, " ".join(num.split()[1:]) or "", F_BIG, 70, (30, 300, 640, 380), fill=WHITE, max_lines=1, stroke=6)
        text_block(d, words, F_BIG, 90, (30, 390, 640, 610), max_lines=2, stroke=8)
    elif style == "question":
        card = card.resize((540, 540), Image.LANCZOS)
        im.alpha_composite(card, (370, 160))
        text_block(d, words, F_BIG, 110, (20, 14, 1260, 150), fill=WHITE, max_lines=1, stroke=10)
        q = fnt(F_BIG, 420)
        d.text((990, 180), "?", font=q, fill=YELLOW, stroke_width=14, stroke_fill=NAVY)
        m = R.mascot("thinking", 300); im.alpha_composite(m, (20, 420))
    else:                                                   # board_text
        im.alpha_composite(card, (620, 40))
        text_block(d, words, F_BIG, 120, (30, 30, 600, 450), fill=WHITE, max_lines=3, stroke=10)
        if th.get("rating"):
            pill(d, f"RATING {th['rating']}", 40, 470, 40, bg=YELLOW)
        m = R.mascot("thinking", 220); im.alpha_composite(m, (400, 490))
    if style != "question":
        lg = logo(260); im.alpha_composite(lg, (36, TH - lg.height - 22))
    return im.convert("RGB")


def fmt_ts(s):
    s = int(s); return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


if __name__ == "__main__":
    plan = json.load(open(sys.argv[1]))
    print(json.dumps(render(plan, sys.argv[2]), indent=1, default=str))
