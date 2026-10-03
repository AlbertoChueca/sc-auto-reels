"""StreakChess daily reel generator.
Usage: python3 make_reel.py <puzzle_index> <variant_seed> <out.mp4>
Builds a ~25s 1080x1920 puzzle-challenge reel: hook -> puzzle + countdown -> solution -> CTA.
"""
import sys, json, math, random, io, subprocess, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import chess, chess.svg, cairosvg
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
W, H, FPS = 1080, 1920, 30
SR = 24000
FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts", "Poppins-Bold.ttf")
def font(s): return ImageFont.truetype(FONT, s)

ORANGE = (242, 98, 46); YELLOW = (255, 216, 77); PURPLE = (143, 135, 241)
DARK = (34, 30, 36); WHITE = (255, 255, 255)

# ---------------------------------------------------------------- easing
def clamp(x, a=0, b=1): return max(a, min(b, x))
def ease_out_back(t, s=1.7):
    t = clamp(t) - 1; return t * t * ((s + 1) * t + s) + 1
def ease_out(t): t = clamp(t); return 1 - (1 - t) ** 3
def ease_in_out(t): t = clamp(t); return 3 * t * t - 2 * t * t * t

# ---------------------------------------------------------------- assets
MASCOT = {}
def mascot(name, size):
    k = (name, size)
    if k not in MASCOT:
        im = Image.open(f"{HERE}/assets/mascot/{name}.png").convert("RGBA")
        MASCOT[k] = im.resize((size, size), Image.LANCZOS)
    return MASCOT[k]

PIECES = {}
def piece_img(p, sq):
    k = (p.symbol(), sq)
    if k not in PIECES:
        png = cairosvg.svg2png(bytestring=chess.svg.piece(p).encode(), output_width=sq, output_height=sq)
        PIECES[k] = Image.open(io.BytesIO(png)).convert("RGBA")
    return PIECES[k]

# ---------------------------------------------------------------- backgrounds
def bg_orange():
    y, x = np.mgrid[0:H, 0:W]
    d = np.sqrt(((x - W / 2) / W) ** 2 + ((y - H * 0.55) / H) ** 2) / 0.75
    d = np.clip(d, 0, 1)[..., None]
    c1 = np.array([255, 150, 50]); c2 = np.array([120, 30, 8])
    return Image.fromarray((c1 * (1 - d) + c2 * d).astype(np.uint8), "RGB")

