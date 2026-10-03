"""Cinematic 'hype' puzzle reel in the StreakChess trailer style:
dark spotlight stage, angry/animated knight, slam typography, fire wipes, sunburst
backgrounds, camera punch-ins and shake, impact sound design and a driving beat.

python make_hype.py puzzle.json seed out.mp4 [level|tagfriend]
"""
import json, math, os, random, re, subprocess, sys
import numpy as np
import chess
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import soundfile as sf
import make_reel as R
from mascot_rig import Mascot

HERE = os.path.dirname(os.path.abspath(__file__))
W, H, FPS, SR = 1080, 1920, 30, 24000
F900 = os.path.join(HERE, "fonts", "Nunito-900.ttf")
if not os.path.exists(F900):   # fallback so a missing font never breaks a run
    F900 = next((p for p in (os.path.join(HERE, "Nunito-900.ttf"), os.path.join(HERE, "fonts", "Poppins-Bold.ttf"),
                             os.path.join(HERE, "Poppins-Bold.ttf")) if os.path.exists(p)), F900)
YEL, ORA, RED, WHITE, INK = (255, 214, 64), (242, 98, 46), (255, 70, 70), (255, 255, 255), (20, 16, 28)
VOICE = os.environ.get("HYPE_VOICE", "am_fenrir")
clamp, eob, eo, eio = R.clamp, R.ease_out_back, R.ease_out, R.ease_in_out


