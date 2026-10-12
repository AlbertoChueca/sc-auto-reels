"""Renders a plan (yt_script) to a 1920x1080 MP4 with a chess-studio look, word-by-word captions, an SRT file,
two thumbnails and the YouTube chapters.

Layout: evaluation bar | classic board (last move, arrows, glowing squares) | right panel (context: puzzle card,
timer + hint, players + move list in algebraic notation, pop words) ; captions band at the bottom.
The narration is recorded first; the picture is a list of shots (image + duration) joined by ffmpeg.
"""
import json, math, os, re, subprocess, sys, tempfile
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import chess, chess.svg, cairosvg, io

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import make_reel as R                                      # noqa: E402  (sound effects, mascot)
import yt_notation as NT                                   # noqa: E402
import yt_engine as EN                                     # noqa: E402

W, H, FPS, SR = 1920, 1080, 25, 24000
MOCK = bool(os.environ.get("YT_MOCK"))
FD = os.path.join(ROOT, "fonts")
F_REG, F_MED, F_SEMI, F_BOLD, F_XB = (os.path.join(FD, f) for f in
                                      ("Inter-Medium.otf", "Inter-Medium.otf", "Inter-SemiBold.otf", "Inter-Bold.otf", "Inter-ExtraBold.otf"))
F_DISP, F_BLACK = os.path.join(FD, "InterDisplay-Bold.otf"), os.path.join(FD, "InterDisplay-Black.otf")

BG = (16, 18, 23); PANEL = (26, 29, 36); PANEL2 = (34, 38, 47); LINE = (52, 57, 68)
TEXT = (238, 240, 244); MUTED = (146, 153, 168); ORANGE = (242, 98, 46); GOLD = (246, 192, 72); GREEN = (96, 196, 120)
LIGHT_SQ, DARK_SQ = (240, 217, 181), (181, 136, 99)
LAST = (205, 210, 106, 150); ARROW = (21, 120, 27, 200); ARROW2 = (230, 80, 50, 200)

SQ = 104; BOARD = SQ * 8
EBX, BX, BY = 48, 94, 52                                  # eval bar x, board x, board y
PX0, PX1, PY0, PY1 = 972, 1868, 52, BY + BOARD             # right panel
CAP_Y = 920
COACH = ("You are the voice of StreakChess, a sharp, warm and funny chess coach talking at the board to one viewer. "
         "Sound like a real YouTuber recording in a studio: natural rhythm, smiles in the voice, small pauses before "
         "reveals, conversational, confident. Never robotic, never a flat announcer, never over the top.")


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


def text_fit(d, text, path, size, box, fill=TEXT, align="left", max_lines=3, min_size=24, lh=1.15, stroke=0, sfill=BG):
    x0, y0, x1, y1 = box
    while True:
        f = fnt(path, size); lines = wrap(text, f, x1 - x0); h = int(size * lh) * len(lines)
        if (len(lines) <= max_lines and h <= y1 - y0) or size <= min_size:
            break
        size -= 2
    y = y0
    for ln in lines[:max_lines]:
        w = f.getlength(ln)
        x = x0 + {"left": 0, "center": (x1 - x0 - w) / 2, "right": x1 - x0 - w}[align]
        d.text((x, y), ln, font=f, fill=fill, stroke_width=stroke, stroke_fill=sfill)
        y += int(size * lh)
    return y


def chip(d, x, y, text, size=22, bg=PANEL2, fg=TEXT, pad=14, bold=F_BOLD):
    f = fnt(bold, size); w = f.getlength(text)
    d.rounded_rectangle([x, y, x + w + 2 * pad, y + size + 2 * pad - 6], 8, fill=bg)
    d.text((x + pad, y + pad - 5), text, font=f, fill=fg)
    return x + w + 2 * pad


# ------------------------------------------------------------------ static layers
_C = {}


def background():
    if "bg" not in _C:
        y, x = np.mgrid[0:H, 0:W]
        d = np.clip(np.sqrt(((x - W * 0.28) / W) ** 2 + ((y - H * 0.45) / H) ** 2) / 0.9, 0, 1)[..., None]
        c1, c2 = np.array([30, 33, 42]), np.array(BG)
        img = (c1 * (1 - d) + c2 * d)
        noise = np.random.RandomState(1).normal(0, 2.2, (H, W, 1))
        _C["bg"] = Image.fromarray(np.clip(img + noise, 0, 255).astype(np.uint8), "RGB").convert("RGBA")
    return _C["bg"].copy()


def logo(width, white=True):
    k = ("logo", width, white)
    if k not in _C:
        im = Image.open(os.path.join(ROOT, "assets", "logo_h_white.png" if white else "logo_h.png")).convert("RGBA")
        _C[k] = im.resize((width, int(im.height * width / im.width)), Image.LANCZOS)
    return _C[k]


def piece(p, size=SQ):
    k = ("pc", p.symbol(), size)
    if k not in _C:
        png = cairosvg.svg2png(bytestring=chess.svg.piece(p).encode(), output_width=size, output_height=size)
        _C[k] = Image.open(io.BytesIO(png)).convert("RGBA")
    return _C[k]


