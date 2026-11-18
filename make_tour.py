"""'Inside StreakChess' app-tour reel: a guided walkthrough of the real app (3 a week).

What the viewer sees: the real app on a phone from the very first frame, then the camera pushes into the part of the
screen being explained (so the text is readable on a phone), with a gold highlight on the element and a tap where
the user would tap. Vektor hosts from the top of the screen, kinetic subtitles follow the voice, and the reel ends
with one easy question (comments) and the app card.

Everything said is in assets/app/tours.json and describes a real feature; the screens are real screenshots from a
demo account (assets/app/screens) - never mock-ups. To refresh a screen, replace the .jpg with a new 1080-wide
screenshot of the same page.

python make_tour.py <seed> out.mp4 [episode_id]        (voice: Gemini if GEMINI_API_KEY, else local)
TOUR_MOCK=1 ...                                          (offline: local voice, no Gemini text, no review)
"""
import json, math, os, random, re, subprocess, sys
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import make_reel as R
import make_hype as HY
import make_science as SCI

HERE = os.path.dirname(os.path.abspath(__file__))
TOURS = os.path.join(HERE, "assets", "app", "tours.json")
SCREENS = os.path.join(HERE, "assets", "app", "screens")
LOG = os.path.join(HERE, "tour_log.json")
W, H, FPS, SR = HY.W, HY.H, HY.FPS, HY.SR
GOLD, IVORY, INK = HY.YEL, HY.WHITE, HY.INK
SERIES = "INSIDE STREAKCHESS"
PAD_X = 60                                    # left edge of the header column
BADGE_Y, LABEL_Y = 270, 318                   # series badge (centre) / top of the big label
CARD_TOP, BOX_W, BOX_H = 478, 880, 850        # the app screen lives in y 478-1328 (phone safe zone is 250-1470)
SUB_Y = 1405
eo, eob, eio, clamp = R.ease_out, R.ease_out_back, R.ease_in_out, R.clamp
NUMWORDS = set("zero one two three four five six seven eight nine ten eleven twelve thirty fifty hundred first second third".split())


# ----------------------------------------------------------------- episodes
def tours():
    return json.load(open(TOURS))


def pick_episode(seed, ep_id=None):
    """Least recently used first: every episode runs before any repeats."""
    eps = tours()["episodes"]
    if ep_id:
        return next(e for e in eps if e["id"] == ep_id)
    log = json.load(open(LOG)) if os.path.exists(LOG) else []
    used = [e.get("tour") for e in log]
    never = [e for e in eps if e["id"] not in used]
    bi = os.environ.get("BATCH_INDEX", "")                # test batches (nothing is logged): a different one each
    if never:
        return never[int(bi) % len(never)] if bi.isdigit() else never[0]                                   # first pass: in the written order (it starts with "how it works")
    last = {e["id"]: max(i for i, u in enumerate(used) if u == e["id"]) for e in eps}
    return min(eps, key=lambda e: last[e["id"]])


def _nums(s):
    return sorted(w for w in re.findall(r"[a-z]+|\d+", s.lower()) if w in NUMWORDS or w.isdigit())


def script_for(ep, variant=0, mock=False):
    """[hook, scene lines..., question, end]. On repeats Gemini rewrites the wording but every number must survive."""
    lines = [ep["hook_say"]] + [s["say"] for s in ep["scenes"]] + [ep["question"]["say"], tours()["end_say"]]
    if variant and not mock and os.environ.get("GEMINI_API_KEY"):
        try:
            import reviewer
            body = lines[:-2]
            res = reviewer._ask([{"text": f"""You write voice-over for a short product walkthrough of a chess training app (StreakChess).
Rewrite these narration lines so they sound NEW (different words, same meaning, same order).
HARD RULES: every line must describe exactly the same feature with exactly the same numbers (written as words);
do not add any feature, number, price, result or claim that is not in the original; 8-22 words each; plain spoken
English, concrete, no hype words ("revolutionary", "game-changer", "unlock"). Keep the names StreakChess, Vektor,
Puzzle Blitz, Puzzle Survival, Deep Calculation, Boss Fight exactly.
Original lines (JSON list): {json.dumps(body, ensure_ascii=False)}
Return JSON: {{"lines": [str, ...]}} with the same number of lines."""}], 0.8)
            new = [str(x).strip() for x in (res.get("lines") or [])]
            if len(new) == len(body) and all(5 <= len(n.split()) <= 26 and _nums(n) == _nums(o) for n, o in zip(new, body)):
                lines = new + lines[-2:]
                print("tour: narration variant", variant, flush=True)
        except Exception as e:
            print("tour: variant skipped:", str(e)[:120], flush=True)
    return lines


