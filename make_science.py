"""'Chess science' explainer reel (the sports-science explainer format, in our colours).

Structure (about 55 s): a relatable moment -> "and no, it's not because..." (myth) -> the mechanism -> a statistic
drawn as a grid/dots -> the real study -> the result as a bar chart with a big number -> the method (on a real
board) -> the takeaway -> "send this to the friend who..." (phone mock-up) -> app card.

Every number comes from assets/science/facts.json (verified studies). Visuals are drawn in code: neon-style line
art on night blue with champagne gold, ivory, cool blue, crimson (bad) and green (good); Vektor reacts in every
scene; kinetic subtitles follow the voice. No AI images, so it is cheap and never off-model.

python make_science.py <seed> out.mp4 [fact_id]       (voice: Gemini if GEMINI_API_KEY, else local)
SCIENCE_MOCK=1 ...                                      (offline: local voice, no Gemini text)
"""
import json, math, os, random, re, subprocess, sys
import numpy as np
import chess
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import make_reel as R
import make_hype as HY

HERE = os.path.dirname(os.path.abspath(__file__))
FACTS = os.path.join(HERE, "assets", "science", "facts.json")
LOG = os.path.join(HERE, "science_log.json")
W, H, FPS, SR = HY.W, HY.H, HY.FPS, HY.SR
GOLD, IVORY, INK = HY.YEL, HY.WHITE, HY.INK
BLUE, RED, GREEN, VIOLET = (122, 170, 226), (206, 92, 92), (110, 188, 140), (156, 130, 224)
NIGHT0, NIGHT1 = (14, 16, 34), (5, 6, 14)
TOP_Y, VIS_CY, SUB_Y = 372, 950, 1405          # big label / visual centre / subtitles (inside the phone safe zone)
F_BOLD = os.path.join(HERE, "fonts", "InterDisplay-Bold.otf")
F_SEMI = os.path.join(HERE, "fonts", "Inter-SemiBold.otf")
eo, eob, eio, clamp = R.ease_out, R.ease_out_back, R.ease_in_out, R.clamp


# ----------------------------------------------------------------- facts
def facts():
    return json.load(open(FACTS))["facts"]


def pick_fact(seed, fact_id=None):
    """Rotate through the facts; the least recently used first (every fact runs before any repeats)."""
    fs = facts()
    if fact_id:
        return next(f for f in fs if f["id"] == fact_id)
    log = json.load(open(LOG)) if os.path.exists(LOG) else []
    used = [e.get("fact") for e in log]
    never = [f for f in fs if f["id"] not in used]
    if never:
        return random.Random(seed).choice(never)
    last = {f["id"]: max(i for i, u in enumerate(used) if u == f["id"]) for f in fs}
    return min(fs, key=lambda f: last[f["id"]])


SCENES = ["moment", "myth", "mechanism", "stat", "study", "result", "method", "takeaway", "share", "end"]
END_LINE = "Train your calculation free, every day, on StreakChess. Link in bio."


def script_for(fact, variant=0, mock=False):
    """Narration per scene. The canonical lines live in facts.json; on repeats Gemini writes a fresh variant that
    keeps every number (validated) so the same study never sounds the same twice."""
    lines = {k: fact[k]["narration"] for k in SCENES[:-2]}
    lines["share"] = fact["share"] + "."
    lines["end"] = END_LINE
    if variant and not mock and os.environ.get("GEMINI_API_KEY"):
        try:
            import reviewer
            res = reviewer._ask([{"text": f"""You write voice-over for a premium chess explainer reel (chess players of every age).
Rewrite these narration lines so they sound NEW (different words, same meaning, same order, same facts).
HARD RULES: keep every number exactly (written as words, like now); do not add any number, study, name or claim
that is not in the original; each line 8-22 words, spoken English, vivid and concrete, no hype words.
Original lines (JSON): {json.dumps({k: lines[k] for k in SCENES[:-2]}, ensure_ascii=False)}
Return JSON with the same keys."""}], 0.8)
            ok = True
            for k in SCENES[:-2]:
                new = (res.get(k) or "").strip()
                nums_old = set(re.findall(r"\d+", lines[k])); nums_new = set(re.findall(r"\d+", new))
                if not new or not 6 <= len(new.split()) <= 26 or nums_new != nums_old:
                    ok = False; break
            if ok:
                for k in SCENES[:-2]:
                    lines[k] = res[k].strip()
                print("science: narration variant", variant, flush=True)
        except Exception as e:
            print("science: variant skipped:", str(e)[:120], flush=True)
    return lines


# ----------------------------------------------------------------- drawing helpers
def font(size, bold=True):
    return ImageFont.truetype(F_BOLD if bold else F_SEMI, size)


def label(txt, size=64, color=IVORY):
    return HY.fit_phrase(txt.split(), size, 940, 2, 40) if len(txt.split()) > 1 else HY.word_img(txt, size, color, 0)


def big_label(txt, color=GOLD, size=84):
    """One or two lines of big display type."""
    return HY.fit_phrase(txt.upper().split(), size, 960, 2, 48)


def glow(im, color, radius=18, alpha=140):
    """Neon glow: the alpha of im blurred and tinted, under the image."""
    a = im.getchannel("A")
    g = Image.new("RGBA", im.size, color + (0,)); g.putalpha(a.point(lambda v: int(v * alpha / 255)))
    g = g.filter(ImageFilter.GaussianBlur(radius))
    out = Image.new("RGBA", im.size, (0, 0, 0, 0)); out.alpha_composite(g); out.alpha_composite(im)
    return out


def _bg_static():
    y = np.linspace(0, 1, H)[:, None, None]
    arr = (np.array(NIGHT0) * (1 - y) + np.array(NIGHT1) * y) * np.ones((1, W, 3))
    im = Image.fromarray(arr.astype(np.uint8)).convert("RGBA")
    d = ImageDraw.Draw(im)
    for x in range(0, W, 90):                                   # faint perspective grid (neon-field feel)
        d.line([(x, 0), (x, H)], fill=(255, 255, 255, 9), width=1)
    for yy in range(0, H, 90):
        d.line([(0, yy), (W, yy)], fill=(255, 255, 255, 9), width=1)
    gl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(gl).ellipse([W * 0.1, H * 0.3, W * 0.9, H * 0.75], fill=GOLD + (26,))
    im.alpha_composite(gl.filter(ImageFilter.GaussianBlur(160)))
    return im