def sq_xy(s, flip):
    f, r = chess.square_file(s), chess.square_rank(s)
    return ((7 - f) * SQ, r * SQ) if flip else (f * SQ, (7 - r) * SQ)


def arrow(d, a, b, flip, color, width=20):
    x1, y1 = sq_xy(a, flip); x2, y2 = sq_xy(b, flip)
    x1 += SQ / 2; y1 += SQ / 2; x2 += SQ / 2; y2 += SQ / 2
    ang = math.atan2(y2 - y1, x2 - x1); L = math.hypot(x2 - x1, y2 - y1) - SQ * 0.18
    hw, hl = 46, 44; w = width
    pts = [(SQ * 0.18, -w / 2), (L - hl, -w / 2), (L - hl, -hw / 2), (L, 0), (L - hl, hw / 2), (L - hl, w / 2), (SQ * 0.18, w / 2)]
    ca, sa = math.cos(ang), math.sin(ang)
    d.polygon([(x1 + px * ca - py * sa, y1 + px * sa + py * ca) for px, py in pts], fill=color)


def board_img(fen, flip, last=None, squares=(), arrows=(), hide=None, floating=None):
    """Classic board with coordinates, last move, glowing squares, arrows, check."""
    key = (fen, flip, last, tuple(squares), tuple(arrows), hide)
    if floating is None and key in _C:
        return _C[key]
    b = chess.Board(fen)
    im = Image.new("RGBA", (BOARD, BOARD))
    d = ImageDraw.Draw(im)
    for s in chess.SQUARES:
        x, y = sq_xy(s, flip)
        light = (chess.square_file(s) + chess.square_rank(s)) % 2 == 1
        d.rectangle([x, y, x + SQ, y + SQ], fill=LIGHT_SQ if light else DARK_SQ)
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
    if last:
        for s in last:
            x, y = sq_xy(s, flip); od.rectangle([x, y, x + SQ, y + SQ], fill=LAST)
    for name in squares:
        s = chess.parse_square(name); x, y = sq_xy(s, flip)
        od.ellipse([x + 6, y + 6, x + SQ - 6, y + SQ - 6], outline=(242, 98, 46, 235), width=7)
    if b.is_check():
        k = b.king(b.turn); x, y = sq_xy(k, flip)
        for r_, a in ((52, 70), (40, 120), (26, 170)):
            od.ellipse([x + SQ / 2 - r_, y + SQ / 2 - r_, x + SQ / 2 + r_, y + SQ / 2 + r_], fill=(230, 30, 30, a))
    im.alpha_composite(ov)
    fl = fnt(F_BOLD, 21)
    for i in range(8):
        file_c = "abcdefgh"[7 - i if flip else i]; rank_c = str(i + 1 if flip else 8 - i)
        d.text((i * SQ + SQ - 18, BOARD - 27), file_c, font=fl, fill=LIGHT_SQ if i % 2 == 0 else DARK_SQ)
        d.text((6, i * SQ + 4), rank_c, font=fl, fill=DARK_SQ if i % 2 == 0 else LIGHT_SQ)
    for s, p in b.piece_map().items():
        if s == hide:
            continue
        x, y = sq_xy(s, flip); im.alpha_composite(piece(p), (x, y))
    if floating:
        p, fx, fy = floating; im.alpha_composite(piece(p), (int(fx), int(fy)))
    if arrows:
        ar = Image.new("RGBA", im.size, (0, 0, 0, 0)); ad = ImageDraw.Draw(ar)
        for k, u in enumerate(arrows):
            m = chess.Move.from_uci(u); arrow(ad, m.from_square, m.to_square, flip, ARROW if k == 0 else ARROW2)
        im.alpha_composite(ar)
    if floating is None:
        _C[key] = im
    return im


def win_pct(cp):
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def eval_bar(d, cp, flip, show):
    x0, x1, y0, y1 = EBX, EBX + 30, BY, BY + BOARD
    d.rounded_rectangle([x0, y0, x1, y1], 6, fill=(60, 60, 64))
    if not show or cp is None:
        d.rounded_rectangle([x0, y0, x1, y1], 6, fill=(70, 72, 80))
        f = fnt(F_BOLD, 22); d.text((x0 + 15 - f.getlength("?") / 2, (y0 + y1) / 2 - 12), "?", font=f, fill=TEXT)
        return
    pw = win_pct(cp) / 100
    h = int((y1 - y0) * pw)
    if not flip:
        d.rounded_rectangle([x0, y1 - h, x1, y1], 6, fill=(245, 245, 245))
    else:
        d.rounded_rectangle([x0, y0, x1, y0 + h], 6, fill=(245, 245, 245))
    lab = EN.fmt(cp).replace("+", "")
    f = fnt(F_BOLD, 15 if len(lab) > 3 else 17)
    white_bottom = not flip
    near_white = (cp >= 0)
    ty = (y1 - 24 if white_bottom else y0 + 6) if near_white else (y0 + 6 if white_bottom else y1 - 24)
    d.text((x0 + 15 - f.getlength(lab) / 2, ty), lab, font=f, fill=(30, 30, 30) if near_white else (240, 240, 240))