# ----------------------------------------------------------------- drawing
def font(size, bold=True):
    return ImageFont.truetype(SCI.F_BOLD if bold else SCI.F_SEMI, size)


def left_label(txt, maxw=690, size=62, min_size=44, color=GOLD, max_lines=2):
    """Big left-aligned display label (upper case), shrunk until it fits in max_lines."""
    txt = txt.upper()
    while True:
        f = font(size); words = txt.split(); lines, cur = [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if f.getlength(t) <= maxw or not cur:
                cur = t
            else:
                lines.append(cur); cur = w
        lines.append(cur)
        if (len(lines) <= max_lines and all(f.getlength(l) <= maxw for l in lines)) or size <= min_size:
            break
        size -= 2
    lh = int(size * 1.12)
    im = Image.new("RGBA", (maxw + 40, lh * len(lines) + 30), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for i, l in enumerate(lines):
        d.text((20, 10 + i * lh), l, font=f, fill=color + (255,))
    return SCI.glow(im, color, 14, 45)


def badge(n):
    """Series badge: 'INSIDE STREAKCHESS · #07' + a small honest note about the screens."""
    b = R.outline_pill(f"{SERIES}  ·  #{n:02d}", 26, color=GOLD, fg=IVORY, padx=24, pady=10)
    note = R.text_img("real app · demo account", 21, (165, 170, 196))
    im = Image.new("RGBA", (b.width + 18 + note.width, max(b.height, note.height)), (0, 0, 0, 0))
    im.alpha_composite(b, (0, (im.height - b.height) // 2)); im.alpha_composite(note, (b.width + 18, (im.height - note.height) // 2))
    return im


_SCR = {}


def screen(name):
    if name not in _SCR:
        _SCR[name] = Image.open(os.path.join(SCREENS, name + ".jpg")).convert("RGB")
    return _SCR[name]


def rect_of(focus, size):
    """focus [y0,y1] or [x0,y0,x1,y1] (fractions) -> pixel rect on the screenshot."""
    sw, sh = size
    if focus is None:
        return (0.0, 0.0, float(sw), float(sh))
    if len(focus) == 2:
        return (0.0, focus[0] * sh, float(sw), focus[1] * sh)
    return (focus[0] * sw, focus[1] * sh, focus[2] * sw, focus[3] * sh)


def lerp_rect(a, b, k):
    return tuple(a[i] + (b[i] - a[i]) * k for i in range(4))


def widen(r, size, k=0.16):
    """The same rect seen from a little further away (start of the push-in), clamped to the screenshot."""
    sw, sh = size; cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2; w, h = (r[2] - r[0]) * (1 + k), (r[3] - r[1]) * (1 + k)
    w, h = min(w, sw), min(h, sh)
    x0 = min(max(0, cx - w / 2), sw - w); y0 = min(max(0, cy - h / 2), sh - h)
    return (x0, y0, x0 + w, y0 + h)


_MASK, _SHADOW = {}, {}


def card(name, rect, fast=False):
    """The visible part of a screenshot as a phone-screen card. Returns (image, scale, pad) where pad is the bezel."""
    scr = screen(name); x0, y0, x1, y1 = rect
    s = min(BOX_W / (x1 - x0), BOX_H / (y1 - y0))
    w, h = max(8, int(round((x1 - x0) * s))), max(8, int(round((y1 - y0) * s)))
    view = scr.resize((w, h), Image.BILINEAR if fast else Image.LANCZOS, box=(x0, y0, x1, y1))
    pad, rad = 12, 40
    key = (w, h)
    if key not in _MASK:
        if len(_MASK) > 40: _MASK.clear()
        m = Image.new("L", (w, h), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], rad - 8, fill=255)
        _MASK[key] = m
    out = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0)); d = ImageDraw.Draw(out)
    d.rounded_rectangle([0, 0, out.width - 1, out.height - 1], rad, fill=(8, 8, 14, 255), outline=(232, 222, 200, 235), width=3)
    out.paste(view, (pad, pad), _MASK[key])
    return out, s, pad


def shadow(w, h):
    """Soft gold halo + drop shadow behind the card (drawn small and scaled up: cheap enough for every frame)."""
    key = (w // 8, h // 8)
    if key not in _SHADOW:
        if len(_SHADOW) > 60: _SHADOW.clear()
        sw, sh = w // 4 + 60, h // 4 + 60
        im = Image.new("RGBA", (sw, sh), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.rounded_rectangle([30, 34, sw - 30, sh - 26], 12, fill=(0, 0, 0, 170))
        d.rounded_rectangle([26, 26, sw - 26, sh - 34], 12, fill=GOLD + (60,))
        _SHADOW[key] = im.filter(ImageFilter.GaussianBlur(10))
    return _SHADOW[key].resize((w + 240, h + 240), Image.BILINEAR)


def highlight(fr, box, rect, s, origin, a, t):
    """Gold rounded outline (with a soft glow and a slow pulse) around an element of the screenshot."""
    if a <= 0: return
    ox, oy = origin
    x0, y0 = ox + (box[0] - rect[0]) * s, oy + (box[1] - rect[1]) * s
    x1, y1 = ox + (box[2] - rect[0]) * s, oy + (box[3] - rect[1]) * s
    grow = 10 * (1 - eo(a)); pulse = 0.5 + 0.5 * math.sin(t * 4.0)
    L = Image.new("RGBA", (int(x1 - x0) + 120, int(y1 - y0) + 120), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    d.rounded_rectangle([60 - grow, 60 - grow, L.width - 60 + grow, L.height - 60 + grow], 26, outline=GOLD + (int(255 * min(1, a * 1.5)),), width=7)
    g = L.filter(ImageFilter.GaussianBlur(12))
    g.putalpha(g.getchannel("A").point(lambda v: int(v * (0.55 + 0.35 * pulse))))
    fr.alpha_composite(g, (int(x0) - 60, int(y0) - 60)); fr.alpha_composite(L, (int(x0) - 60, int(y0) - 60))


def tap_mark(fr, pt, rect, s, origin, q):
    """A fingertip that lands on the element and a ring that spreads from it (q: 0..1 through the tap)."""
    if q <= 0 or q >= 1: return
    x, y = origin[0] + (pt[0] - rect[0]) * s, origin[1] + (pt[1] - rect[1]) * s
    d = ImageDraw.Draw(fr)
    if q > 0.35:
        k = (q - 0.35) / 0.65; r = 26 + 70 * eo(k)
        d.ellipse([x - r, y - r, x + r, y + r], outline=GOLD + (int(230 * (1 - k)),), width=6)
    land = eo(q / 0.35); r = 30 - 5 * math.sin(min(1, q / 0.5) * math.pi)
    yy = y + 46 * (1 - land)
    d.ellipse([x - r - 4, yy - r - 4, x + r + 4, yy + r + 4], fill=(10, 10, 18, int(150 * land)))
    d.ellipse([x - r, yy - r, x + r, yy + r], fill=IVORY + (int(245 * land),), outline=GOLD + (255,), width=4)


def end_layer(p, t, logo, phone):
    """App card: the real home screen on a phone + what StreakChess is, in one glance."""
    L = Image.new("RGBA", (980, 800), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    d.rounded_rectangle([0, 0, 979, 799], 44, fill=(10, 10, 18, 222), outline=GOLD + (210,), width=2)
    q = eo(p / 0.35)
    ph = phone.copy(); ph.putalpha(ph.getchannel("A").point(lambda v: int(v * q)))
    L.alpha_composite(ph, (44, (800 - ph.height) // 2 + int(30 * (1 - q))))
    x0 = 44 + phone.width + 34; colw = 980 - x0 - 40; y = 96
    lg = logo.resize((min(colw, 470), int(logo.height * min(colw, 470) / logo.width)), Image.LANCZOS)
    L.alpha_composite(lg, (x0 + (colw - lg.width) // 2, y)); y += lg.height + 40
    rows = [("THE DAILY CHESS\nTRAINING APP", 46, GOLD, "t", 30), ("streakchess.com", 50, IVORY, "p", 34),
            ("FREE TO START  ·  ALL LEVELS", 27, IVORY, "w", 4), ("FOUNDER OFFER: FIRST 500 ACCOUNTS", 23, GOLD, "w", 0)]
    for k, (txt, size, col, kind, gap) in enumerate(rows):
        a = eo((p - 0.14 * k - 0.1) / 0.35)
        if kind == "p":
            im = R.pill(txt, size, IVORY, fg=INK, padx=38, pady=16)
        elif kind == "t":                                         # two tight centred lines
            f = font(size); ls = txt.split("\n"); lh = int(size * 1.16)
            im = Image.new("RGBA", (int(max(f.getlength(l) for l in ls)) + 8, lh * len(ls) + 8), (0, 0, 0, 0)); dd = ImageDraw.Draw(im)
            for i, l in enumerate(ls):
                dd.text(((im.width - f.getlength(l)) / 2, i * lh), l, font=f, fill=col + (255,))
        else:
            im = HY.word_img(txt, size, col, 0); im = im.crop(im.getbbox())
        if im.width > colw:
            im = im.resize((colw, int(im.height * colw / im.width)), Image.LANCZOS)
        if a > 0:
            im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
            L.alpha_composite(im, (x0 + (colw - im.width) // 2, y))
        y += im.height + gap + 14
    return L


def phone_card(name="home", height=640):
    """A whole screenshot as a small phone (used on end cards, also by the other reel engines)."""
    scr = screen(name); w = int(height * scr.width / scr.height)
    view = scr.resize((w, height), Image.LANCZOS)
    m = Image.new("L", (w, height), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, height - 1], 30, fill=255)
    out = Image.new("RGBA", (w + 20, height + 20), (0, 0, 0, 0)); d = ImageDraw.Draw(out)
    d.rounded_rectangle([0, 0, out.width - 1, out.height - 1], 38, fill=(8, 8, 14, 255), outline=(232, 222, 200, 235), width=3)
    out.paste(view, (10, 10), m)
    return out


# ----------------------------------------------------------------- the reel
def build(seed, out, ep_id=None):
    import voice
    mock = os.environ.get("TOUR_MOCK") == "1"
    ep = pick_episode(seed, ep_id)
    log = json.load(open(LOG)) if os.path.exists(LOG) else []
    variant = sum(1 for e in log if e.get("tour") == ep["id"])
    number = len(log) + 1
    lines = script_for(ep, variant, mock)
    hook_txt = ([ep["hook"]] + ep.get("hook_alt", []))[variant % (1 + len(ep.get("hook_alt", [])))]
    print("Tour reel:", ep["id"], "|", hook_txt, flush=True)
    NS = len(ep["scenes"]); KINDS = ["hook"] + ["scene"] * NS + ["question", "end"]

    # ---- voice (one engine for the whole reel)
    styles = ["confident, a little intriguing"] + ["friendly product guide, clear and quick"] * NS + ["curious, direct to the viewer", "warm invitation"]
    voice.reset("local" if mock else None)
    A = voice.say_many(lines, speed=1.14, styles=styles, one_take=False)
    durs = [max(len(a) / SR + 0.35, 2.0) for a in A]
    durs[0] = max(durs[0], 3.0); durs[-2] += 1.1; durs[-1] = max(durs[-1] + 0.6, 3.4)
    starts = list(np.cumsum([0.0] + durs[:-1])); total = float(sum(durs)) + 0.3
    n = int(SR * (total + 0.5)); vo = np.zeros(n, np.float32); fx = np.zeros(n, np.float32)

    def put(buf, a, at, g=1.0):
        i = int(at * SR)
        if i >= n or i < 0: return
        j = min(n, i + len(a)); buf[i:j] += a[: j - i] * g

    # shots of every block: hook and question reuse a screen; scenes come from the episode
    def shots_of(k):
        if KINDS[k] == "hook":
            return [dict(ep["hook_shot"])]
        if KINDS[k] == "scene":
            return [dict(s) for s in ep["scenes"][k - 1]["shots"]]
        if KINDS[k] == "question":
            return [dict(ep["question"].get("shot") or ep["scenes"][-1]["shots"][-1])]
        return []
    SH = [shots_of(k) for k in range(len(KINDS))]
    for k, a in enumerate(A):
        put(vo, a, starts[k] + 0.18)
        if k: put(fx, R.shimmer([659.3, 784.0, 880.0, 587.3][k % 4]), starts[k] - 0.05, 0.45)
        for sh in SH[k]:
            if sh.get("tap"):
                at = starts[k] + durs[k] * (sh.get("at", 0.0) + (1 - sh.get("at", 0.0)) * 0.72)
                put(fx, R.pop(), at + 0.12, 0.7)
            if sh.get("at"):
                put(fx, R.tick(True), starts[k] + durs[k] * sh["at"], 0.6)
    put(fx, R.soft_hit(), 0.05, 0.6)
    put(fx, R.ding(), starts[-2] + 0.15, 0.5)
    music = HY.beat(total)[:n]
    venv = np.convolve((np.abs(vo) > 0.01).astype(np.float32), np.ones(3000) / 3000, "same")
    mix = HY.dehiss(np.tanh((vo * 1.15 + fx + music * (0.36 - 0.2 * np.clip(venv * 3, 0, 1))) * 1.1) * 0.92)
    wav = out.replace(".mp4", "_tour.wav"); sf.write(wav, mix, SR)
    hop = SR // FPS
    env = np.array([np.sqrt(np.mean(vo[i * hop:(i + 1) * hop] ** 2)) for i in range(int(total * FPS) + 2)])
    env = np.clip(env / (np.percentile(env[env > 0.004], 85) + 1e-6), 0, 1) if (env > 0.004).any() else env
    words = []
    for k, a in enumerate(A):
        for ts, w in voice.align(a, lines[k]):
            words.append((k, starts[k] + 0.18 + ts, w))

    # ---- static pieces
    stage = SCI.Stage()
    _lp = os.path.join(HERE, "assets", "logo_h_white.png")
    logo = Image.open(_lp if os.path.exists(_lp) else os.path.join(HERE, "assets", "logo_h.png")).convert("RGBA")
    logo = logo.crop(logo.getbbox())
    badge_img = badge(number)
    labels = [left_label(hook_txt, size=66)] + [left_label(s["label"]) for s in ep["scenes"]] + [None, None]
    q_label = HY.fit_phrase(ep["question"]["label"].upper().split(), 88, 780, 2, 52)
    q_pill = R.pill("COMMENT IT BELOW", 44, IVORY, fg=INK, padx=40, pady=16)
    end_phone = phone_card("home", 640)
    MOODS = ["excited"] + ["happy", "thinking", "determined", "star", "happy", "thinking"][:NS] + ["surprised", "excited"]

    def camera(k, lt):
        """(screen name, rect, crossfade partner or None, shot dict, progress inside the shot) at local time lt."""
        shots = SH[k]; p = clamp(lt / max(0.1, durs[k]))
        i = max(j for j, s in enumerate(shots) if s.get("at", 0.0) <= p + 1e-6)
        sh = shots[i]; t0 = sh.get("at", 0.0) * durs[k]
        t1 = (shots[i + 1]["at"] if i + 1 < len(shots) else 1.0) * durs[k]
        st = lt - t0; sp = clamp(st / max(0.1, t1 - t0))
        size = screen(sh["screen"]).size
        foc = rect_of(sh.get("focus"), size)
        if KINDS[k] == "hook":                                    # whole phone first, then push into the screen
            z = eio((lt - 0.7) / 0.85)
            rect = lerp_rect(rect_of(None, size), foc, z)
        else:
            same = i > 0 and shots[i - 1]["screen"] != sh["screen"] and shots[i - 1].get("focus") == sh.get("focus")
            rect = foc if same else lerp_rect(widen(foc, size), foc, eo(st / 0.7))
            if sh.get("pan"):
                rect = lerp_rect(rect, rect_of(sh["pan"], size), eio((sp - 0.38) / 0.5))
        prev = None
        if i > 0 and st < 0.28:                                   # short crossfade from the previous shot
            ps = shots[i - 1]; prev = (ps["screen"], rect_of(ps.get("pan") or ps.get("focus"), screen(ps["screen"]).size), st / 0.28)
        return sh, rect, prev, st, sp, t1 - t0

    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-i", wav, "-shortest"] + HY.enc_args(out), stdin=subprocess.PIPE)
    still = {}
    for fi in range(int(total * FPS)):
        t = fi / FPS
        k = min(len(starts) - 1, int(np.searchsorted(starts, t, side="right") - 1)); lt = t - starts[k]
        kind = KINDS[k]; mouth = float(env[fi]) if fi < len(env) else 0.0
        fr = stage.frame(t)
        if kind != "end":
            sh, rect, prev, st, sp, sdur = camera(k, lt)
            key = (sh["screen"],) + tuple(round(v, 1) for v in rect)
            moving = key != still.get("key")
            if moving or "img" not in still:
                im, s, pad = card(sh["screen"], rect, fast=True)
                nxt = camera(k, min(durs[k], lt + 1 / FPS))[1] if lt + 1 / FPS < durs[k] else rect
                if tuple(round(v, 1) for v in nxt) == tuple(round(v, 1) for v in rect):   # camera settles: sharp version
                    im, s, pad = card(sh["screen"], rect, fast=False)
                still = {"key": key, "img": im, "s": s, "pad": pad}
            im, s, pad = still["img"], still["s"], still["pad"]
            cw, chh = im.width, im.height
            cx0, cy0 = (W - cw) // 2, CARD_TOP
            z = clamp((cw - 420) / (BOX_W - 420 + 24))            # 0 = whole phone, 1 = pushed in
            # Vektor: stands beside the phone, then perches behind the top-right corner of the screen
            zz = eio((z - 0.05) / 0.45)
            vk_cx = 900 * (1 - zz) + (cx0 + cw - 92) * zz; vk_scale = 0.40 - 0.15 * zz
            vk_bottom = (CARD_TOP + BOX_H) * (1 - zz) + (cy0 + 72) * zz
            stage.vektor(fr, t, mouth, MOODS[k], vk_cx, vk_bottom, vk_scale, look=(-0.55, 0.35))
            fr.alpha_composite(shadow(cw, chh), (cx0 - 120, cy0 - 120))
            if prev:
                pim, _, _ = card(prev[0], prev[1], fast=True)
                if pim.size != im.size: pim = pim.resize(im.size, Image.BILINEAR)
                fr.alpha_composite(Image.blend(pim, im, eo(prev[2])), (cx0, cy0))
            else:
                fr.alpha_composite(im, (cx0, cy0))
            origin = (cx0 + pad, cy0 + pad)
            scr_size = screen(sh["screen"]).size
            if kind != "question":
                if sh.get("box"):
                    highlight(fr, rect_of(sh["box"], scr_size), rect, s, origin, clamp((st - 0.75) / 0.35) if kind != "hook" else clamp((lt - 1.7) / 0.35), t)
                if sh.get("tap"):
                    tp = (sh["tap"][0] * scr_size[0], sh["tap"][1] * scr_size[1])
                    tap_mark(fr, tp, rect, s, origin, (st - sdur * 0.72) / 0.75)
            # header: series badge + big label (left column)
            fr.alpha_composite(badge_img, (PAD_X, BADGE_Y - badge_img.height // 2))
            if kind == "question":
                dim = Image.new("RGBA", (cw, chh), (6, 6, 12, int(205 * eo(lt / 0.35))))
                mk = Image.new("L", (cw, chh), 0); ImageDraw.Draw(mk).rounded_rectangle([0, 0, cw - 1, chh - 1], 40, fill=255)
                fr.paste(Image.alpha_composite(fr.crop((cx0, cy0, cx0 + cw, cy0 + chh)), dim), (cx0, cy0), mk)
                mid = cy0 + chh // 2
                R.paste_center(fr, SCI.glow(q_label, GOLD, 18, 80), W / 2, mid - 70, eob(lt / 0.4))
                R.paste_center(fr, q_pill, W / 2, mid + q_label.height // 2 + 20, 1.0, eo((lt - 0.5) / 0.4))
                d = ImageDraw.Draw(fr)
                for j in range(3):                                # three little comment bubbles popping up
                    a = eob((lt - 0.9 - 0.25 * j) / 0.35)
                    if a > 0:
                        bx, by = W / 2 - 150 + j * 150, mid + q_label.height // 2 + 150
                        r = 34 * a
                        d.rounded_rectangle([bx - r * 1.5, by - r, bx + r * 1.5, by + r], int(r * 0.7), fill=IVORY + (235,))
                        for m_ in (-1, 0, 1):
                            d.ellipse([bx + m_ * r * 0.7 - 6, by - 6, bx + m_ * r * 0.7 + 6, by + 6], fill=INK + (255,))
                R.paste_center(fr, left_label("Your turn", size=58), PAD_X + 365, LABEL_Y + 50, 1.0, eo(lt / 0.3))
            else:
                lab = labels[k]
                a = eo(lt / 0.3); fade = 1.0 if lt < durs[k] - 0.2 or kind == "hook" else max(0.0, (durs[k] - lt) / 0.2)
                li = lab.copy(); li.putalpha(li.getchannel("A").point(lambda v: int(v * a * fade)))
                fr.alpha_composite(li, (PAD_X - 20 + int(30 * (1 - a)), LABEL_Y - 10))
        else:
            layer = end_layer(clamp(lt / max(0.1, durs[k] - 0.5)), t, logo, end_phone)
            enter = eo(lt / 0.45); cy = 960
            stage.vektor(fr, t, mouth, "excited", 860, cy - layer.height // 2 + 26, 0.30, look=(-0.3, 0.2))
            R.paste_center(fr, layer, W / 2, cy + (1 - enter) * 60, 1.0, enter)
        # kinetic subtitles (the words being spoken)
        cur = [(ts, w) for si, ts, w in words if si == k and ts <= t]
        if cur and kind != "end":
            idx = len(cur) - 1; s0 = (idx // 3) * 3
            ph = HY.phrase_img([w for _, w in cur[s0:idx + 1]], t - cur[-1][0], 66, 1000)
            R.paste_center(fr, HY.band_img(ph.height + 60), W / 2, SUB_Y)
            R.paste_center(fr, ph, W / 2, SUB_Y)
        if lt < 0.25 and k:                                       # soft dip between blocks
            fr = Image.blend(fr, Image.new("RGBA", (W, H), (4, 4, 10, 255)), 0.45 * (1 - lt / 0.25))
        fr.alpha_composite(HY.vignette())
        proc.stdin.write(fr.convert("RGB").tobytes())
    proc.stdin.close(); proc.wait(); os.remove(wav)

    # ---- caption
    rng = random.Random(seed)
    import hooks, brand
    cap_hook = hook_txt + " 📱"
    if not hooks.is_fresh(cap_hook):                             # a recent reel opened the same way: use another line
        cap_hook = next((h for h in brand.explainer_hook("tour", ep["topic"], ep.get("hook_alt", []), seed) if hooks.is_fresh(h)), cap_hook)
    cap = (f"{cap_hook}\nInside StreakChess #{number:02d} · {ep['topic']}\n\n"
           + "\n".join("✅ " + x for x in ep.get("takeaways", [])) + "\n\n"
           f"{ep['question']['caption']}\n\n"
           + brand.product_block(seed, bridge=False) + "\n\n"
           + " ".join(R.hashtags(rng, "chessapp")))
    review = {}
    if not mock and os.environ.get("REVIEWER", "on") != "off" and os.environ.get("GEMINI_API_KEY"):
        import reviewer
        try:
            new_cap, review = reviewer.review_video(out, {"title": f"App tour: {ep['topic']}"}, cap, kind="tour")
            # the first line stays ours: every tour hook is written and checked by hand (the reviewer's rewrites
            # drift into vague benefit claims); the review is used for the score and the quality gate only
            cap = cap_hook + "\n" + new_cap.split("\n", 1)[1] if "\n" in new_cap else cap
        except reviewer.RejectReel:
            raise
        except Exception as e:
            print("tour review skipped:", str(e)[:150], flush=True)
    open(out.replace(".mp4", ".txt"), "w").write(cap)
    if not mock and os.environ.get("DRY_RUN") != "true":
        log.append({"tour": ep["id"], "variant": variant}); json.dump(log[-300:], open(LOG, "w"), indent=0)
    return dict(mode="tour", puzzle=None, level=None, rating=None, hook=cap_hook, sans=[], reveal=None, ab=None, side=None,
                story=f"App tour: {ep['topic']}", tour=ep["id"], question=ep["question"]["caption"], duration=round(total, 1),
                thumb_offset_ms=500, review_score=review.get("overall"))


if __name__ == "__main__":
    print(json.dumps(build(int(sys.argv[1]), sys.argv[2], ep_id=sys.argv[3] if len(sys.argv) > 3 else None), indent=1))