# ----------------------------------------------------------------- typography
def word_img(word, size, color=WHITE, stroke=10):
    fo = ImageFont.truetype(F900, size)
    w = int(fo.getlength(word)) + 2 * stroke + 20
    im = Image.new("RGBA", (w, int(size * 1.35) + 2 * stroke), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.text((stroke + 10 + 6, stroke + 8), word, font=fo, fill=(0, 0, 0, 160))          # drop shadow
    d.text((stroke + 10, stroke), word, font=fo, fill=color, stroke_width=stroke, stroke_fill=INK)
    return im


HOT = re.compile(r"^(mate|checkmate|genius|prove|seconds?|free|master|beginner|advanced|intermediate|club|check|"
                 r"friend|3%|\d+|win|sacrifice|fork|trapped|king|streakchess)", re.I)


def phrase_img(words, newest_t, size=96, maxw=980):
    """Lay out up to ~3 words; the newest word pops."""
    ims = [word_img(w.upper(), size, YEL if HOT.match(w.strip(".,!?")) else WHITE) for w in words]
    lines, cur, cw = [], [], 0
    for im in ims:
        if cur and cw + im.width > maxw:
            lines.append(cur); cur, cw = [], 0
        cur.append(im); cw += im.width + 18
    lines.append(cur)
    lh = max(i.height for i in ims) - 22
    out = Image.new("RGBA", (maxw + 80, lh * len(lines) + 40), (0, 0, 0, 0))
    k = 0
    for li, line in enumerate(lines):
        tw = sum(i.width + 18 for i in line); x = (out.width - tw) / 2
        for im in line:
            is_new = k == len(ims) - 1
            s = (1.18 - 0.18 * eob(newest_t / 0.18)) if is_new else 1.0
            im2 = im if s == 1 else im.resize((int(im.width * s), int(im.height * s)), Image.BILINEAR)
            out.alpha_composite(im2, (int(x + (im.width - im2.width) / 2), int(li * lh + (im.height - im2.height) / 2) + 10))
            x += im.width + 18; k += 1
    return out


_GRAIN = [np.random.RandomState(k).normal(0, 5.5, (H // 2, W // 2, 1)).astype(np.int16) for k in range(4)]


def grain(fr, fi):
    """Subtle film grain -> raw RGB bytes."""
    a = np.asarray(fr.convert("RGB"), dtype=np.int16)
    g = np.repeat(np.repeat(_GRAIN[fi % 4], 2, 0), 2, 1)
    return np.clip(a + g, 0, 255).astype(np.uint8).tobytes()


# ----------------------------------------------------------------- backgrounds
class BG:
    def __init__(self):
        y, x = np.mgrid[0:H, 0:W].astype(np.float32)
        self.ang = np.arctan2(y - H * 0.42, x - W / 2)
        self.rad = np.sqrt((x - W / 2) ** 2 + (y - H * 0.42) ** 2) / (H * 0.7)
        # dark stage with spotlight cone from top-right
        base = np.zeros((H, W, 3), np.float32)
        base[:] = np.array([12, 11, 18])
        cone = Image.new("L", (W, H), 0); cd = ImageDraw.Draw(cone)
        cd.polygon([(W * 0.62, -50), (W * 1.05, -50), (W * 0.95, H * 0.95), (W * 0.05, H * 0.95)], fill=70)
        cone = np.array(cone.filter(ImageFilter.GaussianBlur(60)), np.float32)[..., None] / 255
        floor = np.clip((y - H * 0.78) / (H * 0.22), 0, 1)[..., None]
        stage = base + cone * np.array([255, 230, 160]) * 0.55 + floor * np.array([40, 34, 52])
        vig = np.clip(1 - self.rad[..., None] * 0.55, 0.35, 1)
        self.stage = Image.fromarray(np.clip(stage * vig, 0, 255).astype(np.uint8)).convert("RGBA")
        rng = np.random.RandomState(3)
        self.dust = [(rng.uniform(W * 0.2, W), rng.uniform(0, H), rng.uniform(2, 5), rng.uniform(8, 30)) for _ in range(70)]
        # fire noise
        def layer(gw, gh, blur):
            g = (rng.rand(gh, gw) * 255).astype(np.uint8)
            im = Image.fromarray(g).resize((W // 2, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(blur))
            return np.array(im, np.float32) / 255
        nz = 0.55 * layer(9, 14, 18) + 0.3 * layer(20, 40, 8) + 0.15 * layer(45, 90, 3)
        nz = (nz - nz.min()) / (nz.max() - nz.min())
        self.noise = np.vstack([nz, nz[::-1]])
        x = np.linspace(0, 1, 256)
        self.lut = np.stack([np.clip(x * 3.0, 0, 1) * 255, np.clip(x * 2.2 - 0.55, 0, 1) * 225,
                             np.clip(x * 3 - 2.2, 0, 1) * 190, np.clip(x * 4, 0, 1) * 255], -1).astype(np.uint8)

    def stage_frame(self, t):
        im = self.stage.copy(); d = ImageDraw.Draw(im)
        for x, y, r, sp in self.dust:
            yy = (y - t * sp) % H; xx = x + 12 * math.sin(t * 0.7 + y)
            d.ellipse([xx - r, yy - r, xx + r, yy + r], fill=(255, 235, 180, 60))
        return im

    def burst(self, t, c1, c2, rays=18):
        a = (self.ang + t * 0.35) % (2 * math.pi / rays) < (math.pi / rays)
        col = np.where(a[..., None], np.array(c1, np.float32), np.array(c2, np.float32))
        glow = np.clip(1.25 - self.rad[..., None], 0.45, 1.25)
        return Image.fromarray(np.clip(col * glow, 0, 255).astype(np.uint8)).convert("RGBA")

    def fire(self, p):
        """Full-screen fire wipe; p 0..1 (rises from bottom, covers, exits top)."""
        off = int(p * H * 0.8) % H
        nz = self.noise[off:off + H]
        nz = np.array(Image.fromarray((nz * 255).astype(np.uint8)).resize((W, H), Image.BILINEAR), np.float32) / 255
        yy = np.linspace(0, 1, H)[:, None]
        front = 1.25 - p * 2.6                       # wipe front position
        inten = np.clip((yy - front) * 2.2 + nz * 0.9 - 0.25, 0, 1.4)
        inten *= np.clip((front + 1.6 - yy) * 2.0, 0, 1)   # tail leaves at the top at the end
        idx = np.clip(inten / 1.4 * 255, 0, 255).astype(np.uint8)
        return Image.fromarray(self.lut[idx], "RGBA")


# ----------------------------------------------------------------- audio
def kick():
    t = np.arange(int(SR * 0.35)) / SR
    f = 40 + 90 * np.exp(-t * 25)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9) * 0.9).astype(np.float32)


def hat():
    n = np.random.randn(int(SR * 0.05)).astype(np.float32)
    n = n - np.convolve(n, np.ones(6) / 6, "same")
    return n * np.exp(-np.arange(len(n)) / SR * 70) * 0.25


def boom():
    t = np.arange(int(SR * 1.2)) / SR
    f = 30 + 120 * np.exp(-t * 6)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 3)
    nz = np.convolve(np.random.randn(len(t)), np.ones(40) / 40, "same") * np.exp(-t * 5) * 0.6
    return ((s + nz) * 0.8).astype(np.float32)


def riser(d):
    t = np.arange(int(SR * d)) / SR
    f = 200 + 1600 * (t / d) ** 2
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.15
    nz = np.random.randn(len(t)) * 0.08
    return ((s + nz) * (t / d) ** 2).astype(np.float32)


def beat(total, bpm=124):
    n = int(SR * (total + 1)); out = np.zeros(n, np.float32)
    step = 60 / bpm / 2; i = 0; tt = 0.0
    bassline = [55.0, 55.0, 65.41, 49.0]
    K, Hh = kick(), hat()
    while tt < total:
        k = int(tt * SR)
        if i % 2 == 0:
            out[k:k + len(K)] += K[: n - k] * 0.7
        else:
            out[k:k + len(Hh)] += Hh[: n - k]
        if i % 4 == 2:
            b = R.tone(bassline[(i // 8) % 4] * 2, step * 1.8, 5, 0.35)
            b = np.sign(b) * np.abs(b) ** 0.7 * 0.6
            out[k:k + len(b)] += b[: n - k]
        tt += step; i += 1
    return out


# ----------------------------------------------------------------- build
THEME = [("smotheredMate", "Smothered by its own pieces!"), ("backRankMate", "The king is trapped on the back rank!"),
         ("sacrifice", "A sacrifice to rip the king open!"), ("attraction", "The king got dragged into the net!"),
         ("deflection", "Deflect the defender. Game over!"), ("fork", "A fork. Two targets, one move!"),
         ("pin", "That piece was pinned!"), ("skewer", "A skewer!"), ("discoveredAttack", "A discovered attack!"),
         ("promotion", "Promote and win!"), ("hangingPiece", "A free piece!")]
HOOKS = {
    "basic": [("Think you're good at chess?", "Prove it."), ("Most beginners miss this.", "Do you?")],
    "intermediate": [("Think you're a chess genius?", "Prove it."), ("Only 3% of club players see this.", "Do you?")],
    "advanced": [("This is master level.", "No excuses."), ("Think you can calculate?", "Prove it.")],
    "tagfriend": [("Tag a friend.", "Who solves it first?"), ("You versus your chess buddy.", "Go!")],
}


def build(P, seed, out, mode="level", skip_hook=False, backdrop=None):
    rng = random.Random(f"{P.get('id')}-{seed}-{mode}")
    LV = R.LEVELS[P["level"]]
    if "fen" in P:
        board = chess.Board(P["fen"]); ms = P["moves"].split(); board.push(chess.Move.from_uci(ms[0])); sol = ms[1:]
    else:
        board = chess.Board()
        for m in P["pgn"].split(): board.push_san(m)
        sol = P["sol"]
    last = board.peek(); flip = board.turn == chess.BLACK; side = "Black" if flip else "White"
    moves = [chess.Move.from_uci(u) for u in sol]
    b2 = board.copy(); sans = []
    for m in moves: sans.append(b2.san(m)); b2.push(m)
    mate_n = (len(moves) + 1) // 2 if b2.is_checkmate() else None
    COUNT = LV["count"]
    themes = (P.get("themes") or "").split()
    finale = next((l for k, l in THEME if k in themes), "No escape squares!" if mate_n else "And that wins!")
    h1, h2 = rng.choice(HOOKS["tagfriend" if mode == "tagfriend" else P["level"]])
    goal_say = f"mate in {R.NUM[mate_n]}" if mate_n else "the winning move"
    numw = {8: "eight", 10: "ten", 12: "twelve"}[COUNT]

    lines = ([] if skip_hook else [("h1", h1), ("h2", h2)]) + [
             ("lvl", f"{LV['name'].title()} level. {side} to move. Find {goal_say}."),
             ("go", f"You've got {numw} seconds. Go!"),
             ("up", "Time's up!")]
    lines += [(f"m{i}", R.san_say(s)) for i, s in enumerate(sans)]
    lines += [("fin", finale),
              ("cta", ("Tag a friend who can't solve it! " if mode == "tagfriend" else "Did you get it? ")
               + "Train your calculation every day on StreakChess. It's free. Link in bio.")]

    import voice
    STY = {"h1": "playful challenge, a little cocky", "h2": "teasing, with a smile", "lvl": "clear and friendly, like a coach",
           "go": "upbeat, encouraging", "up": "playful, slightly dramatic", "fin": "satisfied, impressed",
           "cta": "warm and genuine, like recommending something to a friend"}
    clips = voice.say_many([v for _, v in lines], speed=1.12,
                           styles=[STY.get(k, "confident, calm, revealing the answer") for k, _ in lines])
    A = {k: c for (k, _), c in zip(lines, clips)}; TXT = dict(lines)
    D = {k: len(a) / SR for k, a in A.items()}

    T = {}; t = 0.0
    def add(k, d):
        nonlocal t; T[k] = (t, t + d); t += d
    if skip_hook:
        T["h1"] = T["h2"] = (0.0, 0.0)
    else:
        add("h1", D["h1"] + 0.15); add("h2", D["h2"] + 0.45)
    add("fire1", 0.0)
    add("lvl", D["lvl"] + 0.1)
    add("go", D["go"] + 0.1)
    add("count", COUNT)
    add("up", D["up"] + 0.25)
    for i in range(len(sans)): add(f"m{i}", max(D[f"m{i}"] + 0.2, 1.25))
    add("fin", D["fin"] + 0.6)
    add("cta", D["cta"] + 1.2)
    total = t
    VO_AT = {k: T[k][0] + 0.05 for k in A}

    # ---- audio
    n = int(SR * (total + 0.5)); vo = np.zeros(n, np.float32); fx = np.zeros(n, np.float32)
    def put(buf, a, at, g=1.0):
        i = int(at * SR)
        if i >= n: return
        if i < 0: a = a[-i:]; i = 0
        j = min(n, i + len(a)); buf[i:j] += a[: j - i] * g
    for k in A: put(vo, A[k], VO_AT[k])
    if not skip_hook: put(fx, boom(), T["h2"][0], 0.9)
    put(fx, R.whoosh(0.6), T["lvl"][0] - 0.3, 1.2)
    put(fx, boom(), T["lvl"][0], 0.5)
    for i in range(COUNT): put(fx, R.tick(i >= COUNT - 3), T["count"][0] + i, 1.3)
    put(fx, riser(3.0), T["count"][1] - 3.0, 1.0)
    put(fx, boom(), T["up"][0], 1.0)
    for i in range(len(sans)):
        put(fx, R.whoosh(0.3), T[f"m{i}"][0] + 0.2, 0.8); put(fx, kick(), T[f"m{i}"][0] + 0.62, 0.9)
    put(fx, boom(), T["fin"][0], 1.0); put(fx, R.ding(), T["fin"][0], 0.7)
    put(fx, R.whoosh(0.6), T["cta"][0] - 0.25, 1.2)
    music = beat(total)[:n]
    music[int(T["count"][0] * SR):int(T["count"][1] * SR)] *= 0.45      # tension: thinner during countdown
    venv = np.convolve((np.abs(vo) > 0.01).astype(np.float32), np.ones(3000) / 3000, "same")
    mix = vo * 1.15 + fx + music * (0.42 - 0.24 * np.clip(venv * 3, 0, 1))
    mix = np.tanh(mix * 1.1) * 0.92
    wav = out.replace(".mp4", ".wav"); sf.write(wav, mix, SR)
    hop = SR // FPS
    env = np.array([np.sqrt(np.mean(vo[i * hop:(i + 1) * hop] ** 2)) for i in range(int(total * FPS) + 2)])
    env = np.clip(env / (np.percentile(env[env > 0.004], 85) + 1e-6), 0, 1)

    # word timing (proportional to characters inside each spoken line)
    WORDS = {}
    for k, txt in lines:
        ws = txt.split(); L = sum(len(w) + 1 for w in ws); acc = 0; lst = []
        for w in ws:
            lst.append((VO_AT[k] + D[k] * acc / L * 0.95, w)); acc += len(w) + 1
        WORDS[k] = lst

    def caption(tt):
        for k, _ in lines:
            if k in ("count", "lvl", "go") or k.startswith("m"): continue
            a, b = T[k]
            if a <= tt < b:
                cur = [(ts, w) for ts, w in WORDS[k] if ts <= tt]
                if not cur: return None
                idx = len(cur) - 1; start = (idx // 3) * 3
                return [w for _, w in cur[start:idx + 1]], tt - cur[-1][0]
        return None

    # ---- assets
    bg = BG(); mas = Mascot()
    bd_dark = bd_soft = None
    if backdrop is not None:   # keep the story's world behind the puzzle (premium, cohesive look)
        im = backdrop.convert("RGB"); r_ = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * r_) + 1, int(im.height * r_) + 1), Image.LANCZOS)
        im = im.crop(((im.width - W) // 2, (im.height - H) // 2, (im.width - W) // 2 + W, (im.height - H) // 2 + H))
        bl = im.filter(ImageFilter.GaussianBlur(22))
        bd_soft = Image.blend(bl, Image.new("RGB", (W, H), (10, 8, 18)), 0.45).convert("RGBA")
        bd_dark = Image.blend(bl, Image.new("RGB", (W, H), (8, 6, 14)), 0.68).convert("RGBA")

    def back(tt, soft=False):
        if bd_dark is None:
            return bg.stage_frame(tt)
        im = (bd_soft if soft else bd_dark).copy(); d = ImageDraw.Draw(im)
        for x, y, r, sp in bg.dust[:40]:
            yy = (y - tt * sp) % H; d.ellipse([x - r, yy - r, x + r, yy + r], fill=(255, 235, 180, 50))
        return im
    lg = Image.open(os.path.join(HERE, "assets", "logo_h.png")).convert("RGBA"); lg = lg.crop(lg.getbbox())
    lg = lg.resize((620, int(lg.height * 620 / lg.width)), Image.LANCZOS)
    logo_v = Image.new("RGBA", (lg.width + 80, lg.height + 60), (0, 0, 0, 0))
    ImageDraw.Draw(logo_v).rounded_rectangle([0, 0, logo_v.width - 1, logo_v.height - 1], 40, fill=(255, 255, 255, 255), outline=INK, width=8)
    logo_v.alpha_composite(lg, (40, 30))
    states = [board.copy()]
    for m in moves:
        s2 = states[-1].copy(); s2.push(m); states.append(s2)
    cache = {}

    def board_card(tt):
        if tt < T["m0"][0] + 0.35:
            if "s" not in cache: cache["s"] = R.card(R.draw_board(board, flip, (last.from_square, last.to_square)))
            return cache["s"], None
        i = max(j for j in range(len(moves)) if tt >= T[f"m{j}"][0] + 0.35)
        m = moves[i]; prog = eio((tt - T[f"m{i}"][0] - 0.35) / 0.32); st = states[i]
        if prog >= 1:
            red = states[i + 1].king(states[i + 1].turn) if (i == len(moves) - 1 and mate_n) else None
            k = ("d", i, red)
            if k not in cache:
                im = R.draw_board(states[i + 1], flip, (m.from_square, m.to_square), red=red)
                R.draw_arrow(im, m.from_square, m.to_square, flip, (242, 98, 46, 170) if i % 2 == 0 else (90, 90, 110, 120))
                cache[k] = R.card(im)
            return cache[k], m.to_square
        im = R.draw_board(st, flip, (m.from_square,), hide=m.from_square)
        x1, y1 = R.sq_xy(m.from_square, flip); x2, y2 = R.sq_xy(m.to_square, flip)
        if prog > 0.6 and st.piece_at(m.to_square):
            tx, ty = R.sq_xy(m.to_square, flip)
            light = (chess.square_file(m.to_square) + chess.square_rank(m.to_square)) % 2 == 1
            ImageDraw.Draw(im).rectangle([tx, ty, tx + R.SQ, ty + R.SQ], fill=R.LIGHT if light else R.DARKSQ)
        lift = -60 * math.sin(math.pi * prog); sc = 1 + 0.25 * math.sin(math.pi * prog)
        pc = R.piece_img(st.piece_at(m.from_square), int(R.SQ * sc))
        im.alpha_composite(pc, (int(x1 + (x2 - x1) * prog - (pc.width - R.SQ) / 2), int(y1 + (y2 - y1) * prog + lift - (pc.height - R.SQ) / 2)))
        return R.card(im), m.to_square

    def put_mascot(fr, tt, sc, cx, bottom, mood, look, mouth, bounce=0, tilt=0, squash=0, rim=True):
        mi = mas.render(tt, mouth=mouth, mood=mood, look=look, bounce=bounce, tilt=tilt, squash=squash)
        mw, mh = int(mi.width * sc), int(mi.height * sc)
        if mw < 8: return
        mi = mi.resize((mw, mh), Image.BILINEAR)
        x, y = int(cx - mw / 2), int(bottom - mh)
        if rim:  # yellow rim light from the spotlight (top-right)
            a = mi.getchannel("A")
            rimc = Image.new("RGBA", mi.size, YEL + (0,)); rimc.putalpha(a.filter(ImageFilter.GaussianBlur(3)))
            fr.alpha_composite(rimc, (x + int(10 * sc), y - int(8 * sc)))
            sh = Image.new("RGBA", (int(mw * 0.8), int(mh * 0.08)), (0, 0, 0, 0))
            ImageDraw.Draw(sh).ellipse([0, 0, sh.width - 1, sh.height - 1], fill=(0, 0, 0, 120))
            fr.alpha_composite(sh.filter(ImageFilter.GaussianBlur(10)), (int(cx - sh.width / 2), int(bottom - sh.height * 0.8)))
        fr.alpha_composite(mi, (x, y))

    sparks = [(rng.uniform(0, 2 * math.pi), rng.uniform(400, 1300), rng.choice([YEL, ORA, WHITE, (255, 120, 60)])) for _ in range(90)]
    ring_font = ImageFont.truetype(F900, 120)

    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-i", wav, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out],
                            stdin=subprocess.PIPE)
    for fi in range(int(total * FPS)):
        tt = fi / FPS
        mouth = float(env[fi]) * (0.75 + 0.25 * math.sin(tt * 41))
        zoom, cxo, cyo, shake, flash = 1.0, 0.0, 0.0, 0.0, 0.0
        BOARD_CY = 1150

        if tt < T["h1"][1]:                                   # hook line 1: spotlight stage
            lt = tt
            fr = bg.stage_frame(tt)
            put_mascot(fr, tt, 1.35 * (0.9 + 0.1 * eo(lt / 0.4)), W / 2 + 40, 1820, "determined", (-0.2, 0.15), mouth,
                       tilt=-2 + 2 * math.sin(lt * 2))
            zoom = 1.0 + 0.05 * lt
        elif tt < T["h2"][1]:                                 # "PROVE IT." extreme close-up
            lt = tt - T["h2"][0]
            fr = bg.stage_frame(tt)
            put_mascot(fr, tt, 3.2, W / 2 - 330, 3050, "angry", (-0.15, 0.1), mouth, rim=True)
            zoom = 1.12 - 0.1 * eo(lt / 0.3); shake = 18 * max(0, 1 - lt / 0.35); flash = max(0, 0.6 - lt * 3)
        elif tt < T["go"][1]:                                 # level reveal on sunburst
            lt = tt - T["lvl"][0]
            fr = back(tt, True) if bd_soft is not None else bg.burst(tt, tuple(min(255, c + 30) for c in LV["color"]), LV["color"])
            chip = R.pill(f"{LV['name']}  {LV['rng']}", 52, WHITE, fg=INK, padx=44, pady=18)
            R.paste_center(fr, chip, W / 2, 330, eob(lt / 0.35))
            goal = word_img(f"MATE IN {mate_n}!" if mate_n else "WIN!", 150, YEL)
            R.paste_center(fr, goal, W / 2, 560, eob((lt - 0.5) / 0.35), 1.0, -3)
            stm = word_img(f"{side.upper()} TO MOVE", 76, WHITE, 8)
            R.paste_center(fr, stm, W / 2, 720, eob((lt - 0.8) / 0.35))
            put_mascot(fr, tt, 0.9 if bd_soft is not None else 1.0, W / 2, 1880 - 30 * abs(math.sin(lt * 4)),
                       "excited" if tt < T["go"][0] else "determined", (0.0, 0.0), mouth, tilt=4 * math.sin(lt * 3),
                       rim=bd_soft is not None)
            zoom = 1.04 - 0.04 * eo(lt / 0.5)
            if lt < 0.2: shake = 10
        else:
            fr = back(tt)
            if tt < T["cta"][0]:
                # board stage
                card, focus = board_card(tt)
                enter = eo((tt - T["count"][0] + 0.6) / 0.5) if tt < T["count"][0] + 0.5 else 1
                R.paste_center(fr, R.shadowed(card, 30, (0, 20), 160)[0], W / 2, BOARD_CY + (1 - enter) * 1100, 0.96)
                mood, look = "thinking", (0.5 * math.sin(tt * 1.4), 0.7)
                if tt >= T["up"][0]: mood, look = "surprised", (0.6, 0.7)
                if tt >= T["fin"][0]: mood = "star"
                bounce = 50 * abs(math.sin((tt - T["fin"][0]) * 7)) * max(0, 1 - (tt - T["fin"][0]) / 1.4) if tt >= T["fin"][0] else 0
                put_mascot(fr, tt, 0.5, 205, 600, mood, look, mouth, bounce=bounce, tilt=3 * math.sin(tt * 2))
                if T["count"][0] <= tt < T["count"][1]:     # ring countdown
                    lt = tt - T["count"][0]; remain = COUNT - int(lt); ph = lt % 1
                    ring = Image.new("RGBA", (300, 300), (0, 0, 0, 0)); rd = ImageDraw.Draw(ring)
                    rd.ellipse([10, 10, 290, 290], fill=(20, 16, 28, 230))
                    col = RED if remain <= 3 else YEL
                    rd.arc([18, 18, 282, 282], -90, -90 + 360 * (1 - lt / COUNT), fill=col, width=22)
                    txt = str(remain); tw = ring_font.getlength(txt)
                    rd.text((150 - tw / 2, 70), txt, font=ring_font, fill=WHITE)
                    R.paste_center(fr, ring, 820, 330, 1 + (0.15 if remain <= 3 else 0.06) * max(0, 1 - ph * 5))
                    zoom = 1.0   # board stays perfectly still while the viewer thinks
                    cap = word_img("PAUSE IF YOU NEED TIME" if lt < COUNT / 2 else "COMMENT YOUR MOVE!", 54, WHITE, 7)
                    R.paste_center(fr, cap, W / 2, 1780, eob(((lt % (COUNT / 2))) / 0.3))
                if T["up"][0] <= tt < T["up"][1]:
                    lt = tt - T["up"][0]; flash = max(0, 0.55 - lt * 2.5); shake = 14 * max(0, 1 - lt / 0.3)
                    R.paste_center(fr, word_img("TIME'S UP!", 130, RED), W / 2 + 160, 330, eob(lt / 0.3), 1, -4)
                for i in range(len(sans)):
                    a, b = T[f"m{i}"]
                    if a <= tt < b:
                        lt = tt - a
                        col = YEL if i % 2 == 0 else WHITE
                        R.paste_center(fr, word_img(sans[i], 140, col), W / 2 + 170, 330, eob(lt / 0.28), 1, -3 if i % 2 else 3)
                        lab = "CHECKMATE!" if "#" in sans[i] else ("CHECK!" if "+" in sans[i] else ("BLACK" if (states[i].turn == chess.BLACK) else "WHITE"))
                        R.paste_center(fr, word_img(lab, 56, RED if "#" in sans[i] else WHITE, 7), W / 2 + 170, 470, eob((lt - 0.55) / 0.25))
                        if 0.62 <= lt < 0.9: shake = 10 * (1 - (lt - 0.62) / 0.28)
                        if focus is not None and lt > 0.3:   # punch in toward the landing square
                            fx_, fy_ = R.sq_xy(focus, flip)
                            px = (fx_ + R.SQ / 2 + 22 - 494) * 0.96; py = (fy_ + R.SQ / 2 + 22 - 494) * 0.96
                            k = eio((lt - 0.3) / 0.5) * 0.14
                            zoom = 1 + k; cxo, cyo = px * k * 0.9, (BOARD_CY - H / 2 + py) * k * 0.9
                if T["fin"][0] <= tt < T["fin"][1]:
                    lt = tt - T["fin"][0]
                    flash = max(flash, 0.7 - lt * 2.5); shake = max(shake, 22 * max(0, 1 - lt / 0.5))
                    d = ImageDraw.Draw(fr)
                    for ang, sp, c in sparks:
                        r0 = sp * lt; x = W / 2 + math.cos(ang) * r0; y = BOARD_CY + math.sin(ang) * r0 + 400 * lt * lt
                        s = max(2, 14 * (1 - lt))
                        d.ellipse([x - s, y - s, x + s, y + s], fill=c)
                    R.paste_center(fr, word_img("CHECKMATE!" if mate_n else "WINNING!", 150, YEL), W / 2, 1150, eob(lt / 0.3), 1, -5)
            else:                                           # CTA on sunburst
                lt = tt - T["cta"][0]
                fr = back(tt, True) if bd_soft is not None else bg.burst(tt, (255, 140, 50), (235, 92, 40))
                R.paste_center(fr, logo_v, W / 2, 330, eob(lt / 0.4), 1, -3)
                put_mascot(fr, tt, 0.78, W / 2, 1560, "excited", (0, 0), mouth, bounce=12 * abs(math.sin(lt * 5)), rim=False)
                R.paste_center(fr, R.pill("100% FREE TO PLAY", 46, (88, 204, 2), fg=WHITE, padx=40, pady=16), W / 2, 1610, eob((lt - 1.0) / 0.35))
                R.paste_center(fr, R.pill("FOUNDER OFFER - FIRST 500 ACCOUNTS", 38, INK, fg=YEL, padx=36, pady=14), W / 2, 1712, eob((lt - 1.6) / 0.35))
                R.paste_center(fr, R.pill("streakchess.com", 66, WHITE, fg=ORA, padx=50, pady=18), W / 2, 1830 - 20, eob((lt - 2.2) / 0.35) * (1 + 0.03 * math.sin(lt * 7)))
                zoom = 1.06 - 0.06 * eo(lt / 0.5)

        # kinetic captions for spoken lines
        cap = caption(tt)
        if cap and not (T["count"][0] <= tt < T["count"][1]):
            words, nt = cap
            y = 330 if tt < T["h2"][1] else (1000 if tt < T["go"][1] else (1380 if tt < T["cta"][0] else 1080))
            if T["lvl"][0] <= tt < T["go"][1]: y = 880
            if T["fin"][0] <= tt < T["cta"][0]: y = 1770
            if tt >= T["cta"][0]: y = 690
            if not (T["up"][0] <= tt < T["fin"][0]):
                ph = phrase_img(words, nt, 104 if tt < T["h2"][1] else 84)
                band = Image.new("RGBA", (W, ph.height + 80), (0, 0, 0, 0))
                ImageDraw.Draw(band).rounded_rectangle([40, 20, W - 40, band.height - 20], 40, fill=(0, 0, 0, 110))
                R.paste_center(fr, band.filter(ImageFilter.GaussianBlur(14)), W / 2, y)
                R.paste_center(fr, ph, W / 2, y)
        # fire wipes between acts
        for key, dur in (("lvl", 0.55), ("cta", 0.55)):
            ft = tt - (T[key][0] - dur / 2)
            if 0 <= ft < dur:
                fr.alpha_composite(bg.fire(ft / dur))

        # camera
        if zoom != 1 or cxo or cyo or shake:
            sx = (random.uniform(-1, 1) * shake); sy = (random.uniform(-1, 1) * shake)
            zw, zh = W / zoom, H / zoom
            x0 = W / 2 + cxo - zw / 2 + sx; y0 = H / 2 + cyo - zh / 2 + sy
            x0 = min(max(x0, 0), W - zw); y0 = min(max(y0, 0), H - zh)
            fr = fr.crop((int(x0), int(y0), int(x0 + zw), int(y0 + zh))).resize((W, H), Image.BILINEAR)
        if flash > 0:
            fr = Image.blend(fr, Image.new("RGBA", (W, H), (255, 255, 255, 255)), min(0.8, flash))
        proc.stdin.write(grain(fr, fi))
    proc.stdin.close(); proc.wait(); os.remove(wav)

    first = rng.choice(R.TAG_CAPTIONS) if mode == "tagfriend" else f"{h1} {h2}"
    ig = (f"{first}\n{LV['name'].title()} puzzle ({LV['rng']}). {side} to move, {goal_say}.\n\n"
          + ("Comment the move and tag a friend to challenge them!\n\n" if mode == "tagfriend" else "Comment your move before watching the solution!\n\n")
          + "Train your calculation every day on StreakChess. Free to play. Founder offer for the first 500 accounts, link in bio.\n\n"
          + " ".join(R.hashtags(rng)))
    open(out.replace(".mp4", ".txt"), "w").write(ig)
    return dict(mode=mode, puzzle=P.get("id"), level=P["level"], rating=P.get("rating"), hook=f"{h1} {h2}", sans=sans,
                duration=round(total, 1))


if __name__ == "__main__":
    P = json.load(open(sys.argv[1]))
    print(json.dumps(build(P, int(sys.argv[2]), sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "level"), indent=1))