# ------------------------------------------------------------------ panel
def move_list(d, labels, upto, box, active=True):
    """Two-column move list in algebraic notation, the current move highlighted; auto-scrolls."""
    x0, y0, x1, y1 = box
    rows = []
    for k, lab in enumerate(labels[:upto]):
        m = re.match(r"(\d+)\.(\.\.)?(.*)", lab)
        if m and not m.group(2):
            rows.append([m.group(1), (m.group(3), k), None])
        elif m and m.group(2):
            rows.append([m.group(1), ("...", -1), (m.group(3), k)])
        else:
            if rows and rows[-1][2] is None:
                rows[-1][2] = (lab, k)
            else:
                rows.append(["", ("...", -1), (lab, k)])
    rh = 44; maxr = int((y1 - y0) / rh)
    rows = rows[-maxr:]
    f, fn = fnt(F_SEMI, 27), fnt(F_MED, 24)
    cw = min(210, (x1 - x0 - 70) / 2)
    for i, (num, a, b) in enumerate(rows):
        y = y0 + i * rh
        if i % 2 == 0:
            d.rectangle([x0, y, x1, y + rh], fill=(31, 34, 42))
        d.text((x0 + 14, y + 9), f"{num}." if num else "", font=fn, fill=MUTED)
        for j, cell in enumerate((a, b)):
            if not cell:
                continue
            txt, k = cell; cx = x0 + 70 + j * cw
            if k == upto - 1 and active:
                d.rounded_rectangle([cx - 8, y + 4, cx + f.getlength(txt) + 10, y + rh - 4], 6, fill=ORANGE)
                d.text((cx, y + 7), txt, font=f, fill=(255, 255, 255))
            else:
                d.text((cx, y + 7), txt, font=f, fill=TEXT if k >= 0 else MUTED)