def bg_checker(t, a=PURPLE, b=WHITE, s=180):
    off = int(t * 40) % (2 * s)
    big = Image.new("RGB", (W + 2 * s, H + 2 * s), b)
    d = ImageDraw.Draw(big)
    for i in range((W + 2 * s) // s + 1):
        for j in range((H + 2 * s) // s + 1):
            if (i + j) % 2 == 0: d.rectangle([i * s, j * s, i * s + s, j * s + s], fill=a)
    return big.crop((off, off, off + W, off + H))

_CHK = {}
def bg_checker_fast(t, a=(92, 80, 208), b=(112, 100, 228)):
    key = a
    s = 180; off = int(t * 40) % (2 * s)
    # rebuild big tile once
    if (key, "big") not in _CHK:
        big = Image.new("RGB", (W + 2 * s, H + 2 * s), b); d = ImageDraw.Draw(big)
        for i in range((W + 2 * s) // s + 1):
            for j in range((H + 2 * s) // s + 1):
                if (i + j) % 2 == 0: d.rectangle([i * s, j * s, i * s + s, j * s + s], fill=a)
        _CHK[(key, "big")] = big
    return _CHK[(key, "big")].crop((off, off, off + W, off + H))

_STR = {}
def bg_stripes(t):
    s = 150
    if "big" not in _STR:
        big = Image.new("RGB", (W, H + 2 * s), YELLOW); d = ImageDraw.Draw(big)
        for j in range((H + 2 * s) // s + 1):
            if j % 2 == 0: d.rectangle([0, j * s, W, j * s + s], fill=ORANGE)
        _STR["big"] = big
    off = int(t * 60) % (2 * s)
    return _STR["big"].crop((0, off, W, off + H))

GOLD = (232, 192, 96); GOLD2 = (190, 140, 50); NAVY = (20, 17, 40)
def bg_dark():
    y, x = np.mgrid[0:H, 0:W]
    d = np.clip(np.sqrt(((x - W / 2) / W) ** 2 + ((y - H * 0.45) / H) ** 2) / 0.7, 0, 1)[..., None]
    c1 = np.array([70, 56, 150]); c2 = np.array(NAVY)
    return Image.fromarray((c1 * (1 - d) ** 1.5 + c2 * (1 - (1 - d) ** 1.5)).astype(np.uint8), "RGB")

def gold_pill(txt, size, padx=40, pady=16, fg=NAVY):
    t = text_img(txt, size, fg)
    w, h = t.width + 2 * padx, t.height + 2 * pady
    g = np.linspace(0, 1, w)[None, :, None]
    arr = (np.array((250, 220, 140)) * (1 - g) + np.array(GOLD2) * g)
    arr = np.repeat(arr, h, 0).astype(np.uint8)
    im = Image.fromarray(arr, "RGB").convert("RGBA")
    m = Image.new("L", (w, h), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], h // 2, fill=255)
    im.putalpha(m); im.alpha_composite(t, (padx, pady - int(size * 0.08)))
    return im

def outline_pill(txt, size, color=GOLD, fg=WHITE, padx=36, pady=14):
    t = text_img(txt, size, fg)
    w, h = t.width + 2 * padx, t.height + 2 * pady
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([2, 2, w - 3, h - 3], h // 2, fill=(255, 255, 255, 18), outline=color, width=4)
    im.alpha_composite(t, (padx, pady - int(size * 0.08)))
    return im

# ---------------------------------------------------------------- drawing helpers
def text_img(txt, size, fill=WHITE, stroke=0, stroke_fill=DARK, maxw=None):
    f = font(size)
    lines = [txt]
    if maxw:
        words, lines, cur = txt.split(), [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if f.getlength(test) > maxw and cur: lines.append(cur); cur = w
            else: cur = test
        lines.append(cur)
    lh = int(size * 1.18)
    wmax = int(max(f.getlength(l) for l in lines)) + 2 * stroke + 4
    im = Image.new("RGBA", (wmax, lh * len(lines) + 2 * stroke + 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, l in enumerate(lines):
        x = (wmax - f.getlength(l)) / 2
        d.text((x, stroke + i * lh), l, font=f, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
    return im

def pill(txt, size, bg, fg=WHITE, padx=36, pady=16, radius=None):
    t = text_img(txt, size, fg)
    w, h = t.width + 2 * padx, t.height + 2 * pady
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, w - 1, h - 1], radius or h // 2, fill=bg)
    im.alpha_composite(t, (padx, pady - int(size * 0.08)))
    return im

def shadowed(im, blur=18, off=(0, 14), alpha=110):
    pad = blur * 3
    out = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, alpha)); sh.putalpha(im.getchannel("A").point(lambda a: a * alpha // 255))
    out.alpha_composite(sh, (pad + off[0], pad + off[1]))
    out = out.filter(ImageFilter.GaussianBlur(blur))
    out.alpha_composite(im, (pad, pad))
    return out, pad

def paste_center(canvas, im, cx, cy, scale=1.0, alpha=1.0, rot=0):
    if scale <= 0.01 or alpha <= 0.01: return
    if scale != 1: im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BILINEAR)
    if rot: im = im.rotate(rot, Image.BICUBIC, expand=True)
    if alpha < 1:
        im = im.copy(); im.putalpha(im.getchannel("A").point(lambda a: int(a * alpha)))
    canvas.alpha_composite(im, (int(cx - im.width / 2), int(cy - im.height / 2)))

def caption(canvas, txt, y=300):
    if not txt: return
    t = text_img(txt, 50, WHITE, maxw=900)
    box = Image.new("RGBA", (t.width + 50, t.height + 26), (0, 0, 0, 0))
    ImageDraw.Draw(box).rounded_rectangle([0, 0, box.width - 1, box.height - 1], 22, fill=(14, 12, 28, 225), outline=(232, 192, 96, 160), width=2)
    box.alpha_composite(t, (25, 10))
    paste_center(canvas, box, W / 2, y)

# ---------------------------------------------------------------- board
SQ = 118; BOARD = SQ * 8
LIGHT = (246, 244, 255); DARKSQ = PURPLE

def sq_xy(sq, flip):
    f, r = chess.square_file(sq), chess.square_rank(sq)
    return ((7 - f) * SQ, r * SQ) if flip else (f * SQ, (7 - r) * SQ)

def draw_board(board, flip, highlights=(), red=None, hide=None):
    im = Image.new("RGBA", (BOARD, BOARD))
    d = ImageDraw.Draw(im)
    for s in chess.SQUARES:
        x, y = sq_xy(s, flip)
        light = (chess.square_file(s) + chess.square_rank(s)) % 2 == 1
        d.rectangle([x, y, x + SQ, y + SQ], fill=LIGHT if light else DARKSQ)
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
    for s in highlights:
        x, y = sq_xy(s, flip); od.rectangle([x, y, x + SQ, y + SQ], fill=(255, 196, 40, 130))
    if red is not None:
        x, y = sq_xy(red, flip); od.rectangle([x, y, x + SQ, y + SQ], fill=(235, 40, 40, 170))
    im.alpha_composite(ov)
    fl = font(22)
    for i in range(8):
        # file letters bottom row, rank numbers left col
        fx = i; file_char = "abcdefgh"[7 - i if flip else i]
        rank_char = str(i + 1 if flip else 8 - i)
        d.text((i * SQ + SQ - 20, BOARD - 30), file_char, font=fl, fill=(90, 80, 150))
        d.text((6, i * SQ + 4), rank_char, font=fl, fill=(90, 80, 150))
    for s, p in board.piece_map().items():
        if s == hide: continue
        x, y = sq_xy(s, flip)
        im.alpha_composite(piece_img(p, SQ), (x, y))
    return im

def draw_arrow(im, frm, to, flip, color=(242, 98, 46, 220)):
    x1, y1 = sq_xy(frm, flip); x2, y2 = sq_xy(to, flip)
    x1 += SQ / 2; y1 += SQ / 2; x2 += SQ / 2; y2 += SQ / 2
    ang = math.atan2(y2 - y1, x2 - x1); L = math.hypot(x2 - x1, y2 - y1)
    w, hw, hl = 22, 48, 56
    pts = [(0, -w / 2), (L - hl, -w / 2), (L - hl, -hw / 2), (L, 0), (L - hl, hw / 2), (L - hl, w / 2), (0, w / 2)]
    ca, sa = math.cos(ang), math.sin(ang)
    pts = [(x1 + px * ca - py * sa, y1 + px * sa + py * ca) for px, py in pts]
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); ImageDraw.Draw(ov).polygon(pts, fill=color)
    im.alpha_composite(ov)

def card(board_img):
    pad = 22
    c = Image.new("RGBA", (BOARD + 2 * pad, BOARD + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(c).rounded_rectangle([0, 0, c.width - 1, c.height - 1], 34, fill=WHITE)
    mask = Image.new("L", board_img.size, 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, BOARD - 1, BOARD - 1], 18, fill=255)
    c.paste(board_img, (pad, pad), mask)
    return c

# ---------------------------------------------------------------- speech
PNAME = {"K": "King", "Q": "Queen", "R": "Rook", "B": "Bishop", "N": "Knight"}
NUM = ["", "one", "two", "three", "four", "five", "six", "seven", "eight"]
def sq_say(s): return f"{s[0].upper()} {NUM[int(s[1])]}"
def san_say(san):
    mate, check = san.endswith("#"), san.endswith("+")
    s = san.rstrip("+#")
    if s.startswith("O-O-O"): out = "castles long"
    elif s.startswith("O-O"): out = "castles"
    else:
        promo = None
        if "=" in s: s, promo = s.split("=")
        piece = PNAME.get(s[0], None)
        dest = s[-2:]
        if piece: out = f"{piece} {'takes ' if 'x' in s else 'to '}{sq_say(dest)}"
        else: out = f"{s[0].upper()} takes {sq_say(dest)}" if "x" in s else f"pawn to {sq_say(dest)}"
        if promo: out += f", promoting to a {PNAME[promo].lower()}"
    if mate: out += ". Checkmate!"
    elif check: out += ", check!"
    return out

_K = None
def tts(text, voice="am_michael", speed=1.08):
    global _K
    if _K is None:
        from kokoro_onnx import Kokoro
        _K = Kokoro(f"{HERE}/models/kokoro.onnx", f"{HERE}/models/voices.bin")
    s, sr = _K.create(text, voice=voice, speed=speed, lang="en-us")
    assert sr == SR
    return np.asarray(s, dtype=np.float32)

# ---------------------------------------------------------------- sfx
def tone(freq, dur, decay=18, vol=0.35):
    t = np.arange(int(SR * dur)) / SR
    return (np.sin(2 * np.pi * freq * t) * np.exp(-decay * t) * vol).astype(np.float32)
def tick(high=False): return tone(1900 if high else 1400, 0.06, 60, 0.35 if high else 0.25)
def whoosh(dur=0.4):
    n = int(SR * dur); noise = np.random.randn(n).astype(np.float32)
    k = np.ones(30) / 30; noise = np.convolve(noise, k, "same")
    env = np.sin(np.linspace(0, np.pi, n)) ** 2
    return noise * env * 0.5
def ding(): return tone(880, 1.0, 4, 0.3) + tone(1320, 1.0, 5, 0.18)
def pop():
    t = np.arange(int(SR * 0.09)) / SR
    return (np.sin(2 * np.pi * (300 + 2500 * t) * t) * np.exp(-30 * t) * 0.4).astype(np.float32)

# ---------------------------------------------------------------- variants
LEVELS = {
    "basic": dict(name="BEGINNER", rng="800-1200", count=8, color=(70, 190, 130), hooks=[
        ("EASY... OR IS IT?", "This one looks easy. But most beginners miss it.", "thinking"),
        ("BEGINNER TEST", "Beginner test. If you're under twelve hundred, this one is for you.", "happy"),
        ("DON'T BLUNDER THIS", "Don't blunder this one. Beginners, can you find it?", "angry")]),
    "intermediate": dict(name="INTERMEDIATE", rng="1200-1900", count=10, color=(90, 160, 255), hooks=[
        ("CLUB PLAYER TEST", "Club players, this one's for you. Can you find the win?", "angry"),
        ("ONLY 3% SEE IT", "Only three percent of club players find this. Are you one of them?", "thinking"),
        ("1500+ ONLY", "If you're rated under fifteen hundred, you won't see this. Prove me wrong.", "crown2")]),
    "advanced": dict(name="ADVANCED", rng="1900-2500", count=12, color=(235, 80, 90), hooks=[
        ("MASTER LEVEL", "Master level puzzle. Only strong players find this.", "crown3"),
        ("GRANDMASTER MOVE", "Grandmasters see this in seconds. Do you?", "angry"),
        ("2000+ ONLY", "This is a two thousand plus puzzle. Think you can crack it?", "thinking")]),
}

def logo_glow(path, width, glow=60):
    im = Image.open(f"{HERE}/assets/{path}").convert("RGBA")
    im = im.resize((width, int(im.height * width / im.width)), Image.LANCZOS)
    pad = glow
    out = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    a = im.getchannel("A").point(lambda v: 90 if v > 0 else 0)
    g = Image.new("RGBA", im.size, (255, 255, 255, 0)); g.putalpha(a)
    out.alpha_composite(g, (pad, pad)); out = out.filter(ImageFilter.GaussianBlur(glow / 2.5))
    out.alpha_composite(im, (pad, pad))
    return out

CHESS_TAGS = ["chess", "chesspuzzle", "chesstactics", "chesstraining", "chessplayer", "chesslover",
              "chesscommunity", "chessgame", "chessmaster", "chesspuzzles", "chessclub", "checkmate",
              "chesslife", "chessstrategy", "chesskids", "learnchess", "chessmoves", "chessbrain",
              "chessforkids", "kidschess", "scholasticchess", "chesskid", "chessforbeginners"]
US_STATES = ["Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware",
             "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
             "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi",
             "Missouri", "Montana", "Nebraska", "Nevada", "NewHampshire", "NewJersey", "NewMexico", "NewYork",
             "NorthCarolina", "NorthDakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "RhodeIsland",
             "SouthCarolina", "SouthDakota", "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
             "WestVirginia", "Wisconsin", "Wyoming"]

def hashtags(rng):
    """3-5 random English chess hashtags (the US location is set as the post location)."""
    tags = rng.sample(CHESS_TAGS, rng.randint(3, 5))
    return ["#" + t for t in tags]

TAG_HOOKS = [
    ("TAG A FRIEND", "Tag a friend who thinks they're good at chess. Let's see who solves this first.", "angry"),
    ("FRIEND CHALLENGE", "Challenge time. Send this to a friend and see who finds the move first.", "thinking"),
    ("SEND THIS TO A FRIEND", "Send this to the friend who always beats you. Can they solve it?", "crown2"),
    ("WHO'S SMARTER?", "You or your chess friend? Tag them and find out.", "happy"),
]
TAG_CAPTIONS = [
    "Challenge a friend to solve this 👇",
    "Tag the friend who always beats you at chess 👇",
    "Send this to a friend and see who solves it first ⏱️",
    "Tag a friend who loves chess puzzles 👇",
    "Who finds it first, you or your friend? Tag them 👇",
]

def build(P, seed, out, mode="level"):
    """P: dict with level + either (fen, moves) in Lichess-CSV format or (pgn, sol) in Lichess-API format."""
    random.seed(seed); np.random.seed(seed)
    LV = LEVELS[P["level"]]
    if "fen" in P:
        board = chess.Board(P["fen"]); ms = P["moves"].split()
        board.push(chess.Move.from_uci(ms[0])); P = dict(P, sol=ms[1:])
    else:
        board = chess.Board()
        for m in P["pgn"].split(): board.push_san(m)
    last = board.peek()
    flip = board.turn == chess.BLACK
    side = "BLACK" if flip else "WHITE"
    moves = [chess.Move.from_uci(u) for u in P["sol"]]
    b2 = board.copy(); sans = []
    for m in moves: sans.append(b2.san(m)); b2.push(m)
    mate_n = (len(moves) + 1) // 2 if b2.is_checkmate() else None
    goal = f"MATE IN {mate_n}" if mate_n else "FIND THE BEST MOVE"

    tag = mode == "tagfriend"
    hook_txt, hook_vo, pose = (TAG_HOOKS if tag else LV["hooks"])[seed % len(TAG_HOOKS if tag else LV["hooks"])]
    COUNT = LV["count"]
    goal_say = f"mate in {NUM[mate_n]}" if mate_n else "the best move"
    NUMW = {10: "ten", 12: "twelve"}
    segs = {
        "hook": hook_vo,
        "intro": f"{side.title()} to move. Find {goal_say}. You've got {NUM[COUNT] if COUNT < 9 else NUMW[COUNT]} seconds.",
        "reveal": "Here's the answer. " + " ".join(san_say(s) + ("" if san_say(s).endswith("!") else ".") for s in sans),
        "cta": ("Did you get it? Now tag a friend and see if they can. StreakChess is free to play. And the first five hundred accounts get a special Founder offer for Premium. Link in bio." if tag else
                "Did you get it? Comment your time. StreakChess is free to play. And the first five hundred accounts get a special Founder offer for Premium. Link in bio."),
    }
    audio = {k: tts(v) for k, v in segs.items()}
    dur = {k: len(a) / SR for k, a in audio.items()}

    # timeline (seconds)
    T = {}
    t = 0.0
    T["hook"] = (t, t + dur["hook"] + 0.35); t = T["hook"][1]
    T["intro"] = (t, t + dur["intro"] + 0.25); t = T["intro"][1]
    T["count"] = (t, t + COUNT); t = T["count"][1]
    T["reveal"] = (t, t + dur["reveal"] + 0.8); t = T["reveal"][1]
    T["cta"] = (t, t + dur["cta"] + 0.8); total = T["cta"][1]

    # ---- audio mix
    mix = np.zeros(int(SR * (total + 0.2)), np.float32)
    def put(a, at, gain=1.0):
        i = int(at * SR); j = min(len(mix), i + len(a)); mix[i:j] += a[: j - i] * gain
    put(audio["hook"], T["hook"][0] + 0.2)
    put(audio["intro"], T["intro"][0] + 0.1)
    put(audio["reveal"], T["reveal"][0] + 0.15)
    put(audio["cta"], T["cta"][0] + 0.2)
    put(pop(), 0.05); put(whoosh(), T["intro"][0] - 0.2); put(whoosh(), T["cta"][0] - 0.2)
    for i in range(COUNT): put(tick(i >= COUNT - 3), T["count"][0] + i)
    put(ding(), T["reveal"][0])
    # reveal move timing: spread across reveal VO
    rv0 = T["reveal"][0] + 0.15 + 0.9; rv1 = T["reveal"][0] + 0.15 + dur["reveal"] - 0.4
    mstep = (rv1 - rv0) / len(moves)
    move_t = [rv0 + i * mstep for i in range(len(moves))]
    for mt in move_t: put(tone(520, 0.08, 40, 0.3), mt + 0.35)
    mate_t = move_t[-1] + 0.45
    if mate_n: put(ding(), mate_t, 0.8)
    n = len(mix); tt = np.arange(n) / SR
    chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (196.0, 246.94, 293.66), (164.81, 207.65, 246.94)]
    pad = np.zeros(n, np.float32); L = 2.4
    for ci in range(int(total / L) + 1):
        a, b = int(ci * L * SR), min(n, int((ci + 1) * L * SR) + SR // 2)
        if a >= n: break
        seg = tt[a:b] - ci * L; env = np.clip(seg / 0.5, 0, 1) * np.clip((L + 0.5 - seg) / 0.6, 0, 1)
        for f in chords[ci % 4]:
            pad[a:b] += (np.sin(2 * np.pi * f * tt[a:b]) + 0.5 * np.sin(2 * np.pi * f * 1.003 * tt[a:b]) + 0.2 * np.sin(2 * np.pi * f * 2 * tt[a:b])) * env
    pad /= np.abs(pad).max() + 1e-9
    vo = np.abs(mix) > 0.02
    mix += pad * 0.06
    peak = np.abs(mix).max(); mix = mix / peak * 0.95 if peak > 0 else mix
    wav = out.replace(".mp4", ".wav"); sf.write(wav, mix, SR)

    # ---- captions per segment
    def cap_at(t):
        for k, key in (("hook", "hook"), ("intro", "intro"), ("reveal", "reveal"), ("cta", "cta")):
            a, b = T[k]
            if a <= t < b: return segs[key]
        return ""
    # captions split into chunks for readability
    import re
    def chunks(text, n=8):
        for a_, b_ in (("fourteen hundred", "1400"), ("fifteen hundred", "1500"), ("twelve hundred", "1200"), ("two thousand plus", "2000+"), ("ten seconds", "10 seconds"), ("twelve seconds", "12 seconds"), ("three percent", "3%"), ("five hundred", "500"), ("eight seconds", "8 seconds"), ("mate in two", "mate in 2"), ("mate in three", "mate in 3")):
            text = text.replace(a_, b_)
        out = []
        for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
            w = sent.split()
            if len(w) <= n: out.append(sent)
            else:
                h = (len(w) + 1) // 2; out += [" ".join(w[:h]), " ".join(w[h:])]
        return out
    # solution in algebraic notation, renumbered from move 1
    nb = board.copy(); nb.fullmove_number = 1
    san_line = []
    tmp = nb.copy()
    for i, m in enumerate(moves):
        num = ""
        if tmp.turn == chess.WHITE: num = f"{tmp.fullmove_number}. "
        elif i == 0: num = f"{tmp.fullmove_number}... "
        san_line.append(num + tmp.san(m)); tmp.push(m)
    def cap_text(t):
        if T["reveal"][0] <= t < T["reveal"][1]:
            if t < move_t[0]: return "Solution:"
            k = min(len(moves), int((t - move_t[0]) / mstep) + 1)
            return "  ".join(san_line[:k])
        if T["count"][0] <= t < T["count"][1]:
            return "Pause if you need more time" if t < T["count"][0] + COUNT / 2 else ("Tag a friend before the answer!" if tag else "Comment your move before the answer!")
        if T["cta"][0] <= t: return ""
        for k in ("hook", "intro"):
            a, b = T[k]
            if a <= t < b:
                cs = chunks(segs[k]); spoken = dur[k]
                w = np.cumsum([len(c) for c in cs]) / sum(len(c) for c in cs)
                p = clamp((t - a) / max(spoken, 0.1), 0, 0.999)
                txt = cs[int(np.searchsorted(w, p, side="right").clip(0, len(cs) - 1))]
                for a_, b_ in (("fourteen hundred", "1400"), ("fifteen hundred", "1500"), ("twelve hundred", "1200"), ("two thousand plus", "2000+"), ("ten seconds", "10 seconds"), ("twelve seconds", "12 seconds"), ("three percent", "3%"), ("five hundred", "500"), ("eight seconds", "8 seconds"), ("mate in two", "mate in 2"), ("mate in three", "mate in 3")):
                    txt = txt.replace(a_, b_)
                return txt
        return ""

    # ---- static layers
    bgO = bg_dark().convert("RGBA")
    lvl_chip = Image.new("RGBA", (10, 10))
    _t1 = text_img(f"{LV['name']}", 40, NAVY); _t2 = text_img(f"{LV['rng']}", 40, WHITE)
    lvl_chip = Image.new("RGBA", (_t1.width + _t2.width + 110, max(_t1.height, _t2.height) + 28), (0, 0, 0, 0))
    _d = ImageDraw.Draw(lvl_chip); _h = lvl_chip.height
    _d.rounded_rectangle([0, 0, lvl_chip.width - 1, _h - 1], _h // 2, fill=(14, 12, 28, 235), outline=LV["color"], width=4)
    _d.rounded_rectangle([4, 4, _t1.width + 50, _h - 5], (_h - 8) // 2, fill=LV["color"])
    lvl_chip.alpha_composite(_t1, (27, 10)); lvl_chip.alpha_composite(_t2, (_t1.width + 75, 10))
    logo_top = logo_glow("logo_h_white.png", 400, 30)
    logo_big = logo_glow("logo_v_white.png", 520, 70)
    band = gold_pill(hook_txt, 104, padx=60, pady=22).rotate(-3, Image.BICUBIC, expand=True)
    if band.width > 1020:
        band = band.resize((1020, int(band.height * 1020 / band.width)), Image.LANCZOS)
    hook_m = mascot(pose, 820)
    chip_side = pill(f"{side} TO MOVE", 32, WHITE, fg=NAVY)
    chip_goal = gold_pill(goal, 32, padx=30)
    chip_lvl = pill(LV["name"], 32, LV["color"], fg=NAVY)
    think_m = mascot("thinking", 230)
    celeb_m = mascot("celebrate", 270)
    hook_m_small = mascot(pose, 560)
    url_pill = gold_pill("streakchess.com", 66, padx=56, pady=24)
    cta_top = text_img("TAG A FRIEND!" if tag else "DID YOU GET IT?", 100, WHITE)
    free_pill = outline_pill("100% FREE TO PLAY", 46, color=(120, 220, 160))
    founder = Image.new("RGBA", (900, 250), (0, 0, 0, 0)); fd = ImageDraw.Draw(founder)
    fd.rounded_rectangle([2, 2, 897, 247], 40, fill=(34, 28, 66, 255), outline=GOLD, width=4)
    fb = gold_pill("FOUNDER OFFER", 38, padx=30, pady=10); founder.alpha_composite(fb, ((900 - fb.width) // 2, 30))
    ft = text_img("Premium for the first 500 accounts", 48, WHITE); founder.alpha_composite(ft, ((900 - ft.width) // 2, 118))
    fs = text_img("Limited founder spots", 34, (200, 190, 240)); founder.alpha_composite(fs, ((900 - fs.width) // 2, 182))
    cta_sub = text_img("Train your calculation daily", 50, DARK)
    mate_stamp = (pill("CHECKMATE!", 84, (220, 40, 40), padx=44, pady=18) if mate_n else gold_pill("WINNING!", 84, padx=44, pady=18)).rotate(8, Image.BICUBIC, expand=True)

    # board states for reveal
    states = [board.copy()]
    for m in moves: s = states[-1].copy(); s.push(m); states.append(s)
    base_cache = {}
    def board_frame(t):
        if t < move_t[0]:
            return draw_board(board, flip, (last.from_square, last.to_square))
        i = min(len(moves) - 1, int((t - move_t[0]) / mstep))
        mt = move_t[i]; m = moves[i]; prog = ease_in_out((t - mt) / 0.45)
        key = (i, prog >= 1)
        red = None
        if prog >= 1:
            st = states[i + 1]
            if i == len(moves) - 1 and mate_n: red = st.king(st.turn)
            if (i, "done", red) not in base_cache:
                im = draw_board(st, flip, (m.from_square, m.to_square), red=red)
                base_cache[(i, "done", red)] = im
            im = base_cache[(i, "done", red)].copy()
            if i % 2 == 0 or True: draw_arrow(im, m.from_square, m.to_square, flip, (242, 98, 46, 150) if i % 2 == 0 else (80, 80, 90, 110))
            return im
        st = states[i]
        if (i, "moving") not in base_cache:
            b_hide = st.copy()
            base_cache[(i, "moving")] = draw_board(b_hide, flip, (m.from_square,), hide=m.from_square)
        im = base_cache[(i, "moving")].copy()
        # captured piece stays until moving piece arrives (fine)
        x1, y1 = sq_xy(m.from_square, flip); x2, y2 = sq_xy(m.to_square, flip)
        p = st.piece_at(m.from_square)
        x = x1 + (x2 - x1) * prog; y = y1 + (y2 - y1) * prog
        if prog > 0.5 and st.piece_at(m.to_square):  # hide captured
            tx, ty = sq_xy(m.to_square, flip)
            light = (chess.square_file(m.to_square) + chess.square_rank(m.to_square)) % 2 == 1
            ImageDraw.Draw(im).rectangle([tx, ty, tx + SQ, ty + SQ], fill=LIGHT if light else DARKSQ)
        im.alpha_composite(piece_img(p, SQ), (int(x), int(y)))
        return im

    puzzle_board_static = card(draw_board(board, flip, (last.from_square, last.to_square)))
    pb_sh, pb_pad = shadowed(puzzle_board_static)
    pb_blur = pb_sh.filter(ImageFilter.GaussianBlur(22))
    _dk = Image.new("RGBA", pb_blur.size, (14, 12, 28, 90)); _dk.putalpha(pb_blur.getchannel("A").point(lambda v: v * 90 // 255))
    pb_blur.alpha_composite(_dk)
    qmark = text_img("?", 300, (250, 220, 140))

    # confetti
    conf = [dict(x=random.uniform(0, W), y=random.uniform(-400, 0), vx=random.uniform(-120, 120), vy=random.uniform(200, 600),
                 c=random.choice([GOLD, (250, 225, 150), PURPLE, WHITE, GOLD2]), r=random.uniform(0, 360), s=random.randint(14, 26)) for _ in range(90)]

    BOARD_CY = 1130
    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                             "-i", wav, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                             "-shortest", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    nframes = int(total * FPS)
    for fi in range(nframes):
        t = fi / FPS
        if t < T["hook"][1]:
            lt = t - T["hook"][0]
            fr = bgO.copy()
            paste_center(fr, pb_blur, W / 2, BOARD_CY, 1.0 + 0.03 * lt)
            paste_center(fr, qmark, W / 2, BOARD_CY - 120, ease_out_back((lt - 0.2) / 0.5) * (1 + 0.04 * math.sin(lt * 5)), 0.9)
            paste_center(fr, lvl_chip, W / 2, 420, ease_out_back(lt / 0.4))
            bs = 1.5 - 0.5 * ease_out(lt / 0.35)
            paste_center(fr, band, W / 2, 570, bs, clamp(lt / 0.2))
            paste_center(fr, hook_m_small, W / 2 + 180, 1560 + 10 * math.sin(lt * 3), ease_out_back((lt - 0.15) / 0.5))
            caption(fr, cap_text(t), 250)
            paste_center(fr, logo_top, W / 2, 110)
        elif t < T["count"][1] or t < T["reveal"][1]:
            lt = t - T["intro"][0]
            fr = bg_checker_fast(t, (30, 26, 62), (22, 19, 46)).convert("RGBA")
            # board card slide-in
            if t < T["reveal"][0]:
                paste_center(fr, pb_sh, W / 2, BOARD_CY)
                if lt < 0.5: paste_center(fr, pb_blur, W / 2, BOARD_CY, 1.0, 1 - ease_out(lt / 0.5))
            else:
                c, pad = shadowed(card(board_frame(t)))
                paste_center(fr, c, W / 2, BOARD_CY)
            # chips
            ca = clamp((lt - 0.3) / 0.3)
            gap = 16; tw = chip_lvl.width + chip_side.width + chip_goal.width + 2 * gap; x0 = (W - tw) / 2
            paste_center(fr, chip_lvl, x0 + chip_lvl.width / 2, 570, ease_out_back((lt - 0.25) / 0.4), ca)
            paste_center(fr, chip_side, x0 + chip_lvl.width + gap + chip_side.width / 2, 570, ease_out_back((lt - 0.3) / 0.4), ca)
            paste_center(fr, chip_goal, x0 + chip_lvl.width + chip_side.width + 2 * gap + chip_goal.width / 2, 570, ease_out_back((lt - 0.4) / 0.4), ca)
            # timer
            if t < T["reveal"][0]:
                if t < T["count"][0]: remain = COUNT
                else: remain = COUNT - int(t - T["count"][0])
                ph = (t - T["count"][0]) % 1 if t >= T["count"][0] else 1
                urgent = t >= T["count"][0] and remain <= 3
                box = Image.new("RGBA", (400, 150), (0, 0, 0, 0)); bd = ImageDraw.Draw(box)
                bd.rounded_rectangle([0, 0, 399, 149], 36, fill=(230, 50, 60) if urgent else GOLD)
                bd.rounded_rectangle([12, 12, 387, 137], 26, fill=NAVY)
                tt = text_img(f"00:{remain:02d}", 92, (255, 90, 90) if urgent else (250, 220, 140))
                box.alpha_composite(tt, ((400 - tt.width) // 2, 14))
                pulse = 1 + (0.12 if urgent else 0.06) * max(0, 1 - ph * 4)
                paste_center(fr, box, W / 2, 400, ease_out_back(lt / 0.5) * pulse)
                # peeking thinking mascot
                paste_center(fr, think_m, 900, 380 + 8 * math.sin(t * 4), ease_out_back((lt - 0.6) / 0.5), 1, -6)
            else:
                rt = t - T["reveal"][0]
                ans = gold_pill("SOLUTION", 66, padx=50, pady=20)
                paste_center(fr, ans, W / 2, 400, ease_out_back(rt / 0.4))
                if t >= mate_t:
                    mt = t - mate_t
                    paste_center(fr, mate_stamp, W / 2, BOARD_CY, 1.8 - 0.8 * ease_out(mt / 0.25), clamp(mt / 0.15))
                    paste_center(fr, celeb_m, 900, 380, ease_out_back(mt / 0.5))
                    d = ImageDraw.Draw(fr)
                    for p in conf:
                        x = p["x"] + p["vx"] * mt; y = p["y"] + p["vy"] * mt + 300 * mt * mt
                        if -50 < y < H: d.rectangle([x, y, x + p["s"], y + p["s"] * 0.5], fill=p["c"])
            caption(fr, cap_text(t), 250)
            paste_center(fr, logo_top, W / 2, 110)
        else:
            lt = t - T["cta"][0]
            fr = Image.new("RGBA", (W, H), NAVY + (255,))
            paste_center(fr, cta_top, W / 2, 300, ease_out_back(lt / 0.4))
            paste_center(fr, logo_big, W / 2, 680 + 8 * math.sin(lt * 3), ease_out_back((lt - 0.15) / 0.5))
            paste_center(fr, free_pill, W / 2, 1040, ease_out_back((lt - 1.2) / 0.4))
            paste_center(fr, founder, W / 2, 1250, ease_out_back((lt - 2.6) / 0.45))
            paste_center(fr, url_pill, W / 2, 1480, ease_out_back((lt - 3.2) / 0.4) * (1 + 0.03 * math.sin(lt * 6)))
        proc.stdin.write(fr.convert("RGB").tobytes())
    proc.stdin.close(); proc.wait()
    os.remove(wav)
    rng = random.Random(f"{P['id']}-{seed}-{mode}")
    first = rng.choice(TAG_CAPTIONS) if tag else hook_txt
    ig = (f"{first}\n{LV['name'].title()} puzzle ({LV['rng']}). {side.title()} to move, {goal_say}.\n\n"
          + ("Comment the move and tag a friend to challenge them!\n\n" if tag else "Comment your move before watching the solution!\n\n")
          + "Train your calculation every day on StreakChess. Free to play. Founder offer for the first 500 accounts, link in bio.\n\n"
          + " ".join(hashtags(rng)))
    open(out.replace(".mp4", ".txt"), "w").write(ig)
    meta = dict(mode=mode, puzzle=P["id"], level=P["level"], rating=P.get("rating"), hook=hook_txt, sans=sans, duration=round(total, 1), script=segs)
    print(json.dumps(meta, indent=1))
    return meta

if __name__ == "__main__":
    # python make_reel.py puzzle.json seed out.mp4
    build(json.load(open(sys.argv[1])), int(sys.argv[2]), sys.argv[3])