class Stage:
    """Background with drifting particles + the mascot, shared by every scene."""

    def __init__(self):
        self.base = _bg_static()
        rng = np.random.RandomState(5)
        self.dust = [(rng.uniform(0, W), rng.uniform(0, H), rng.uniform(1.5, 4), rng.uniform(6, 22)) for _ in range(70)]
        from mascot_rig import Mascot
        self.mascot = Mascot()

    def frame(self, t):
        im = self.base.copy(); d = ImageDraw.Draw(im)
        for x, y, r, sp in self.dust:
            yy = (y - t * sp) % H; xx = x + 10 * math.sin(t * 0.6 + y)
            d.ellipse([xx - r, yy - r, xx + r, yy + r], fill=(232, 204, 150, 42))
        return im

    def vektor(self, fr, t, mouth, mood, cx, bottom, scale=0.42, look=(0.3, 0.1), bounce=0.0):
        mi = self.mascot.render(t, mouth=mouth, mood=mood, look=look, bounce=bounce)
        mi = mi.resize((int(mi.width * scale), int(mi.height * scale)), Image.BILINEAR)
        sh = Image.new("RGBA", (int(mi.width * 0.7), 40), (0, 0, 0, 0))
        ImageDraw.Draw(sh).ellipse([0, 0, sh.width - 1, 39], fill=(0, 0, 0, 120))
        fr.alpha_composite(sh.filter(ImageFilter.GaussianBlur(10)), (int(cx - sh.width / 2), int(bottom - 20)))
        fr.alpha_composite(mi, (int(cx - mi.width / 2), int(bottom - mi.height)))