def panel(im, st, plan):
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([PX0, PY0, PX1, PY1], 18, fill=PANEL)
    ctx = st.get("ctx") or {}; kind = ctx.get("kind", "talk")
    x = PX0 + 34; y = PY0 + 30
    d.text((x, y), plan.get("series_tag", ""), font=fnt(F_BOLD, 20), fill=ORANGE)
    lg = logo(150); im.alpha_composite(lg, (PX1 - lg.width - 30, y - 6))
    y += 40
    if st.get("chapter"):
        text_fit(d, st["chapter"], F_DISP, 44, (x, y, PX1 - 34, y + 60), max_lines=1)
    y += 78
    d.line([x, y, PX1 - 34, y], fill=LINE, width=2); y += 26
    if st["kind"] == "countdown":
        side = ctx.get("side") or st.get("prompt", "").split()[0]
        nx = chip(d, x, y, st["prompt"].upper(), 24, bg=(245, 245, 245) if side == "White" else (12, 12, 14),
                  fg=(20, 20, 20) if side == "White" else TEXT)
        if ctx.get("rating"):
            chip(d, nx + 12, y, f"RATING {ctx['rating']}", 24)
        cx, cy, r = (PX0 + PX1) / 2, y + 290, 175
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=PANEL2, width=20)
        frac = st["left"] / max(1, st["total"])
        if frac > 0:
            d.arc([cx - r, cy - r, cx + r, cy + r], -90, -90 + 360 * frac, fill=ORANGE if st["left"] <= 3 else GOLD, width=20)
        n = str(st["left"]); f = fnt(F_BLACK, 150)
        d.text((cx - f.getlength(n) / 2, cy - 98), n, font=f, fill=TEXT)
        if st.get("hint") and st["left"] <= st["total"] // 2:
            hy = cy + r + 40
            d.rounded_rectangle([x, hy, PX1 - 34, hy + 96], 14, fill=PANEL2)
            d.text((x + 22, hy + 14), "HINT", font=fnt(F_BOLD, 20), fill=GOLD)
            text_fit(d, st["hint"], F_SEMI, 32, (x + 22, hy + 42, PX1 - 56, hy + 90), max_lines=1)
        else:
            text_fit(d, "Pause the video if you need more time", F_MED, 26, (x, cy + r + 50, PX1 - 34, cy + r + 90),
                     fill=MUTED, align="center", max_lines=1)
        return
    if kind in ("puzzle",):
        side = ctx["side"]
        nx = chip(d, x, y, f"{side.upper()} TO MOVE", 24, bg=(245, 245, 245) if side == "White" else (12, 12, 14),
                  fg=(20, 20, 20) if side == "White" else TEXT)
        if ctx.get("rating"):
            nx = chip(d, nx + 12, y, f"RATING {ctx['rating']}", 24)
        if ctx.get("demo"):
            chip(d, nx + 12, y, "DEMO", 24, bg=ORANGE)
        y += 74
        if ctx.get("streak"):
            n, i = ctx["of"], ctx["num"]
            d.text((x, y), "STREAK", font=fnt(F_BOLD, 20), fill=MUTED)
            bw = (PX1 - 34 - x - 9 * 8) / n
            for k in range(n):
                bx = x + k * (bw + 8)
                col = ORANGE if k < i - 1 else (GOLD if k == i - 1 else PANEL2)
                d.rounded_rectangle([bx, y + 30, bx + bw, y + 46], 5, fill=col)
            y += 70
        ply = st.get("ply") or 0
        if ply:
            d.text((x, y), "SOLUTION", font=fnt(F_BOLD, 20), fill=MUTED); y += 34
            move_list(d, ctx["moves"], ply, (x, y, PX1 - 34, PY1 - 150))
    elif kind in ("game", "live"):
        f1, f2 = fnt(F_BOLD, 30), fnt(F_MED, 24)
        for col, nm, el in ((245, ctx.get("white"), ctx.get("welo")), (12, ctx.get("black"), ctx.get("belo"))):
            d.rounded_rectangle([x, y + 6, x + 22, y + 28], 4, fill=(col, col, col), outline=LINE)
            d.text((x + 36, y), (nm or "")[:34], font=f1, fill=TEXT)
            if el:
                d.text((PX1 - 34 - f2.getlength(str(el)), y + 4), str(el), font=f2, fill=MUTED)
            y += 44
        ev = ctx.get("event") or ""
        sub = f"{ev} · {ctx['year']}" if ctx.get("year") else (f"{ev} · Round {ctx['round']}" if ctx.get("round") else ev)
        text_fit(d, sub, F_MED, 24, (x, y, PX1 - 34, y + 32), fill=MUTED, max_lines=1); y += 50
        upto = st.get("ply") if st.get("ply") is not None else ctx.get("upto", 0)
        if kind == "live" and not st.get("ply"):
            upto = 0
        if upto:
            move_list(d, ctx["moves"], upto, (x, y, PX1 - 34, PY1 - 150))
        elif kind == "live" and ctx.get("side"):
            y += 20
            chip(d, x, y, f"{ctx['side'].upper()} TO MOVE", 24, bg=(245, 245, 245) if ctx["side"] == "White" else (12, 12, 14),
                 fg=(20, 20, 20) if ctx["side"] == "White" else TEXT)
            text_fit(d, "FIND THE SHOT", F_BLACK, 84, (x, y + 80, PX1 - 34, y + 200), max_lines=1)
            text_fit(d, "One move wins. Can you see it before the timer ends?", F_MED, 30, (x, y + 200, PX1 - 34, y + 290),
                     fill=MUTED, max_lines=2)
    elif kind == "app":
        m = R.mascot("happy", 300); im.alpha_composite(m, (int((PX0 + PX1) / 2 - 150), y + 10))
        y += 330
        text_fit(d, "Train your calculation every day", F_DISP, 46, (x, y, PX1 - 34, y + 120), align="center", max_lines=2)
        y += 130
        u = os.environ.get("APP_URL", "streakchess.com"); f = fnt(F_BOLD, 34); w = f.getlength(u)
        d.rounded_rectangle([(PX0 + PX1) / 2 - w / 2 - 30, y, (PX0 + PX1) / 2 + w / 2 + 30, y + 64], 32, fill=ORANGE)
        d.text(((PX0 + PX1) / 2 - w / 2, y + 12), u, font=f, fill=(255, 255, 255))
        return
    elif kind == "ranks":
        f = fnt(F_BOLD, 34); fs = fnt(F_MED, 26)
        bands = ["0-2", "3-4", "5-6", "7-8", "9", "10"]
        import yt_script as SC
        for k, (bd, nm) in enumerate(zip(bands, SC.RANKS)):
            yy = y + k * 82
            d.rounded_rectangle([x, yy, PX1 - 34, yy + 68], 12, fill=PANEL2 if k < 5 else ORANGE)
            d.text((x + 24, yy + 18), f"{bd} points", font=fs, fill=TEXT if k < 5 else (255, 255, 255))
            d.text((PX1 - 58 - f.getlength(nm), yy + 13), nm, font=f, fill=GOLD if k < 5 else (255, 255, 255))
        return
    elif kind == "end":
        text_fit(d, "WATCH NEXT", F_BOLD, 24, (x, y, PX1 - 34, y + 30), fill=MUTED, max_lines=1)
        for k in range(2):                                   # room for YouTube end-screen elements
            yy = y + 44 + k * 260
            d.rounded_rectangle([x, yy, PX1 - 34, yy + 230], 16, outline=LINE, width=3)
        return
    if kind == "tease":
        side = ctx.get("side", "White")
        nx = chip(d, x, y, f"{side.upper()} TO MOVE", 24, bg=(245, 245, 245) if side == "White" else (12, 12, 14),
                  fg=(20, 20, 20) if side == "White" else TEXT)
        if ctx.get("rating"):
            chip(d, nx + 12, y, f"RATING {ctx['rating']}", 24)
        y += 90
        text_fit(d, ctx.get("headline", "FIND THE WINNING MOVE"), F_BLACK, 84, (x, y, PX1 - 34, y + 300), max_lines=3)
        y += 320
        text_fit(d, ctx.get("sub", "Don't scroll: we solve it together."), F_MED, 30, (x, y, PX1 - 34, y + 90), fill=MUTED, max_lines=2)
        return
    notes = list(st.get("notes") or [])
    if kind in ("talk",) and not notes and st.get("pop"):
        notes = [st["pop"]]
    if kind in ("talk", "puzzle", "game", "live") and st.get("pop") and kind != "talk":
        text_fit(d, st["pop"].upper(), F_BLACK, 80, (x, PY1 - 300, PX1 - 34, PY1 - 40), fill=GOLD, max_lines=3)
    if kind == "talk":
        rule = plan.get("coach_rule") if st.get("chapter_id") in ("recap", "method", "lessons") else None
        if notes:
            d.text((x, y), "COACH'S NOTES", font=fnt(F_BOLD, 22), fill=MUTED); y += 46
            for k, nt in enumerate(notes[-5:]):
                cur = k == len(notes[-5:]) - 1 and st.get("pop") == nt
                d.ellipse([x, y + 16, x + 14, y + 30], fill=ORANGE if cur else LINE)
                y = text_fit(d, nt, F_DISP if cur else F_SEMI, 46 if cur else 38, (x + 34, y, PX1 - 34, y + 110),
                             fill=GOLD if cur else TEXT, max_lines=2) + 18
        if rule:
            ry = max(y + 10, PY1 - 230)
            d.rounded_rectangle([x, ry, PX1 - 34, PY1 - 30], 16, fill=PANEL2)
            d.text((x + 24, ry + 20), "COACH'S RULE", font=fnt(F_BOLD, 22), fill=ORANGE)
            text_fit(d, plan["coach_rule"], F_DISP, 44, (x + 24, ry + 56, PX1 - 58, PY1 - 44), max_lines=3)
        if not notes and not rule:
            text_fit(d, plan.get("series", ""), F_BLACK, 88, (x, y + 20, PX1 - 34, y + 230), max_lines=2)
            text_fit(d, f"Episode {plan.get('episode', '')}", F_SEMI, 40, (x, y + 240, PX1 - 34, y + 300), fill=MUTED, max_lines=1)
            m = R.mascot("thinking", 300); im.alpha_composite(m, (PX1 - 334, PY1 - 330))


