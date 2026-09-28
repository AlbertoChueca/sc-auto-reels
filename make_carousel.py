"""Daily 'How many can you solve?' carousel: cover + 5 puzzles + answers + CTA (8 slides, 4:5).

Each slide is rendered as a PNG and turned into a short silent mp4, so it can be uploaded
with the same resumable video upload used for reels (image carousels would need public URLs).
"""
import os, random, subprocess
import chess
from PIL import Image, ImageDraw
import make_reel as R

CW, CH = 1080, 1350


def bg():
    return R.bg_dark().convert("RGBA").resize((CW, int(R.H * CW / R.W))).crop((0, 200, CW, 200 + CH))


def puzzle_state(P):
    board = chess.Board(P["fen"]); ms = P["moves"].split()
    board.push(chess.Move.from_uci(ms[0]))
    moves = [chess.Move.from_uci(u) for u in ms[1:]]
    b2 = board.copy(); nb = board.copy(); nb.fullmove_number = 1; line = []
    for i, m in enumerate(moves):
        num = f"{nb.fullmove_number}. " if nb.turn == chess.WHITE else (f"{nb.fullmove_number}... " if i == 0 else "")
        line.append(num + nb.san(m)); nb.push(m); b2.push(m)
    mate_n = (len(moves) + 1) // 2 if b2.is_checkmate() else None
    return board, " ".join(line), mate_n


def cover(n):
    im = bg()
    R.paste_center(im, R.logo_glow("logo_h_white.png", 420, 30), CW / 2, 110)
    R.paste_center(im, R.gold_pill(f"{n} PUZZLES", 110, padx=60, pady=24).rotate(-3, expand=True), CW / 2, 380)
    R.paste_center(im, R.text_img("How many can you solve?", 64, R.WHITE), CW / 2, 560)
    R.paste_center(im, R.mascot("thinking", 560), CW / 2, 930)
    R.paste_center(im, R.pill("SWIPE  >>", 44, R.WHITE, fg=R.NAVY), CW / 2, 1255)
    return im


def puzzle_slide(i, n, P):
    board, _, mate_n = puzzle_state(P)
    flip = board.turn == chess.BLACK
    LV = R.LEVELS[P["level"]]
    im = bg()
    R.paste_center(im, R.logo_glow("logo_h_white.png", 300, 20), CW / 2, 70)
    R.paste_center(im, R.text_img(f"PUZZLE {i}/{n}", 70, R.WHITE), CW / 2, 175)
    chips = [R.pill(LV["name"], 32, LV["color"], fg=R.NAVY),
             R.pill(f"{'BLACK' if flip else 'WHITE'} TO MOVE", 32, R.WHITE, fg=R.NAVY),
             R.gold_pill(f"MATE IN {mate_n}" if mate_n else "BEST MOVE", 32, padx=30)]
    gap = 16; tw = sum(c.width for c in chips) + gap * 2; x = (CW - tw) / 2
    for c in chips:
        R.paste_center(im, c, x + c.width / 2, 265); x += c.width + gap
    last = board.peek()
    card = R.card(R.draw_board(board, flip, (last.from_square, last.to_square)))
    sh, _ = R.shadowed(card)
    R.paste_center(im, sh, CW / 2, 800, 0.9)
    return im


def answers_slide(puzzles):
    im = bg()
    R.paste_center(im, R.logo_glow("logo_h_white.png", 300, 20), CW / 2, 70)
    R.paste_center(im, R.gold_pill("ANSWERS", 90, padx=56, pady=20), CW / 2, 230)
    y = 400
    for i, P in enumerate(puzzles, 1):
        _, line, _ = puzzle_state(P)
        row = Image.new("RGBA", (960, 150), (0, 0, 0, 0)); d = ImageDraw.Draw(row)
        d.rounded_rectangle([0, 0, 959, 149], 32, fill=(34, 28, 66, 255), outline=R.GOLD, width=3)
        row.alpha_composite(R.text_img(f"{i}", 64, R.GOLD), (30, 30))
        t = R.text_img(line, 46 if len(line) < 34 else 38, R.WHITE)
        row.alpha_composite(t, (110, (150 - t.height) // 2))
        R.paste_center(im, row, CW / 2, y); y += 170
    R.paste_center(im, R.text_img("How many did you get? Comment your score!", 44, (220, 210, 250)), CW / 2, 1270)
    return im


def cta_slide():
    im = Image.new("RGBA", (CW, CH), R.NAVY + (255,))
    R.paste_center(im, R.logo_glow("logo_v_white.png", 480, 60), CW / 2, 400)
    R.paste_center(im, R.outline_pill("100% FREE TO PLAY", 46, color=(120, 220, 160)), CW / 2, 760)
    f = Image.new("RGBA", (900, 230), (0, 0, 0, 0)); d = ImageDraw.Draw(f)
    d.rounded_rectangle([2, 2, 897, 227], 40, fill=(34, 28, 66, 255), outline=R.GOLD, width=4)
    fb = R.gold_pill("FOUNDER OFFER", 38, padx=30, pady=10); f.alpha_composite(fb, ((900 - fb.width) // 2, 28))
    ft = R.text_img("Premium for the first 500 accounts", 48, R.WHITE); f.alpha_composite(ft, ((900 - ft.width) // 2, 120))
    R.paste_center(im, f, CW / 2, 980)
    R.paste_center(im, R.gold_pill("streakchess.com", 66, padx=56, pady=24), CW / 2, 1200)
    return im


def to_mp4(png, mp4, secs=5):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", png, "-f", "lavfi", "-i",
                    "anullsrc=r=44100:cl=stereo", "-t", str(secs), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-r", "30", "-c:a", "aac", "-shortest", "-movflags", "+faststart", mp4], check=True)


def build_carousel(puzzles, outdir, seed):
    os.makedirs(outdir, exist_ok=True)
    slides = [cover(len(puzzles))] + [puzzle_slide(i, len(puzzles), P) for i, P in enumerate(puzzles, 1)]
    slides += [answers_slide(puzzles), cta_slide()]
    vids = []
    for k, im in enumerate(slides):
        png = os.path.join(outdir, f"slide{k:02d}.png"); im.convert("RGB").save(png)
        mp4 = png.replace(".png", ".mp4"); to_mp4(png, mp4, 6 if 0 < k <= len(puzzles) else 4); vids.append(mp4)
    rng = random.Random(f"carousel-{seed}")
    caption = (f"{len(puzzles)} puzzles, from beginner to advanced. How many can you solve? 🧠\n\n"
               "Comment your score (e.g. 4/5) and tag a friend to compare! Answers on the last slides.\n\n"
               "Train your calculation every day on StreakChess. Free to play. Founder offer for the first 500 accounts, link in bio.\n\n"
               + " ".join(R.hashtags(rng)))
    return vids, caption