# ----------------------------------------------------------------- visuals (each returns an RGBA layer, centred later)
def board_layer(board, flip, p, effect="", sol=None, cands=None, t=0.0):
    """A real board card with an effect: flash (fades to outline), blunder (red X on the moved piece),
    two_solutions (gold short line vs red long line), chunks (groups circled), glance (plain)."""
    im = R.draw_board(board, flip, ())
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    if effect == "flash":
        k = clamp((p - 0.45) / 0.3)                             # after 45%: the pieces fade out, the grid stays
        if k > 0:
            blank = R.draw_board(chess.Board(None), flip, ())
            im = Image.blend(im, blank, k)
    elif effect == "blunder" and sol is not None:
        q = clamp((p - 0.25) / 0.35)
        if q > 0:
            import lesson_anim as LA
            LA.arrow_partial(im, sol.from_square, sol.to_square, flip, RED, q)
        if p > 0.65:
            x, y = R.sq_xy(sol.to_square, flip); s = int(R.SQ * 0.75 * eob((p - 0.65) / 0.2))
            cx, cy = x + R.SQ / 2, y + R.SQ / 2
            d.line([(cx - s / 2, cy - s / 2), (cx + s / 2, cy + s / 2)], fill=RED + (255,), width=16)
            d.line([(cx - s / 2, cy + s / 2), (cx + s / 2, cy - s / 2)], fill=RED + (255,), width=16)
    elif effect == "two_solutions" and cands:
        import lesson_anim as LA
        for k, (m, col) in enumerate(zip(cands[:2], (RED, GOLD))):
            q = clamp((p - 0.15 - 0.35 * k) / 0.3)
            if q > 0:
                LA.arrow_partial(im, m.from_square, m.to_square, flip, col, q)
    elif effect == "chunks":
        groups = {}
        for sq, pc in board.piece_map().items():
            groups.setdefault((pc.color, chess.square_file(sq) // 4), []).append(sq)
        for k, sqs in enumerate(groups.values()):
            q = clamp((p - 0.1 * k) / 0.3)
            if q <= 0: continue
            xs = [R.sq_xy(s, flip)[0] for s in sqs]; ys = [R.sq_xy(s, flip)[1] for s in sqs]
            d.rounded_rectangle([min(xs) - 6, min(ys) - 6, max(xs) + R.SQ + 6, max(ys) + R.SQ + 6], 24,
                                outline=GOLD + (int(220 * q),), width=6)
    elif effect == "eyes" and cands:
        m = cands[0]
        for sq in (m.from_square, m.to_square):
            x, y = R.sq_xy(sq, flip); a = int(120 + 100 * abs(math.sin(t * 4)))
            d.rounded_rectangle([x + 4, y + 4, x + R.SQ - 4, y + R.SQ - 4], 16, outline=RED + (a,), width=8)
    elif effect == "method" and cands:
        import lesson_anim as LA
        for k, m in enumerate(cands[:4]):
            q = clamp((p - 0.15 - 0.18 * k) / 0.3)
            if q > 0:
                LA.arrow_partial(im, m.from_square, m.to_square, flip, (GOLD, BLUE, VIOLET, GREEN)[k % 4], q, 18)
    im.alpha_composite(ov)
    c = R.card(im)
    return glow(c, GOLD, 26, 90)


def grid_layer(total, a, b, p, label_a, label_b, title):
    """Unit grid (like the 25 jerseys): total units, a highlighted gold, b crimson; counts appear one by one."""
    cols = 5 if total <= 25 else 10
    rows = math.ceil(total / cols)
    cell = 150 if cols == 5 else 84
    pw, ph = cols * cell, rows * cell
    L = Image.new("RGBA", (pw + 80, ph + 200), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    tt = R.pill(title, 34, INK, fg=GOLD, padx=28, pady=10); L.alpha_composite(tt, ((L.width - tt.width) // 2, 0))
    pawn = R.piece_img(chess.Piece(chess.PAWN, chess.WHITE), int(cell * 0.78))
    shown = int(total * clamp(p / 0.45))
    na = int(a * clamp((p - 0.45) / 0.35)); nb = int(b * clamp((p - 0.45) / 0.35))
    for i in range(shown):
        r, c = divmod(i, cols)
        x, y = 40 + c * cell, 110 + r * cell
        col = GOLD if i < na else (RED if i >= total - nb else (255, 255, 255))
        al = 255 if (i < na or i >= total - nb) else 70
        ic = pawn.copy()
        tint = Image.new("RGBA", ic.size, col + (255,)); tint.putalpha(ic.getchannel("A").point(lambda v: int(v * al / 255)))
        L.alpha_composite(tint, (x + (cell - ic.width) // 2, y + (cell - ic.height) // 2))
    y = 120 + rows * cell
    if label_a:
        la = R.pill(f"{a}  {label_a}", 34, GOLD, fg=INK, padx=24, pady=10); L.alpha_composite(la, (40, y))
    if label_b:
        lb = R.pill(f"{b}  {label_b}", 34, INK, fg=RED, padx=24, pady=10); L.alpha_composite(lb, (L.width - lb.width - 40, y))
    return L


def dots_layer(total, p, title, label, split=None, split_labels=None):
    """Dot field (like '942 footballers'): dots fill in, optionally split into two coloured halves."""
    cols = 25 if total >= 200 else (16 if total >= 60 else 8)
    rows = math.ceil(total / cols)
    cell = 880 // cols
    pw, ph = cols * cell, rows * cell
    L = Image.new("RGBA", (pw + 80, ph + 220), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    tt = R.pill(title, 34, INK, fg=GOLD, padx=28, pady=10); L.alpha_composite(tt, ((L.width - tt.width) // 2, 0))
    shown = int(total * clamp(p / 0.6))
    q = clamp((p - 0.65) / 0.3) if split else 0
    r = max(3, cell * 0.33)
    for i in range(shown):
        rr, c = divmod(i, cols)
        x, y = 40 + c * cell + cell / 2, 110 + rr * cell + cell / 2
        col = IVORY
        if split and q > 0:
            col = GOLD if i < split[0] else BLUE
        d.ellipse([x - r, y - r, x + r, y + r], fill=col + (235,))
    y = 125 + rows * cell
    lab = R.pill(label, 34, INK, fg=IVORY, padx=24, pady=10); L.alpha_composite(lab, ((L.width - lab.width) // 2, y))
    if split and split_labels and q > 0:
        la = R.pill(f"{split[0]} · {split_labels[0]}", 30, GOLD, fg=INK, padx=20, pady=8)
        lb = R.pill(f"{split[1]} · {split_labels[1]}", 30, INK, fg=BLUE, padx=20, pady=8)
        L.alpha_composite(la, (40, y + 70)); L.alpha_composite(lb, (L.width - lb.width - 40, y + 70))
    return glow(L, GOLD, 10, 40)


def bars_layer(labels, values, vmax, p, title, big):
    """Two or three bars growing, then the big number pops."""
    n = len(labels); bw = 230 if n < 3 else 190; gap = 80 if n < 3 else 50
    vmax = min(vmax, max(values) * 1.6) if max(values) > 0 else vmax     # tiny values still make tall bars
    pw = n * bw + (n - 1) * gap
    L = Image.new("RGBA", (pw + 200, 800), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    tt = R.pill(title, 34, INK, fg=GOLD, padx=28, pady=10); L.alpha_composite(tt, ((L.width - tt.width) // 2, 0))
    base_y, maxh = 600, 440
    d.line([(60, base_y), (L.width - 60, base_y)], fill=(255, 255, 255, 60), width=3)
    for k, (lab, v) in enumerate(zip(labels, values)):
        q = eo((p - 0.1 - 0.25 * k) / 0.45)
        h = int(maxh * v / max(1, vmax) * q)
        x0 = 100 + k * (bw + gap)
        col = (GOLD if k == n - 1 else (120, 124, 150))
        if q > 0:
            d.rounded_rectangle([x0, base_y - h, x0 + bw, base_y], 18, fill=col + (255,))
            if k == n - 1:
                g = Image.new("RGBA", L.size, (0, 0, 0, 0))
                ImageDraw.Draw(g).rounded_rectangle([x0 - 10, base_y - h - 10, x0 + bw + 10, base_y + 10], 24, fill=GOLD + (90,))
                L.alpha_composite(g.filter(ImageFilter.GaussianBlur(18)))
                d.rounded_rectangle([x0, base_y - h, x0 + bw, base_y], 18, fill=col + (255,))
            vt = R.text_img(f"{v:,}" if isinstance(v, int) else str(v), 38, IVORY)
            L.alpha_composite(vt, (x0 + (bw - vt.width) // 2, base_y - h - 50))
        lt = R.text_img(lab, 28, IVORY if k == n - 1 else (170, 174, 200), maxw=bw + 40)
        L.alpha_composite(lt, (x0 + (bw - lt.width) // 2, base_y + 16))
    bq = eob((p - 0.72) / 0.28)
    if bq > 0:
        bi = HY.word_img(big, 110, GOLD, 0)
        bi = glow(bi, GOLD, 22, 120)
        bi = bi.resize((max(1, int(bi.width * bq)), max(1, int(bi.height * bq))), Image.BILINEAR)
        L.alpha_composite(bi, ((L.width - bi.width) // 2, 700 - bi.height // 2))
    return L


def timeline_layer(points, p, title, big):
    """Curve of performance by age: a line draws itself, a marker rides it, the peak lights up."""
    L = Image.new("RGBA", (980, 700), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    tt = R.pill(title, 34, INK, fg=GOLD, padx=28, pady=10); L.alpha_composite(tt, ((L.width - tt.width) // 2, 0))
    x0, x1, y0, y1 = 90, 900, 520, 150
    ages = [a for a, _ in points]; a0, a1 = min(ages), max(ages)
    d.line([(x0, y0), (x1, y0)], fill=(255, 255, 255, 70), width=3)
    for a in range(a0, a1 + 1, 10):
        x = x0 + (x1 - x0) * (a - a0) / (a1 - a0)
        d.line([(x, y0), (x, y0 + 12)], fill=(255, 255, 255, 120), width=3)
        tx = R.text_img(str(a), 26, (190, 194, 220)); L.alpha_composite(tx, (int(x - tx.width / 2), y0 + 20))
    pts = [(x0 + (x1 - x0) * (a - a0) / (a1 - a0), y0 - (y0 - y1) * v / 100) for a, v in points]
    q = clamp(p / 0.75); n = max(2, int(len(pts) * q) + 1)
    seg = pts[:n]
    if len(seg) >= 2:
        gl = Image.new("RGBA", L.size, (0, 0, 0, 0)); ImageDraw.Draw(gl).line(seg, fill=GOLD + (140,), width=22, joint="curve")
        L.alpha_composite(gl.filter(ImageFilter.GaussianBlur(14)))
        d.line(seg, fill=GOLD + (255,), width=8, joint="curve")
        mx, my = seg[-1]; d.ellipse([mx - 14, my - 14, mx + 14, my + 14], fill=IVORY + (255,))
    if p > 0.8:
        peak = max(pts, key=lambda t_: -t_[1]); s = eob((p - 0.8) / 0.2)
        d.ellipse([peak[0] - 22 * s, peak[1] - 22 * s, peak[0] + 22 * s, peak[1] + 22 * s], outline=GOLD + (255,), width=5)
        bi = glow(HY.word_img(big, 72, GOLD, 0), GOLD, 16, 110)
        L.alpha_composite(bi, (int(min(max(peak[0] - bi.width / 2, 0), L.width - bi.width)), int(peak[1] - 120)))
    return L


def calendar_layer(total, p, title, big):
    """Calendar of days ticking off (habit / one pattern a day)."""
    cols = 7 if total <= 70 else 20
    rows = math.ceil(total / cols)
    cell = 110 if cols == 7 else 44
    L = Image.new("RGBA", (cols * cell + 80, rows * cell + 240), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    tt = R.pill(title, 34, INK, fg=GOLD, padx=28, pady=10); L.alpha_composite(tt, ((L.width - tt.width) // 2, 0))
    shown = int(total * clamp(p / 0.7))
    for i in range(total):
        r, c = divmod(i, cols)
        x, y = 40 + c * cell, 100 + r * cell
        on = i < shown
        d.rounded_rectangle([x + 4, y + 4, x + cell - 4, y + cell - 4], 10 if cols == 7 else 6,
                            fill=(GOLD + (255,)) if on else (255, 255, 255, 28))
        if on and cols == 7:
            d.line([(x + cell * 0.3, y + cell * 0.52), (x + cell * 0.45, y + cell * 0.68), (x + cell * 0.72, y + cell * 0.34)],
                   fill=INK + (255,), width=7)
    bq = eob((p - 0.75) / 0.25)
    if bq > 0:
        bi = glow(HY.word_img(big, 96, GOLD, 0), GOLD, 20, 120)
        bi = bi.resize((max(1, int(bi.width * bq)), max(1, int(bi.height * bq))), Image.BILINEAR)
        L.alpha_composite(bi, ((L.width - bi.width) // 2, L.height - 130 - bi.height // 2))
    return L


def clock_layer(p, t, drain=True, games=True):
    """A chess clock ring draining to red (+ a stack of 'game' cards piling up)."""
    L = Image.new("RGBA", (900, 620), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    cx, cy, r = 450, 300, 220
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(10, 10, 20, 230), outline=(255, 255, 255, 40), width=4)
    left = 1 - clamp(p) if drain else 1
    col = RED if left < 0.3 else GOLD
    d.arc([cx - r + 16, cy - r + 16, cx + r - 16, cy + r - 16], -90, -90 + 360 * left, fill=col + (255,), width=16)
    secs = int(30 * left) if drain else 30
    tx = HY.word_img(f"0:{secs:02d}", 120, IVORY if left > 0.3 else RED, 0)
    L.alpha_composite(tx, (cx - tx.width // 2, cy - tx.height // 2))
    if games:
        n = int(6 * clamp(p / 0.8))
        for k in range(n):
            x = 60 + k * 130; y = 540 - 20 * (k % 2)
            d.rounded_rectangle([x, y, x + 110, y + 60], 12, fill=(255, 255, 255, 30), outline=BLUE + (200,), width=3)
            g = R.text_img("GAME", 22, BLUE); L.alpha_composite(g, (x + 55 - g.width // 2, y + 18))
    return glow(L, col, 18, 70)


def brain_layer(p, t, mode="two"):
    """Stylised brain outline; regions light up (front/parietal = gold 'recall', temporal = blue 'figure out')."""
    L = Image.new("RGBA", (940, 640), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    cx, cy = 470, 300
    body = [cx - 300, cy - 190, cx + 300, cy + 170]
    gl = Image.new("RGBA", L.size, (0, 0, 0, 0)); ImageDraw.Draw(gl).ellipse(body, outline=IVORY + (140,), width=26)
    L.alpha_composite(gl.filter(ImageFilter.GaussianBlur(16)))
    d.ellipse(body, outline=IVORY + (255,), width=7)
    for k in range(5):                                           # folds
        y = cy - 120 + k * 60
        d.arc([cx - 240 + 20 * k, y - 60, cx + 240 - 20 * k, y + 60], 190, 350, fill=IVORY + (110,), width=4)
    qa = clamp((p - 0.15) / 0.4); qb = clamp((p - 0.5) / 0.4)
    def region(box, col, q, name):
        if q <= 0: return
        g = Image.new("RGBA", L.size, (0, 0, 0, 0)); ImageDraw.Draw(g).ellipse(box, fill=col + (int(170 * q),))
        L.alpha_composite(g.filter(ImageFilter.GaussianBlur(28)))
        lb = R.pill(name, 28, INK, fg=col, padx=18, pady=8)
        L.alpha_composite(lb, (int((box[0] + box[2]) / 2 - lb.width / 2), int(box[3] + 8)))
    if mode in ("two", "regions"):
        region([cx - 60, cy - 150, cx + 260, cy + 40], GOLD, qa, "RECALL · PATTERNS")
        region([cx - 250, cy - 20, cx - 20, cy + 150], BLUE, qb, "FIGURE OUT · NEW INFO")
    elif mode == "pull":                                          # memory pulled out: arrow leaving the brain
        region([cx - 120, cy - 120, cx + 160, cy + 80], GOLD, qa, "MEMORY")
        if qb > 0:
            import lesson_anim as LA
            d.line([(cx + 160, cy), (cx + 160 + 200 * qb, cy)], fill=GOLD + (255,), width=12)
            d.polygon([(cx + 160 + 200 * qb, cy - 26), (cx + 200 + 200 * qb, cy), (cx + 160 + 200 * qb, cy + 26)], fill=GOLD + (255,))
    else:                                                         # dust: particles drifting into the brain
        rng = random.Random(3)
        for k in range(60):
            x = rng.uniform(0, L.width); y = (rng.uniform(0, L.height) + t * rng.uniform(10, 40)) % L.height
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=RED + (int(150 * clamp(p / 0.4)),))
        region([cx - 120, cy - 120, cx + 160, cy + 80], RED, qb, "FOGGY DECISIONS")
    return L


def tree_layer(p, t, mode="deep"):
    """Move tree: 'deep' = one long thin line, 'wide' = a few strong first candidates (the master's way)."""
    L = Image.new("RGBA", (940, 640), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    root = (470, 60)
    d.ellipse([root[0] - 22, root[1] - 22, root[0] + 22, root[1] + 22], fill=IVORY + (255,))
    if mode == "deep":
        pts = [root] + [(470 + 90 * math.sin(k * 1.3), 60 + 80 * (k + 1)) for k in range(7)]
        n = max(2, int(len(pts) * clamp(p / 0.8)) + 1)
        d.line(pts[:n], fill=BLUE + (255,), width=8, joint="curve")
        for x, y in pts[1:n]:
            d.ellipse([x - 12, y - 12, x + 12, y + 12], fill=BLUE + (255,))
        if p > 0.85:
            x, y = pts[1]; s = eob((p - 0.85) / 0.15) * 46
            d.line([(x - s, y - s), (x + s, y + s)], fill=RED + (255,), width=14)
            d.line([(x - s, y + s), (x + s, y - s)], fill=RED + (255,), width=14)
    else:
        kids = [(170, 240), (320, 240), (470, 240), (620, 240), (770, 240)]
        for k, (x, y) in enumerate(kids):
            q = clamp((p - 0.1 * k) / 0.3)
            if q <= 0: continue
            col = GOLD if k == 2 else (120, 124, 150)
            d.line([root, (root[0] + (x - root[0]) * q, root[1] + (y - root[1]) * q)], fill=col + (255,), width=8 if k == 2 else 4)
            if q >= 1:
                d.ellipse([x - 16, y - 16, x + 16, y + 16], fill=col + (255,))
        if p > 0.5:
            q = clamp((p - 0.5) / 0.4)
            for k in range(4):
                y1 = 240 + 90 * (k + 1)
                if y1 - 240 <= 360 * q:
                    d.line([(470, 240 + 90 * k), (470, y1)], fill=GOLD + (255,), width=8)
                    d.ellipse([470 - 12, y1 - 12, 470 + 12, y1 + 12], fill=GOLD + (255,))
    return L


def screen_layer(p, t):
    """A screen playing a chess video (watching, not solving)."""
    L = Image.new("RGBA", (900, 620), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    d.rounded_rectangle([60, 40, 840, 540], 30, fill=(10, 10, 20, 240), outline=IVORY + (200,), width=6)
    d.rounded_rectangle([100, 80, 800, 440], 18, fill=(30, 34, 60, 255))
    tri = [(430, 220), (430, 320), (520, 270)]
    d.polygon(tri, fill=GOLD + (255,))
    d.rounded_rectangle([120, 470, 780, 500], 14, fill=(255, 255, 255, 40))
    d.rounded_rectangle([120, 470, 120 + int(660 * clamp(p)), 500], 14, fill=GOLD + (255,))
    for k in range(3):
        d.rounded_rectangle([130 + k * 40, 120, 160 + k * 40, 150], 6, fill=(255, 255, 255, 60))
    return glow(L, BLUE, 16, 60)


def calendar_fail_layer(p, t):
    L = Image.new("RGBA", (900, 560), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    cell = 115
    for i in range(14):
        r, c = divmod(i, 7); x, y = 40 + c * cell, 60 + r * cell
        d.rounded_rectangle([x + 6, y + 6, x + cell - 6, y + cell - 6], 12, fill=(255, 255, 255, 28))
        q = clamp((p - 0.06 * i) / 0.2)
        if q <= 0: continue
        if i < 3:
            d.line([(x + 30, y + 60), (x + 50, y + 80), (x + 85, y + 35)], fill=GREEN + (255,), width=9)
        elif i in (3, 8):
            d.line([(x + 30, y + 30), (x + 85, y + 85)], fill=RED + (255,), width=9)
            d.line([(x + 30, y + 85), (x + 85, y + 30)], fill=RED + (255,), width=9)
        else:
            d.text((x + 45, y + 40), "?", font=font(40), fill=(255, 255, 255, 90))
    return L


def phone_share_layer(p, t, line):
    """Phone mock-up: 'Send to' sheet with three friends, the first gets selected, 'Sent ✓' appears."""
    L = Image.new("RGBA", (760, 1000), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    d.rounded_rectangle([120, 20, 640, 980], 70, fill=(12, 12, 22, 250), outline=IVORY + (220,), width=8)
    d.rounded_rectangle([290, 44, 470, 72], 14, fill=(0, 0, 0, 255))
    d.rounded_rectangle([150, 110, 610, 560], 30, fill=(24, 26, 48, 255))
    bd = R.card(R.draw_board(chess.Board(), False, ())); bd = bd.resize((380, 380), Image.LANCZOS)
    L.alpha_composite(bd, (190, 140))
    sheet_y = 560 + int(260 * (1 - eo((p - 0.1) / 0.3)))
    d.rounded_rectangle([150, sheet_y, 610, 980], 30, fill=(245, 240, 230, 255))
    tx = R.text_img("Send to", 30, INK); L.alpha_composite(tx, (190, sheet_y + 24))
    names = [("E", GOLD), ("D", BLUE), ("L", GREEN)]
    for k, (n, col) in enumerate(names):
        cx, cy = 240 + k * 130, sheet_y + 130
        sel = k == 0 and p > 0.55
        d.ellipse([cx - 44, cy - 44, cx + 44, cy + 44], fill=col + (255,), outline=(INK + (255,)) if sel else (0, 0, 0, 0), width=6)
        tn = R.text_img(n, 40, INK); L.alpha_composite(tn, (cx - tn.width // 2, cy - tn.height // 2))
        nm = R.text_img(("Team", "Dani", "Leo")[k], 22, INK); L.alpha_composite(nm, (cx - nm.width // 2, cy + 56))
    if p > 0.75:
        q = eob((p - 0.75) / 0.25)
        pill = R.pill("Sent ✓", 34, GREEN, fg=INK, padx=30, pady=12)
        pill = pill.resize((max(1, int(pill.width * q)), max(1, int(pill.height * q))), Image.BILINEAR)
        L.alpha_composite(pill, (380 - pill.width // 2, sheet_y - 40 - pill.height // 2))
    if 0.35 < p < 0.6:                                           # a finger tapping the first friend
        fx, fy = 240, sheet_y + 130 + int(60 * (1 - clamp((p - 0.35) / 0.1)))
        d.ellipse([fx - 26, fy - 26, fx + 26, fy + 26], fill=(230, 190, 150, 255))
    return glow(L, GOLD, 20, 60)


def end_layer(p, t, logo):
    L = Image.new("RGBA", (960, 760), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
    d.rounded_rectangle([0, 0, 959, 759], 44, fill=(10, 10, 18, 215), outline=GOLD + (210,), width=2)
    L.alpha_composite(logo, ((L.width - logo.width) // 2, 50))
    y = 60 + logo.height + 30
    for k, (txt, size, col, kind) in enumerate([("DAILY CALCULATION TRAINING", 40, GOLD, "w"),
                                                  ("streakchess.com", 60, IVORY, "p"),
                                                  ("FREE  ·  ALL AGES  ·  FOUNDER OFFER FOR THE FIRST 500", 30, IVORY, "w")]):
        q = eo((p - 0.15 * k) / 0.4)
        if q <= 0: continue
        im = R.pill(txt, size, IVORY, fg=INK, padx=52, pady=18) if kind == "p" else HY.word_img(txt, size, col, 0)
        L.alpha_composite(im, ((L.width - im.width) // 2, y))
        y += im.height + 18
    return L


# ----------------------------------------------------------------- the reel
VIS_MOOD = {"moment": "surprised", "myth": "determined", "mechanism": "thinking", "stat": "neutral", "study": "thinking",
            "result": "excited", "method": "determined", "takeaway": "star", "share": "happy", "end": "excited"}


def build(seed, out, P=None, fact_id=None, mode="level"):
    import voice
    mock = os.environ.get("SCIENCE_MOCK") == "1"
    fact = pick_fact(seed, fact_id)
    log = json.load(open(LOG)) if os.path.exists(LOG) else []
    variant = sum(1 for e in log if e.get("fact") == fact["id"])
    lines = script_for(fact, variant, mock)
    print("Science reel:", fact["id"], "|", fact["hook"], flush=True)

    # a real position for the board scenes (today's puzzle when given, else a classic)
    if P and "fen" in P:
        board = chess.Board(P["fen"]); board.push(chess.Move.from_uci(P["moves"].split()[0]))
        sol = chess.Move.from_uci(P["moves"].split()[1]) if len(P["moves"].split()) > 1 else None
    else:
        board = chess.Board("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"); sol = chess.Move.from_uci("h5f7")
    flip = board.turn == chess.BLACK
    import lesson_anim as LA
    cands = LA.options(board, sol) if sol else LA._ranked_candidates(board, 4)
    method_step = LA.step_facts(board, fact["method"].get("step", "checks"))
    method_moves = [chess.Move.from_uci(m) if isinstance(m, str) else m for m in (method_step.get("moves") or [])] \
                   or [chess.Move(f, t_) for f, t_, _ in method_step.get("arrows", [])[:4]] or cands

    # ---- voice (one engine for the whole reel)
    texts = [lines[k] for k in SCENES]
    styles = {"moment": "vivid, like telling a story", "myth": "playful, a little teasing", "mechanism": "clear, precise, curious",
              "stat": "matter-of-fact, confident", "study": "intrigued", "result": "impressed, slower on the number",
              "method": "practical coach", "takeaway": "warm, memorable", "share": "friendly, direct", "end": "warm invitation"}
    voice.reset("local" if mock else None)
    A = voice.say_many(texts, speed=1.12, styles=[styles[k] for k in SCENES], one_take=False)
    durs = [max(len(a) / SR + 0.4, 2.2) for a in A]
    durs[SCENES.index("result")] += 0.6                            # let the big number land
    durs[SCENES.index("share")] += 0.5
    starts = list(np.cumsum([0.0] + durs[:-1])); total = float(sum(durs)) + 0.3
    n = int(SR * (total + 0.5)); vo = np.zeros(n, np.float32); fx = np.zeros(n, np.float32)

    def put(buf, a, at, g=1.0):
        i = int(at * SR)
        if i >= n: return
        j = min(n, i + len(a)); buf[i:j] += a[: j - i] * g
    for k, a in enumerate(A):
        put(vo, a, starts[k] + 0.2)
        if k: put(fx, R.shimmer([659.3, 784.0, 880.0, 587.3][k % 4]), starts[k] - 0.05, 0.5)
    put(fx, R.soft_hit(), starts[SCENES.index("myth")] + 0.1, 0.7)
    put(fx, R.ding(), starts[SCENES.index("result")] + durs[SCENES.index("result")] * 0.72, 0.6)
    put(fx, R.pop(), starts[SCENES.index("share")] + durs[SCENES.index("share")] * 0.78, 0.8)
    music = HY.beat(total)[:n]
    venv = np.convolve((np.abs(vo) > 0.01).astype(np.float32), np.ones(3000) / 3000, "same")
    mix = HY.dehiss(np.tanh((vo * 1.15 + fx + music * (0.36 - 0.2 * np.clip(venv * 3, 0, 1))) * 1.1) * 0.92)
    wav = out.replace(".mp4", "_sc.wav"); sf.write(wav, mix, SR)
    hop = SR // FPS
    env = np.array([np.sqrt(np.mean(vo[i * hop:(i + 1) * hop] ** 2)) for i in range(int(total * FPS) + 2)])
    env = np.clip(env / (np.percentile(env[env > 0.004], 85) + 1e-6), 0, 1) if (env > 0.004).any() else env
    words = []
    for k, a in enumerate(A):
        for ts, w in voice.align(a, texts[k]):
            words.append((k, starts[k] + 0.2 + ts, w))

    # ---- static pieces
    stage = Stage()
    _lp = os.path.join(HERE, "assets", "logo_h_white.png")
    logo = Image.open(_lp if os.path.exists(_lp) else os.path.join(HERE, "assets", "logo_h.png")).convert("RGBA")
    logo = logo.crop(logo.getbbox()); logo = logo.resize((520, int(logo.height * 520 / logo.width)), Image.LANCZOS)
    hook_img = glow(big_label(fact["hook"], GOLD, 96), GOLD, 20, 90)
    labels = {"myth": fact["myth"]["label"], "mechanism": fact["mechanism"]["label"], "method": fact["method"]["label"],
              "takeaway": fact["takeaway"]["label"]}
    label_imgs = {k: glow(big_label(v, GOLD if k != "myth" else RED, 80), GOLD if k != "myth" else RED, 18, 80)
                  for k, v in labels.items()}
    share_img = HY.fit_phrase(fact["share"].upper().split(), 58, 900, 3, 36)
    src = R.text_img("Source: " + fact["sources"][0][:90], 22, (170, 174, 200), maxw=980)
    mv = fact["moment"].get("visual", "board_flash"); mech = fact["mechanism"].get("visual", "board_chunks")
    S = fact["stat"]; ST = fact["study"]; RS = fact["result"]

    def visual(kind, key, p, t):
        """The visual of a scene as a layer (or None)."""
        if key.startswith("board_"):
            eff = {"board_flash": "flash", "board_blunder": "blunder", "board_two_solutions": "two_solutions",
                   "board_chunks": "chunks", "board_glance": "", "board_vs_desk": "", "board_math": "", "kid_board": ""}.get(key, "")
            return board_layer(board, flip, p, eff, sol, cands, t)
        if key in ("clock_games", "clock_skip"):
            return clock_layer(p, t, drain=True, games=key == "clock_games")
        if key in ("hall_dust", "dust_brain"):
            return brain_layer(p, t, "dust")
        if key in ("brain_two", "brain_regions"):
            return brain_layer(p, t, "regions")
        if key == "brain_pull":
            return brain_layer(p, t, "pull")
        if key in ("tree_deep", "tree_wide"):
            return tree_layer(p, t, "deep" if key == "tree_deep" else "wide")
        if key == "screen_watch":
            return screen_layer(p, t)
        if key == "calendar_fail":
            return calendar_fail_layer(p, t)
        if key in ("timeline", "two_engines"):
            return timeline_layer(ST["points"] if ST.get("type") == "timeline" else [[20, 60], [30, 85], [35, 100], [45, 97], [60, 80]], p, "PERFORMANCE BY AGE", "PEAK")
        if key == "eye_squares":
            return board_layer(board, flip, p, "eyes", sol, cands, t)
        if key == "cue_action":
            return calendar_layer(21, p, "CUE → ACTION → REPEAT", "HABIT")
        return board_layer(board, flip, p, "", sol, cands, t)

    def data_visual(D, p, t):
        ty = D.get("type")
        if ty == "grid":
            return grid_layer(D["total"], D["a"], D["b"], p, D.get("label_a", ""), D.get("label_b", ""), D.get("title", ""))
        if ty == "dots":
            return dots_layer(D["total"], p, D.get("title", ""), D.get("label", ""), D.get("split"), D.get("split_labels"))
        if ty == "bars":
            return bars_layer(D["labels"], D["values"], D.get("max", max(D["values"])), p, D.get("title", ""), D.get("big", ""))
        if ty == "timeline":
            return timeline_layer(D["points"], p, D.get("title", ""), D.get("big", ""))
        if ty == "calendar":
            return calendar_layer(D["total"], p, D.get("title", ""), D.get("big", ""))
        return None

    cache = {}

    def fit(layer, maxw=1000, maxh=760):
        s = min(1.0, maxw / layer.width, maxh / layer.height)
        return layer if s >= 1 else layer.resize((int(layer.width * s), int(layer.height * s)), Image.LANCZOS)

    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-i", wav, "-shortest"] + HY.enc_args(out), stdin=subprocess.PIPE)
    for fi in range(int(total * FPS)):
        t = fi / FPS
        k = min(len(starts) - 1, int(np.searchsorted(starts, t, side="right") - 1)); lt = t - starts[k]
        scene = SCENES[k]; p = clamp(lt / max(0.1, durs[k] - 0.4))
        mouth = float(env[fi]) if fi < len(env) else 0.0
        fr = stage.frame(t)
        layer = None; vk_cx, vk_bottom, vk_scale, vk_mood = 112, 1345, 0.32, VIS_MOOD[scene]
        lx, maxw = W / 2, 1000
        if scene == "moment":
            layer = visual("moment", mv, p, t); maxw = 780
            R.paste_center(fr, hook_img, W / 2, TOP_Y, 1.0, 1.0 if lt < durs[k] - 0.4 else max(0, 1 - (lt - durs[k] + 0.4) / 0.4))
        elif scene == "myth":
            lab = label_imgs["myth"]; q = eob(lt / 0.35)
            R.paste_center(fr, lab, W / 2, TOP_Y, q)
            if lt > 0.5:                                          # a crimson strike through the myth
                d = ImageDraw.Draw(fr); w2 = lab.width * 0.5 * clamp((lt - 0.5) / 0.3)
                d.line([(W / 2 - w2, TOP_Y + 6), (W / 2 + w2, TOP_Y - 6)], fill=RED + (230,), width=10)
            layer = visual("myth", mv, min(1.0, 0.6 + p * 0.4), t); vk_mood = "determined"; maxw = 780
        elif scene == "mechanism":
            R.paste_center(fr, label_imgs["mechanism"], W / 2, TOP_Y, eob(lt / 0.35))
            layer = visual("mechanism", mech, p, t); maxw = 780 if mech.startswith(("board", "eye")) else 900
        elif scene in ("stat", "study", "result"):
            D = {"stat": S, "study": ST, "result": RS}[scene]
            layer = data_visual(D, p, t)
            if layer is None:
                layer = visual(scene, mech, p, t)
        elif scene == "method":
            R.paste_center(fr, label_imgs["method"], W / 2, TOP_Y, eob(lt / 0.35))
            layer = board_layer(board, flip, p, "method", sol, method_moves, t); maxw = 780
        elif scene == "takeaway":
            R.paste_center(fr, label_imgs["takeaway"], W / 2, TOP_Y, eob(lt / 0.35))
            layer = None; vk_cx, vk_bottom, vk_scale = W / 2, 1180, 0.62
            R.paste_center(fr, src, W / 2, 1260 + 60, 1.0, clamp((lt - 0.6) / 0.5))
        elif scene == "share":
            R.paste_center(fr, share_img, W / 2, TOP_Y - 20, eob(lt / 0.35))
            layer = phone_share_layer(p, t, fact["share"]); vk_cx, vk_bottom, vk_scale = 120, 1345, 0.32; lx = W / 2 + 110
        else:
            layer = end_layer(p, t, logo); vk_cx, vk_bottom, vk_scale = 880, 600, 0.30
        if layer is not None:
            layer = fit(layer, maxw)
            enter = eo(lt / 0.45)
            if scene == "end":                                    # Vektor sits on top of the app card
                stage.vektor(fr, t, mouth, vk_mood, vk_cx, VIS_CY - layer.height // 2 + 24, vk_scale, look=(-0.3, 0.2))
            R.paste_center(fr, layer, lx, VIS_CY + (1 - enter) * 60, 1.0, enter)
        if scene != "end":
            stage.vektor(fr, t, mouth, vk_mood, vk_cx, vk_bottom, vk_scale, look=(0.5, 0.0))
        # kinetic subtitles (the words being spoken)
        cur = [(ts, w) for si, ts, w in words if si == k and ts <= t]
        if cur and scene != "end":
            idx = len(cur) - 1; s0 = (idx // 3) * 3
            ph = HY.phrase_img([w for _, w in cur[s0:idx + 1]], t - cur[-1][0], 66, 1000)
            R.paste_center(fr, HY.band_img(ph.height + 60), W / 2, SUB_Y)
            R.paste_center(fr, ph, W / 2, SUB_Y)
        if lt < 0.3 and k:                                        # soft dip between scenes
            fr = Image.blend(fr, Image.new("RGBA", (W, H), (4, 4, 10, 255)), 0.5 * (1 - lt / 0.3))
        fr.alpha_composite(HY.vignette())
        proc.stdin.write(fr.convert("RGB").tobytes())
    proc.stdin.close(); proc.wait(); os.remove(wav)

    # ---- caption
    rng = random.Random(seed)
    import hooks
    cap_hook = hooks.ensure(fact["hook"] + " 🧠", "science", fact["topic"], seed=f"{fact['id']}-{seed}")
    cap = (f"{cap_hook}\n{fact['topic']}\n\n"
           f"🔬 {fact['study']['narration']} {fact['result']['narration']}\n\n"
           f"✅ What to do: {fact['method']['narration']}\n\n"
           f"{fact['share']} 👇\n"
           f"Train your calculation free every day on StreakChess (link in bio).\n"
           f"Source: {'; '.join(fact['sources'])}\n\n"
           + " ".join(R.hashtags(rng, "chessscience")))
    review = {}
    if not mock and os.environ.get("REVIEWER", "on") != "off" and os.environ.get("GEMINI_API_KEY"):
        import reviewer                                        # same QA as every other reel
        try:
            cap, review = reviewer.review_video(out, {"title": f"Chess science: {fact['topic']}"}, cap)
            cap_hook = cap.split("\n", 1)[0]
        except reviewer.RejectReel:
            raise
        except Exception as e:
            print("science review skipped:", str(e)[:150], flush=True)
    open(out.replace(".mp4", ".txt"), "w").write(cap)
    if not mock and os.environ.get("DRY_RUN") != "true":
        log.append({"fact": fact["id"], "variant": variant}); json.dump(log[-200:], open(LOG, "w"), indent=0)
    return dict(mode="science", puzzle=(P or {}).get("id"), level=(P or {}).get("level"), rating=(P or {}).get("rating"),
                hook=cap_hook, sans=[board.san(sol)] if sol else [], reveal=None, ab=None, side="White" if board.turn else "Black",
                story=f"Science: {fact['topic']}", science=fact["id"], duration=round(total, 1), thumb_offset_ms=0,
                review_score=review.get("overall"))


if __name__ == "__main__":
    print(json.dumps(build(int(sys.argv[1]), sys.argv[2], fact_id=sys.argv[3] if len(sys.argv) > 3 else None), indent=1))