def captions(im, cap):
    """Bottom subtitles: current phrase, current word highlighted, notation kept as written."""
    if not cap:
        return
    words, cur = cap
    d = ImageDraw.Draw(im)
    f = fnt(F_SEMI, 46); maxw = 1560
    lines, line, lw = [], [], 0
    sp = f.getlength(" ")
    for k, w in enumerate(words):
        wl = f.getlength(w)
        if line and lw + sp + wl > maxw:
            lines.append(line); line, lw = [], 0
        line.append((k, w, wl)); lw += (sp if len(line) > 1 else 0) + wl
    if line:
        lines.append(line)
    lines = lines[-2:]
    lh = 60; total_h = lh * len(lines)
    widths = [sum(w for _, _, w in ln) + sp * (len(ln) - 1) for ln in lines]
    bw = max(widths) + 56
    y0 = CAP_Y + (128 - total_h) / 2 - 8
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(ov).rounded_rectangle([W / 2 - bw / 2, y0 - 12, W / 2 + bw / 2, y0 + total_h + 10], 16, fill=(8, 9, 12, 190))
    im.alpha_composite(ov)
    for i, ln in enumerate(lines):
        x = W / 2 - widths[i] / 2; y = y0 + i * lh
        for k, w, wl in ln:
            is_move = bool(NT.TOKEN.match(w)) and (NT.is_move_like(NT.TOKEN.match(w).group("san")) or NT.TOKEN.match(w).group("num"))
            col = GOLD if k == cur else ((255, 196, 150) if is_move else TEXT)
            d.text((x, y), w, font=f, fill=col)
            x += wl + sp


def compose(st, plan):
    base_key = json.dumps({k: v for k, v in st.items() if k not in ("cap", "float")}, sort_keys=True, default=str)
    if st.get("float") is None and _C.get("base_key") == base_key:
        im = _C["base"].copy()
    else:
        im = background(); d = ImageDraw.Draw(im)
        if st["kind"] == "sting":
            sting(im, st, plan)
            return im.convert("RGB")
        fen = st["fen"]
        bi = board_img(fen, st.get("flip"), tuple(st.get("last") or ()) or None, st.get("squares", ()), st.get("arrows", ()),
                       st.get("hide"), st.get("float"))
        sh = Image.new("RGBA", (BOARD + 40, BOARD + 40), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rectangle([20, 20, BOARD + 20, BOARD + 20], fill=(0, 0, 0, 150))
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)), (BX - 20, BY - 12))
        im.alpha_composite(bi, (BX, BY))
        eval_bar(d, st.get("cp"), st.get("flip"), st.get("eval"))
        panel(im, st, plan)
        if st.get("float") is None:
            _C["base_key"], _C["base"] = base_key, im.copy()
    captions(im, st.get("cap"))
    return im.convert("RGB")


