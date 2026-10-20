"""Duolingo-style puzzle reel: the animated StreakChess knight asks the puzzle, waits with you,
then explains the solution move by move.

python make_duo.py puzzle.json seed out.mp4 [level|tagfriend]
"""
import json, math, os, random, subprocess, sys
import numpy as np
import chess
from PIL import Image, ImageDraw, ImageFont
import soundfile as sf
import make_reel as R
from mascot_rig import Mascot

HERE = os.path.dirname(os.path.abspath(__file__))
W, H, FPS, SR = 1080, 1920, 30, 24000
F900 = os.path.join(HERE, "fonts", "Nunito-900.ttf")
F800 = os.path.join(HERE, "fonts", "Nunito-800.ttf")
INK = (35, 30, 52)
BG1, BG2 = (243, 239, 255), (234, 228, 255)
ORANGE, PURPLE, GREEN, RED = (242, 98, 46), (124, 108, 240), (88, 204, 2), (255, 75, 75)
VOICE = os.environ.get("DUO_VOICE", "am_puck")

clamp, eob, eo, eio = R.clamp, R.ease_out_back, R.ease_out, R.ease_in_out


def f(sz, heavy=True):
    return ImageFont.truetype(F900 if heavy else F800, sz)


def text_block(txt, size, color=INK, maxw=820, heavy=True, align="center"):
    fo = f(size, heavy); words = txt.split(); lines, cur = [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if fo.getlength(t) > maxw and cur:
            lines.append(cur); cur = w_
        else:
            cur = t
    lines.append(cur)
    lh = int(size * 1.15)
    wd = int(max(fo.getlength(l) for l in lines)) + 6
    im = Image.new("RGBA", (wd, lh * len(lines) + 8), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for i, l in enumerate(lines):
        x = (wd - fo.getlength(l)) / 2 if align == "center" else 0
        d.text((x, i * lh), l, font=fo, fill=color)
    return im


def bubble(content, tail="down", tail_x=0.5, pad=34):
    """White speech bubble with thick outline (Duolingo look) around an RGBA content image."""
    w, h = content.width + 2 * pad, content.height + 2 * pad
    T = 34
    im = Image.new("RGBA", (w + 20, h + T + 20), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    ox, oy = 10, 10 if tail != "up" else 10 + T
    # shadow
    d.rounded_rectangle([ox, oy + 8, ox + w, oy + h + 8], 38, fill=(215, 196, 240, 255))
    d.rounded_rectangle([ox, oy, ox + w, oy + h], 38, fill=(255, 255, 255, 255), outline=(220, 214, 245, 255), width=5)
    if tail == "down":
        tx = ox + w * tail_x
        d.polygon([(tx - 26, oy + h - 3), (tx + 26, oy + h - 3), (tx - 6, oy + h + T)], fill=(255, 255, 255, 255))
    elif tail == "left":
        ty = oy + h * 0.55
        im2 = Image.new("RGBA", (im.width + T, im.height), (0, 0, 0, 0)); im2.alpha_composite(im, (T, 0)); im = im2
        d = ImageDraw.Draw(im); ox += T
        d.polygon([(ox + 3, ty - 24), (ox + 3, ty + 24), (ox - T, ty + 10)], fill=(255, 255, 255, 255))
    im.alpha_composite(content, (ox + pad, oy + pad))
    return im


def music(total):
    """Light, bouncy pentatonic pluck loop (original, generated)."""
    n = int(SR * (total + 1)); out = np.zeros(n, np.float32)
    notes = [523.25, 587.33, 659.25, 783.99, 880.0, 783.99, 659.25, 587.33]
    bass = [130.81, 130.81, 164.81, 146.83]
    step = 60 / 112 / 2
    t = 0; i = 0
    while t < total:
        k = int(t * SR)
        p = R.tone(notes[(i * 3) % len(notes)] * (1 if (i // 8) % 2 == 0 else 1.122), 0.28, 14, 0.18)
        out[k:k + len(p)] += p[: n - k]
        if i % 4 == 0:
            b = R.tone(bass[(i // 4) % 4], 0.45, 6, 0.25); out[k:k + len(b)] += b[: n - k]
        t += step; i += 1
    return out


THEME_LINES = [
    ("smotheredMate", "Smothered by its own pieces!"),
    ("backRankMate", "The king is stuck on the back rank!"),
    ("sacrifice", "A sacrifice to rip the king open!"),
    ("attraction", "We lured the king into the net!"),
    ("deflection", "We deflected the defender!"),
    ("fork", "A fork, two targets at once!"),
    ("pin", "That piece was pinned!"),
    ("skewer", "A skewer!"),
    ("discoveredAttack", "A discovered attack!"),
    ("promotion", "Promote and win!"),
    ("hangingPiece", "A free piece!"),
]

HOOKS = {
    "basic": ["Hey you! Yes, you. Can you solve this one?", "Quick! Most beginners miss this. Do you?",
              "Easy one today... or is it?"],
    "intermediate": ["Psst! Only three percent of club players find this.", "Ready for a real challenge?",
                     "This one tricks a lot of players. Let's see!"],
    "advanced": ["Okay genius, this one is master level.", "Think you're strong? Prove it.",
                 "Only the sharpest calculators find this."],
    "tagfriend": ["Tag a friend and see who solves this first!", "You versus your chess buddy. Who's faster?"],
}


def build(P, seed, out, mode="level"):
    rng = random.Random(f"{P.get('id')}-{seed}-{mode}")
    LV = R.LEVELS[P["level"]]
    if "fen" in P:
        board = chess.Board(P["fen"]); ms = P["moves"].split(); board.push(chess.Move.from_uci(ms[0])); sol = ms[1:]
    else:
        board = chess.Board()
        for m in P["pgn"].split(): board.push_san(m)
        sol = P["sol"]
    last = board.peek(); flip = board.turn == chess.BLACK
    side = "Black" if flip else "White"
    moves = [chess.Move.from_uci(u) for u in sol]
    b2 = board.copy(); sans = []
    nb = board.copy(); nb.fullmove_number = 1; nums = []
    for i, m in enumerate(moves):
        nums.append(f"{nb.fullmove_number}." if nb.turn == chess.WHITE else f"{nb.fullmove_number}...")
        sans.append(b2.san(m)); b2.push(m); nb.push(m)
    mate_n = (len(moves) + 1) // 2 if b2.is_checkmate() else None
    goal_txt = f"Mate in {mate_n}!" if mate_n else "Find the best move!"
    goal_say = f"mate in {R.NUM[mate_n]}" if mate_n else "the best move"
    COUNT = LV["count"]
    themes = (P.get("themes") or "").split()
    finale = next((l for k, l in THEME_LINES if k in themes), "No escape squares left!" if mate_n else "And that wins!")

    hook = rng.choice(HOOKS["tagfriend" if mode == "tagfriend" else P["level"]])
    numw = {8: "eight", 10: "ten", 12: "twelve"}[COUNT]
    seg_txt = {
        "hook": hook,
        "intro": f"{side} to move. Find {goal_say}. You've got {numw} seconds. Go!",
        "lets": "Time's up! Let's see.",
    }
    for i, s in enumerate(sans):
        seg_txt[f"m{i}"] = R.san_say(s)
    seg_txt["finale"] = finale
    seg_txt["cta"] = ("Now tag a friend and see if they can do it! " if mode == "tagfriend" else "Did you get it? ") + \
        "Train with me every day on StreakChess. It's free! Link in bio."

    # ---- voice (playful: slightly higher & faster)
    def voice(txt):
        a = R.tts(txt, voice=VOICE, speed=1.05)
        k = 1.06
        idx = np.arange(0, len(a) - 1, k)
        return np.interp(idx, np.arange(len(a)), a).astype(np.float32)
    A = {k: voice(v) for k, v in seg_txt.items()}
    D = {k: len(v) / SR for k, v in A.items()}

    # ---- timeline
    T = {}; t = 0.0
    def add(k, dur): nonlocal t; T[k] = (t, t + dur); t += dur
    add("hook", D["hook"] + 0.5)
    add("intro", D["intro"] + 0.3)
    add("count", COUNT)
    add("lets", D["lets"] + 0.2)
    for i in range(len(sans)):
        add(f"m{i}", max(D[f"m{i}"] + 0.25, 1.3))
    add("finale", D["finale"] + 0.9)
    add("cta", D["cta"] + 1.0)
    total = t

    # ---- audio
    n = int(SR * (total + 0.3)); vo = np.zeros(n, np.float32); sfx = np.zeros(n, np.float32)
    def put(buf, a, at, g=1.0):
        i = int(at * SR); j = min(n, i + len(a)); buf[i:j] += a[: j - i] * g
    vstart = {}
    for k in A:
        st = T[k][0] + (0.15 if k != "hook" else 0.35); vstart[k] = st; put(vo, A[k], st)
    put(sfx, R.pop(), 0.1); put(sfx, R.whoosh(), T["intro"][0] - 0.15); put(sfx, R.whoosh(), T["cta"][0] - 0.15)
    for i in range(COUNT): put(sfx, R.tick(i >= COUNT - 3), T["count"][0] + i)
    put(sfx, R.ding(), T["lets"][0], 0.6)
    for i in range(len(sans)): put(sfx, R.tone(520 if i % 2 == 0 else 420, 0.08, 40, 0.3), T[f"m{i}"][0] + 0.45)
    if mate_n: put(sfx, R.ding(), T["finale"][0], 0.9)
    mus = music(total)[:n]
    env = np.convolve((np.abs(vo) > 0.01).astype(np.float32), np.ones(4000) / 4000, "same")
    mix = vo + sfx * 0.9 + mus * (0.55 - 0.35 * np.clip(env * 3, 0, 1))
    mix = mix / (np.abs(mix).max() + 1e-6) * 0.95
    wav = out.replace(".mp4", ".wav"); sf.write(wav, mix, SR)

    # lip-sync envelope per frame
    hop = SR // FPS
    vo_env = np.array([np.sqrt(np.mean(vo[i * hop:(i + 1) * hop] ** 2)) for i in range(int(total * FPS) + 2)])
    vo_env = np.clip(vo_env / (np.percentile(vo_env[vo_env > 0.005], 90) + 1e-6 if (vo_env > 0.005).any() else 1), 0, 1)

    # ---- static art
    mas = Mascot()
    logo = Image.open(os.path.join(HERE, "assets", "logo_h.png")).convert("RGBA")
    logo = logo.crop(logo.getbbox())
    logo = logo.resize((360, int(logo.height * 360 / logo.width)), Image.LANCZOS)
    chip = R.pill(f"{LV['name']} LEVEL", 34, LV["color"], fg=(255, 255, 255))
    states = [board.copy()]
    for m in moves:
        s2 = states[-1].copy(); s2.push(m); states.append(s2)
    bcache = {}

    def board_img(tt):
        start = T["m0"][0] + 0.35
        if tt < start:
            k = ("start",)
            if k not in bcache: bcache[k] = R.card(R.draw_board(board, flip, (last.from_square, last.to_square)))
            return bcache[k]
        i = 0
        for j in range(len(moves)):
            if tt >= T[f"m{j}"][0] + 0.35: i = j
        m = moves[i]; prog = eio((tt - T[f"m{i}"][0] - 0.35) / 0.45)
        st = states[i]
        if prog >= 1:
            red = states[i + 1].king(states[i + 1].turn) if (i == len(moves) - 1 and mate_n) else None
            k = ("done", i, red)
            if k not in bcache:
                im = R.draw_board(states[i + 1], flip, (m.from_square, m.to_square), red=red)
                R.draw_arrow(im, m.from_square, m.to_square, flip, (242, 98, 46, 170) if i % 2 == 0 else (90, 90, 110, 120))
                bcache[k] = R.card(im)
            return bcache[k]
        im = R.draw_board(st, flip, (m.from_square,), hide=m.from_square)
        x1, y1 = R.sq_xy(m.from_square, flip); x2, y2 = R.sq_xy(m.to_square, flip)
        if prog > 0.5 and st.piece_at(m.to_square):
            tx, ty = R.sq_xy(m.to_square, flip)
            light = (chess.square_file(m.to_square) + chess.square_rank(m.to_square)) % 2 == 1
            ImageDraw.Draw(im).rectangle([tx, ty, tx + R.SQ, ty + R.SQ], fill=R.LIGHT if light else R.DARKSQ)
        hop_y = -40 * math.sin(math.pi * prog)
        im.alpha_composite(R.piece_img(st.piece_at(m.from_square), R.SQ), (int(x1 + (x2 - x1) * prog), int(y1 + (y2 - y1) * prog + hop_y)))
        return R.card(im)

    bg_tile = Image.new("RGB", (W + 240, H + 240), BG1); dd = ImageDraw.Draw(bg_tile)
    for i in range(0, W + 240, 120):
        for j in range(0, H + 240, 120):
            if (i // 120 + j // 120) % 2 == 0: dd.rectangle([i, j, i + 120, j + 120], fill=BG2)
    conf = [dict(x=rng.uniform(0, W), y=rng.uniform(-500, 0), vx=rng.uniform(-150, 150), vy=rng.uniform(150, 550),
                 c=rng.choice([ORANGE, PURPLE, GREEN, (255, 200, 40), (255, 90, 140)]), s=rng.randint(14, 28)) for _ in range(110)]

    def bubble_for(tt):
        """Returns (bubble image content) for the current moment."""
        for k in ("hook", "intro"):
            if T[k][0] <= tt < T[k][1]:
                txt = seg_txt[k] if k == "hook" else f"{side} to move. {goal_txt}"
                return text_block(txt.replace("three percent", "3%"), 60 if k == "hook" else 58, maxw=760 if k == "hook" else 520)
        if T["count"][0] <= tt < T["count"][1]:
            remain = COUNT - int(tt - T["count"][0])
            col = RED if remain <= 3 else INK
            num = text_block(str(remain), 120, col, heavy=True)
            lab = text_block("seconds left!" if remain > 1 else "second left!", 38, (120, 110, 150), maxw=400)
            c = Image.new("RGBA", (max(380, num.width, lab.width), num.height + lab.height), (0, 0, 0, 0))
            c.alpha_composite(num, ((c.width - num.width) // 2, 0)); c.alpha_composite(lab, ((c.width - lab.width) // 2, num.height - 6))
            return c
        if T["lets"][0] <= tt < T["lets"][1]:
            return text_block("Time's up! Let's see...", 58, maxw=520)
        for i in range(len(sans)):
            if T[f"m{i}"][0] <= tt < T[f"m{i}"][1]:
                mover = "Black" if (states[i].turn == chess.BLACK) else "White"
                c1 = text_block(f"{nums[i]} {sans[i]}", 92, ORANGE if i % 2 == 0 else INK)
                c2 = text_block(("Check!" if "+" in sans[i] else "Checkmate!" if "#" in sans[i] else f"{mover} plays"), 40, (120, 110, 150))
                c = Image.new("RGBA", (max(c1.width, c2.width), c1.height + c2.height + 6), (0, 0, 0, 0))
                c.alpha_composite(c1, ((c.width - c1.width) // 2, 0)); c.alpha_composite(c2, ((c.width - c2.width) // 2, c1.height + 6))
                return c
        if T["finale"][0] <= tt < T["finale"][1]:
            return text_block(finale, 56, maxw=520)
        return None

    # ---- render
    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-i", wav, "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out],
                            stdin=subprocess.PIPE)
    BOARD_CY = 1230
    for fi in range(int(total * FPS)):
        tt = fi / FPS
        off = int(tt * 25) % 240
        fr = bg_tile.crop((off, off, off + W, off + H)).convert("RGBA")
        mouth = float(vo_env[fi]) * (0.7 + 0.3 * math.sin(tt * 37))
        # --- scene parameters
        if tt < T["hook"][1]:
            lt = tt
            sc = 1.25 * eob(lt / 0.55); mx, my = W / 2, 1640
            mood = "excited"; look = (0.1, -0.1); bounce = 18 * abs(math.sin(lt * 5)) * (lt < 1.2)
            board_alpha = 0; tilt = 4 * math.sin(lt * 3)
        elif tt < T["count"][0]:
            lt = tt - T["intro"][0]; k = eio(lt / 0.6)
            sc = 1.25 + (0.54 - 1.25) * k; mx = W / 2 + (215 - W / 2) * k; my = 1640 + (720 - 1640) * k
            mood = "neutral"; look = (0.7, 0.6); bounce = 0; board_alpha = k; tilt = 0
        elif tt < T["count"][1]:
            lt = tt - T["count"][0]
            sc, mx, my = 0.54, 215, 720
            mood = "thinking"; look = (0.6 * math.sin(lt * 1.3), 0.6); bounce = 10 * max(0, 1 - (lt % 1) * 5)
            board_alpha = 1; tilt = 3 * math.sin(lt * 2)
        elif tt < T["cta"][0]:
            lt = tt - T["lets"][0]
            sc, mx, my = 0.54, 215, 720
            mood = "excited"; look = (0.7, 0.7); bounce = 0; board_alpha = 1; tilt = 0
            if tt >= T["finale"][0]:
                ft = tt - T["finale"][0]
                mood = "star" if mate_n else "happy_closed"; bounce = 60 * abs(math.sin(ft * 6)) * max(0, 1 - ft / 1.6)
        else:
            lt = tt - T["cta"][0]; k = eio(lt / 0.6)
            sc = 0.54 + (1.0 - 0.54) * k; mx = 215 + (W / 2 - 215) * k; my = 720 + (1430 - 720) * k
            mood = "excited"; look = (0.0, -0.1); bounce = 8 * abs(math.sin(lt * 4)); board_alpha = 1 - k; tilt = 3 * math.sin(lt * 3)

        # board
        if board_alpha > 0.01:
            c = board_img(tt)
            yo = (1 - board_alpha) * 900
            R.paste_center(fr, c, W / 2, BOARD_CY + yo, 0.93, min(1, board_alpha * 1.4))
        # confetti on finale
        if T["finale"][0] <= tt < T["finale"][1] + 1.5 and mate_n:
            ft = tt - T["finale"][0]; d = ImageDraw.Draw(fr)
            for p in conf:
                x = p["x"] + p["vx"] * ft; y = p["y"] + p["vy"] * ft + 320 * ft * ft
                if -40 < y < H: d.rectangle([x, y, x + p["s"], y + p["s"] * 0.55], fill=p["c"])
        # mascot
        squash = 0.6 * math.sin(tt * 10) if bounce > 1 else 0.0
        mimg = mas.render(tt, mouth=mouth, mood=mood, look=look, bounce=bounce, tilt=tilt, squash=squash * 0.3)
        mw = int(mimg.width * sc); mh = int(mimg.height * sc)
        if mw > 10:
            m2 = mimg.resize((mw, mh), Image.BILINEAR)
            fr.alpha_composite(m2, (int(mx - mw / 2), int(my - mh)))
        # header
        fr.alpha_composite(logo, ((W - logo.width) // 2, 40))
        R.paste_center(fr, chip, W / 2, 40 + logo.height + 45)
        # speech bubble
        content = bubble_for(tt)
        if content is not None:
            if tt < T["hook"][1]:
                b = bubble(content, "down", 0.55); R.paste_center(fr, b, W / 2, 500, eob((tt - 0.25) / 0.35))
            else:
                b = bubble(content, "left")
                seg_start = max([v[0] for v in T.values() if v[0] <= tt])
                R.paste_center(fr, b, 430 + b.width / 2, 500, eob((tt - seg_start) / 0.3))
        # CTA
        if tt >= T["cta"][0]:
            lt = tt - T["cta"][0]
            head = bubble(text_block("Did you get it?" if mode != "tagfriend" else "Tag a friend!", 70), "down", 0.5)
            R.paste_center(fr, head, W / 2, 430, eob((lt - 0.3) / 0.4))
            R.paste_center(fr, R.pill("100% FREE TO PLAY", 42, GREEN, fg=(255, 255, 255)), W / 2, 1520, eob((lt - 1.2) / 0.4))
            R.paste_center(fr, R.pill("Founder offer: first 500 accounts", 38, PURPLE, fg=(255, 255, 255)), W / 2, 1615, eob((lt - 1.8) / 0.4))
            R.paste_center(fr, R.pill("streakchess.com", 64, ORANGE, fg=(255, 255, 255), padx=50, pady=20), W / 2, 1740,
                           eob((lt - 2.4) / 0.4) * (1 + 0.03 * math.sin(lt * 6)))
        proc.stdin.write(fr.convert("RGB").tobytes())
    proc.stdin.close(); proc.wait(); os.remove(wav)

    cap_first = rng.choice(R.TAG_CAPTIONS) if mode == "tagfriend" else hook.replace("three percent", "3%")
    ig = (f"{cap_first}\n{LV['name'].title()} level puzzle. {side} to move, {goal_say}.\n\n"
          + ("Comment the move and tag a friend to challenge them!\n\n" if mode == "tagfriend" else "Comment your move before watching the solution!\n\n")
          + "Train your calculation every day on StreakChess. Free to play. Founder offer for the first 500 accounts, link in bio.\n\n"
          + " ".join(R.hashtags(rng)))
    open(out.replace(".mp4", ".txt"), "w").write(ig)
    return dict(mode=mode, puzzle=P.get("id"), level=P["level"], rating=P.get("rating"), hook=hook, sans=sans,
                duration=round(total, 1))


if __name__ == "__main__":
    P = json.load(open(sys.argv[1]))
    print(json.dumps(build(P, int(sys.argv[2]), sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "level"), indent=1))