def sting(im, st, plan):
    d = ImageDraw.Draw(im)
    if st.get("fen"):
        bi = board_img(st["fen"], st.get("flip")).resize((W, W), Image.LANCZOS).filter(ImageFilter.GaussianBlur(12))
        dark = Image.new("RGBA", bi.size, (12, 13, 17, 210)); bi.alpha_composite(dark)
        im.alpha_composite(bi, (0, H // 2 - W // 2))
    f = fnt(F_BOLD, 30); t = plan.get("series_tag", "")
    d.text((W / 2 - f.getlength(t) / 2, 330), t, font=f, fill=ORANGE)
    text_fit(d, plan.get("title", ""), F_BLACK, 104, (200, 390, W - 200, 690), align="center", max_lines=3)
    lg = logo(380); im.alpha_composite(lg, (W // 2 - lg.width // 2, 760))


# ------------------------------------------------------------------ audio
def music(n_samples):
    """Soft warm pad + gentle pulse under the narration (tonal, no noise)."""
    t = np.arange(n_samples) / SR
    chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (130.81, 196.0, 261.63), (196.0, 246.94, 293.66)]
    bar = 8.0; out = np.zeros(n_samples, np.float32)
    for k in range(int(n_samples / SR / bar) + 1):
        a, b = int(k * bar * SR), min(n_samples, int((k + 1) * bar * SR + SR * 1.5))
        if a >= n_samples:
            break
        tt = np.arange(b - a) / SR
        env = np.clip(tt / 1.5, 0, 1) * np.clip((bar + 1.5 - tt) / 1.5, 0, 1)
        s = sum(np.sin(2 * np.pi * f * tt) + 0.25 * np.sin(2 * np.pi * f * 2 * tt) for f in chords[k % 4])
        bass = np.sin(2 * np.pi * chords[k % 4][0] / 2 * tt) * (0.5 + 0.5 * np.cos(2 * np.pi * tt * 80 / 60)) * 0.6
        out[a:b] += ((s / 4 + bass * 0.5) * env).astype(np.float32)
    return out * (0.85 + 0.15 * np.sin(2 * np.pi * t / 13)).astype(np.float32)


def say_words(text):
    """On-screen words and the spoken words they become (for TTS and caption timing)."""
    toks = NT.tokens(text)
    spoken = []; owner = []
    for i, (_, sp) in enumerate(toks):
        for w in sp:
            spoken.append(w); owner.append(i)
    return [t for t, _ in toks], spoken, owner


def record(plan):
    import voice as V
    V.NARRATOR = COACH
    if os.environ.get("YT_VOICE"):
        V.GEMINI_VOICE = os.environ["YT_VOICE"]
    jobs = []
    for ci, c in enumerate(plan["chapters"]):
        for bi, b in enumerate(c["beats"]):
            if b["t"] == "say":
                _, sp, _ = say_words(b["text"])
                style = ("intriguing, a hint of suspense, pulling the viewer in" if c["id"] == "open" else
                         "excited reveal, then a satisfied smile" if b.get("pop") else
                         "conversational, clear and warm, like explaining at the board to a friend")
                jobs.append((ci, bi, " ".join(sp), style))
    if MOCK:
        return {(ci, bi): np.zeros(int(SR * (0.3 + len(t.split()) / 2.7)), np.float32) for ci, bi, t, _ in jobs}
    force = None
    for attempt in range(3):
        V.reset(force); out = {}
        try:
            for k in range(0, len(jobs), 12):
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


def word_times(clip, text):
    """Start time (s) of every on-screen word of `text` inside its voice clip."""
    shown, spoken, owner = say_words(text)
    dur = len(clip) / SR
    times = None
    if not MOCK:
        try:
            import voice as V
            al = V.align(clip, " ".join(spoken))
            if len(al) == len(spoken):
                times = [t for t, _ in al]
        except Exception as e:
            print("align failed:", str(e)[:100], flush=True)
    if times is None:                                         # proportional to characters
        L = sum(len(w) + 1 for w in spoken); acc = 0; times = []
        for w in spoken:
            times.append(dur * 0.95 * acc / max(1, L)); acc += len(w) + 1
    out = [None] * len(shown)
    for t, o in zip(times, owner):
        if out[o] is None:
            out[o] = t
    for i in range(len(out)):
        if out[i] is None:
            out[i] = out[i - 1] if i else 0.0
    return shown, out


def pages(shown, times):
    """Split a line into caption pages (<= ~11 words, break after punctuation)."""
    out, cur = [], []
    for i, w in enumerate(shown):
        cur.append(i)
        if len(cur) >= 11 or (len(cur) >= 5 and re.search(r"[.!?;:,]$", w) and len(cur) >= 7) or \
                (re.search(r"[.!?]$", w) and len(cur) >= 4):
            out.append(cur); cur = []
    if cur:
        if out and len(cur) < 3:
            out[-1] += cur
        else:
            out.append(cur)
    return out


# ------------------------------------------------------------------ timeline
def render(plan, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    clips = record(plan)
    shots, events, chapters, cues = [], [], [], []
    f = 0
    evals = {}

    def ev(fen):
        if fen not in evals:
            try:
                evals[fen] = EN.eval_white(fen, 14) if EN.available() else None
            except Exception:
                evals[fen] = None
        return evals[fen]

    last_pos = {"fen": chess.STARTING_FEN, "flip": False}
    for ci, c in enumerate(plan["chapters"]):
        chapters.append((f, c["title"]))
        title = None if c["id"] == "open" else c["title"]
        last_move = None; notes = []
        for bi, b in enumerate(c["beats"]):
            common = {"chapter": title, "chapter_id": c["id"], "ctx": b.get("ctx"), "flip": b.get("flip", last_pos["flip"])}
            if b["t"] == "sting":
                n = int(2.4 * FPS)
                shots.append(({"kind": "sting", "fen": last_pos["fen"], "flip": last_pos["flip"]}, n))
                events.append((f, R.whoosh(0.5), 0.8, False)); events.append((f + 6, R.shimmer(), 0.7, False)); f += n
                continue
            if b["t"] == "say":
                clip = clips[(ci, bi)]
                shown, times = word_times(clip, b["text"])
                last = last_move if b["fen"] == last_pos.get("fen") else None
                if b.get("pop") and (b.get("ctx") or {}).get("kind") == "talk":
                    notes.append(b["pop"])
                st = dict(common, kind="say", notes=list(notes), fen=b["fen"], squares=b.get("squares", []), arrows=b.get("arrows", []),
                          pop=b.get("pop"), eval=b.get("eval"), cp=ev(b["fen"]) if b.get("eval") else None,
                          last=last, ply=b.get("ply") if b.get("ply") is not None else (last_pos.get("ply") if last else None))
                dur = len(clip) / SR + 0.25 + float(b.get("pause") or 0)
                n_total = math.ceil(dur * FPS)
                events.append((f + 3, clip, 1.0, True))
                pg = pages(shown, times)
                marks = []
                for p in pg:
                    for k in p:
                        marks.append((int(times[k] * FPS) + 3, p, k))
                marks.sort(key=lambda x: x[0])
                pos = 0
                for mi, (fr, p, k) in enumerate(marks):
                    nxt = marks[mi + 1][0] if mi + 1 < len(marks) else n_total
                    if mi == 0 and fr > 0:
                        shots.append((dict(st, cap=([shown[j] for j in p], -1)), fr)); pos = fr
                    n = max(1, nxt - max(fr, pos))
                    shots.append((dict(st, cap=([shown[j] for j in p], p.index(k))), n)); pos = max(fr, pos) + n
                for p_i, p in enumerate(pg):                 # SRT cues
                    t0 = (f + 3) / FPS + times[p[0]]
                    t1 = (f + 3) / FPS + (times[pg[p_i + 1][0]] if p_i + 1 < len(pg) else len(clip) / SR)
                    cues.append((t0, t1, " ".join(shown[j] for j in p)))
                if pos < n_total:
                    shots.append((dict(st, cap=None), n_total - pos))
                f += max(n_total, pos)
                last_pos.update(fen=b["fen"], flip=b.get("flip"))
            elif b["t"] == "countdown":
                for left in range(b["seconds"], 0, -1):
                    shots.append((dict(common, kind="countdown", fen=b["fen"], prompt=b["prompt"], left=left,
                                       total=b["seconds"], hint=b.get("hint"), eval=False), FPS))
                    events.append((f, R.tick(left <= 3), 0.6, False)); f += FPS
                shots.append((dict(common, kind="countdown", fen=b["fen"], prompt=b["prompt"], left=0, total=b["seconds"],
                                   hint=b.get("hint"), eval=False), int(0.5 * FPS)))
                events.append((f, R.soft_hit(), 0.7, False)); f += int(0.5 * FPS)
                last_pos.update(fen=b["fen"], flip=b.get("flip"))
            elif b["t"] == "move":
                bd = chess.Board(b["fen"]); mv = chess.Move.from_uci(b["uci"])
                pc = bd.piece_at(mv.from_square); cap = bd.is_capture(mv); after = bd.copy(); after.push(mv)
                x0, y0 = sq_xy(mv.from_square, b["flip"]); x1, y1 = sq_xy(mv.to_square, b["flip"])
                steps = 7
                for k in range(1, steps + 1):
                    e = R.ease_in_out(k / steps)
                    shots.append((dict(common, kind="move", fen=b["fen"], hide=mv.from_square, last=[mv.from_square],
                                       float=(pc, x0 + (x1 - x0) * e, y0 + (y1 - y0) * e), eval=True, cp=ev(b["fen"]),
                                       ply=b["ply"] - 1), 1))
                f += steps
                events.append((f, R.place() + (R.soft_hit()[:len(R.place())] * 0.3 if cap else 0), 1.0, False))
                hold = int(0.75 * FPS)
                shots.append((dict(common, kind="move", fen=after.fen(), last=[mv.from_square, mv.to_square], eval=True,
                                   cp=ev(after.fen()), ply=b["ply"]), hold))
                f += hold
                last_move = [mv.from_square, mv.to_square]
                last_pos.update(fen=after.fen(), flip=b["flip"], ply=b["ply"])
    # end screen tail: keep the last frame (end-screen space) for at least 20 s in total
    end_start = next((fr for fr, t in reversed(chapters) if True), 0)
    tail = int(6 * FPS)
    if shots:
        last_state = dict(shots[-1][0], cap=None)
        shots.append((last_state, tail)); f += tail
    total = f
    # chapters (YouTube: first at 0:00, each >= 10 s)
    merged = []
    for fr, t in chapters:
        if merged and fr - merged[-1][0] < 11 * FPS:
            continue
        merged.append((fr, t if merged else "Intro"))
    while len(merged) > 1 and total - merged[-1][0] < 11 * FPS:
        merged.pop()
    # audio mix
    n = int(total / FPS * SR) + SR
    vt = np.zeros(n, np.float32); fx = np.zeros(n, np.float32)
    for fr, a, g, is_voice in events:
        s = int(fr / FPS * SR); a = np.asarray(a, np.float32)[: max(0, n - s)]
        (vt if is_voice else fx)[s:s + len(a)] += a * g
    bed = music(n) * 0.03
    talking = np.convolve((np.abs(vt) > 0.02).astype(np.float32), np.ones(SR // 4) / (SR // 4), "same")
    mix = vt + fx * 0.55 + bed * (1.6 - 0.9 * np.clip(talking, 0, 1))
    fade = int(SR * 3); mix[-fade:] *= np.linspace(1, 0, fade)
    mix = mix / max(1.0, float(np.max(np.abs(mix))) / 0.95)
    wav = os.path.join(out_dir, "audio.wav"); sf.write(wav, mix, SR)
    # frames
    fd = tempfile.mkdtemp(dir=out_dir); lst = []; last_key = None; last_png = None
    for i, (st, nf) in enumerate(shots):
        key = json.dumps(st, sort_keys=True, default=str)
        if key != last_key:
            png = os.path.join(fd, f"{i:06d}.png")
            compose(st, plan).save(png, compress_level=1)
            last_png, last_key = png, key
        lst.append((last_png, nf))
        if i % 500 == 0:
            print(f"render: {i}/{len(shots)} shots", flush=True)
    with open(os.path.join(fd, "list.txt"), "w") as fl:
        for p, nf in lst:
            fl.write(f"file '{p}'\nduration {nf / FPS:.4f}\n")
        fl.write(f"file '{lst[-1][0]}'\n")
    mp4 = os.path.join(out_dir, "video.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", os.path.join(fd, "list.txt"),
                    "-i", wav, "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-tune", "stillimage", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", mp4], check=True)
    subprocess.run(["rm", "-rf", fd])
    srt = os.path.join(out_dir, "captions.en.srt"); write_srt(cues, srt)
    return {"video": mp4, "duration": total / FPS, "chapters": [(fr / FPS, t) for fr, t in merged], "srt": srt,
            "cues": cues, "thumbs": thumbnails(plan, out_dir)}


def ts(s):
    ms = int(round(s * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def write_srt(cues, path, texts=None):
    with open(path, "w", encoding="utf-8") as f:
        for i, (a, b, t) in enumerate(cues, 1):
            f.write(f"{i}\n{ts(a)} --> {ts(max(b, a + 0.4))}\n{(texts[i - 1] if texts else t)}\n\n")


def fmt_ts(s):
    s = int(s); return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


# ------------------------------------------------------------------ thumbnails
def thumbnails(plan, out_dir):
    th = plan["thumb"]
    a = os.path.join(out_dir, "thumb_a.jpg"); b = os.path.join(out_dir, "thumb_b.jpg")
    thumb(th, th.get("style", "board_text"), th["text"], plan).save(a, quality=92)
    thumb(th, th.get("alt_style", "question"), th["alt_text"], plan).save(b, quality=92)
    return [a, b]


def thumb(th, style, text, plan):
    TW, TH = 1280, 720
    im = background().resize((TW, TH)); d = ImageDraw.Draw(im)
    bi = board_img(th["fen"], th.get("flip"), squares=tuple(th.get("squares", ())))
    words = text.upper()
    if style == "big_number":
        im.alpha_composite(bi.resize((600, 600), Image.LANCZOS), (650, 60))
        num = th.get("number") or "1 MOVE"
        text_fit(d, num.split()[0], F_BLACK, 250, (40, 40, 640, 330), fill=GOLD, align="center", max_lines=1, stroke=8)
        text_fit(d, " ".join(num.split()[1:]), F_BLACK, 64, (40, 300, 640, 380), align="center", max_lines=1, stroke=5)
        text_fit(d, words, F_BLACK, 84, (40, 420, 640, 680), align="center", max_lines=2, stroke=7)
    elif style == "question":
        im.alpha_composite(bi.resize((560, 560), Image.LANCZOS), (360, 140))
        text_fit(d, words, F_BLACK, 104, (30, 16, 1250, 140), align="center", max_lines=1, stroke=9)
        q = fnt(F_BLACK, 400); d.text((960, 170), "?", font=q, fill=GOLD, stroke_width=12, stroke_fill=BG)
        im.alpha_composite(R.mascot("thinking", 300), (30, 400))
    else:
        im.alpha_composite(bi.resize((640, 640), Image.LANCZOS), (610, 40))
        text_fit(d, words, F_BLACK, 118, (36, 50, 590, 470), max_lines=3, stroke=8)
        if th.get("badge"):
            chip(d, 40, 500, th["badge"].upper(), 38, bg=ORANGE, fg=(255, 255, 255), bold=F_BLACK)
        im.alpha_composite(R.mascot("thinking", 200), (390, 500))
    if style != "question":
        lg = logo(240); im.alpha_composite(lg, (40, TH - lg.height - 26))
    return im.convert("RGB")


if __name__ == "__main__":
    plan = json.load(open(sys.argv[1]))
    print(json.dumps({k: v for k, v in render(plan, sys.argv[2]).items() if k != "cues"}, indent=1, default=str))
