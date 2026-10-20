"""Calculation-tip reel: Vektor teaches ONE real calculation habit, shows it on a real position (checks and captures
are computed by python-chess, not invented), then the viewer applies it to the puzzle.
Educational reels get saved and shared far more than plain puzzles, which is what grows an account.

python make_tip.py puzzle.json seed out.mp4      (needs GEMINI_API_KEY)
TIP_MOCK=1 ...                                    (offline test)
"""
import json, math, os, random, re, subprocess, sys
import chess
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter
import make_reel as R
import make_hype as HY

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "tip_log.json")
W, H, FPS, SR = HY.W, HY.H, HY.FPS, HY.SR

# Genuine, widely taught calculation habits (no invented statistics).
TIPS = [
    ("cct", "Checks, captures, threats", "Before every move, look at all checks, then all captures, then all threats."),
    ("forcing", "Forcing moves first", "Calculate the most forcing moves first: they leave your opponent the fewest replies."),
    ("blunder", "The blunder check", "Before you press the piece, ask: what is my opponent's best reply?"),
    ("candidates", "Find 2-3 candidates", "List two or three candidate moves before you calculate any of them deeply."),
    ("loose", "Loose pieces drop off", "Undefended pieces are targets. Spot them for both sides."),
    ("count", "Count attackers", "Before a capture, count attackers and defenders on that square."),
    ("king", "Look at the king", "Check how many defenders the king has and whether the back rank is weak."),
    ("end", "See the final position", "Calculate until the position is quiet and picture the final position clearly."),
    ("threat", "What does my opponent want?", "After every enemy move, ask what it threatens before making your plan."),
    ("overload", "Overloaded defenders", "A piece defending two things cannot do both. Attack one of them."),
    ("visual", "Move pieces in your head", "Practise visualising moves without touching the pieces: that is calculation."),
    ("slow", "Slow down when it's sharp", "In sharp positions use your time: one careful minute beats ten fast mistakes."),
]

PROMPT = """You write the script of a 15-20 second "calculation tip" segment for a chess reel. Vektor (a friendly chess
knight mascot) teaches the tip to chess players aged 8-12 and their parents, then invites them to try it on a puzzle.
TIP: {name} - {idea}
{brief}
Rules: exactly 3 short lines of narration (total 30-45 words), spoken style, numbers as words, no chess notation,
no invented statistics or claims. Line 1 = hook/why it matters. Line 2 = how to do it. Line 3 = "now you try"
handing over to the puzzle. screen_hook: max 6 words, curiosity (no emoji). caption_hook: max 10 words, one emoji max.
Return JSON: {{"lines": [str, str, str], "screen_hook": str, "caption_hook": str}}"""


def pick_tip(seed):
    log = json.load(open(LOG)) if os.path.exists(LOG) else []
    recent = [e.get("tip") for e in log[-6:]]
    pool = [t for t in TIPS if t[0] not in recent] or TIPS
    return random.Random(seed).choice(pool)


def write_script(tip):
    import reviewer
    try:
        import agents
        brief = agents._brief("hook")
    except Exception:
        brief = ""
    res = reviewer._ask([{"text": PROMPT.format(name=tip[1], idea=tip[2], brief=brief)}], 0.8)
    lines = [l for l in res.get("lines", []) if isinstance(l, str) and l.strip()]
    if len(lines) != 3 or re.search(r"\b[a-h][1-8]\b|\d{2,}|percent|%", " ".join(lines)):
        raise RuntimeError("tip script invalid")
    return res


def forcing(board):
    """Real checks and captures for the side to move (python-chess)."""
    checks, caps = [], []
    for m in board.legal_moves:
        if board.gives_check(m): checks.append(m)
        elif board.is_capture(m): caps.append(m)
    return checks[:4], caps[:5]


def build(P, seed, out, mode="level", arms=None):
    arms = arms or {}
    mock = os.environ.get("TIP_MOCK") == "1"
    tip = pick_tip(seed)
    script = ({"lines": [f"Strong players have one habit. {tip[1]}.", tip[2], "Now you try. Find the best move."],
               "screen_hook": tip[1], "caption_hook": "Save this calculation tip ♟️"} if mock else write_script(tip))
    print("Tip reel:", tip[1], flush=True)

    # the position: the puzzle after the opponent's move (same as the puzzle segment)
    if "fen" in P:
        board = chess.Board(P["fen"]); board.push(chess.Move.from_uci(P["moves"].split()[0]))
    else:
        board = chess.Board()
        for m in P["pgn"].split(): board.push_san(m)
    flip = board.turn == chess.BLACK
    checks, caps = forcing(board)
    last = board.peek()

    def board_img(arrows):
        im = R.draw_board(board, flip, (last.from_square, last.to_square))
        for m, col in arrows:
            R.draw_arrow(im, m.from_square, m.to_square, flip, col)
        return R.card(im)
    cards = [board_img([]), board_img([(m, (230, 60, 60, 200)) for m in checks]),
             board_img([(m, (230, 60, 60, 200)) for m in checks] + [(m, (242, 150, 46, 190)) for m in caps])]
    legend = ["", f"{len(checks)} CHECK{'S' if len(checks) != 1 else ''}" if checks else "NO CHECKS",
              f"{len(caps)} CAPTURE{'S' if len(caps) != 1 else ''}" if caps else "NO CAPTURES"]

    import voice
    voice.reset()
    puzzle_mp4 = out.replace(".mp4", "_puzzle.mp4"); tip_mp4 = out.replace(".mp4", "_tip.mp4")
    A = voice.say_many(script["lines"], speed=1.08, styles=["curious, inviting", "clear, like a great coach",
                                                            "excited, handing over the challenge"], one_take=True)
    tip_len = sum(max(len(a) / SR + 0.4, 2.2) for a in A)
    import strategy
    meta = HY.build(P, seed, puzzle_mp4, mode=mode, skip_hook=True, keep_voice=True,
                    cta_lead="Save this tip and use it in your next game! ",
                    think_factor=strategy.THINK_FACTOR.get(arms.get("think_time"), 1.0),
                    style={"follow_line": "Follow for a new tip every week", "share_line": "Send this to a chess friend"},
                    max_len=float(os.environ.get("REEL_MAX_SECONDS", "55")) - tip_len,
                    reveal=arms.get("reveal", "in_video") != "comments")

    durs = [max(len(a) / SR + 0.4, 2.2) for a in A]
    starts = np.cumsum([0.0] + durs[:-1]); total = float(sum(durs)) + 0.3
    n = int(SR * (total + 0.5)); vo = np.zeros(n, np.float32); fx = np.zeros(n, np.float32)

    def put(buf, a, at, g=1.0):
        i = int(at * SR)
        if i >= n: return
        j = min(n, i + len(a)); buf[i:j] += a[: j - i] * g
    for i, a in enumerate(A):
        put(vo, a, starts[i] + 0.15)
        if i: put(fx, R.shimmer([659.3, 784.0][i % 2]), starts[i] - 0.05, 0.6)
    tb = np.arange(n) / SR
    pad = sum(np.sin(2 * np.pi * f * tb) for f in (146.8, 220.0, 293.7)) * 0.025 * np.clip(tb / 1.5, 0, 1)
    mix = HY.dehiss(np.tanh((vo * 1.15 + fx + pad.astype(np.float32)) * 1.1) * 0.92)
    wav = out.replace(".mp4", "_t.wav"); sf.write(wav, mix, SR)
    hop = SR // FPS
    env = np.array([np.sqrt(np.mean(vo[i * hop:(i + 1) * hop] ** 2)) for i in range(int(total * FPS) + 2)])
    env = np.clip(env / (np.percentile(env[env > 0.004], 85) + 1e-6), 0, 1) if (env > 0.004).any() else env * 0
    words = []
    for i, line in enumerate(script["lines"]):
        for ts, w in voice.align(A[i], line):
            words.append((i, starts[i] + 0.15 + ts, w))

    y = np.linspace(0, 1, H)[:, None, None]
    bg = Image.fromarray(((np.array([22, 18, 40]) * (1 - y) + np.array([9, 7, 18]) * y) * np.ones((1, W, 3))).astype(np.uint8)).convert("RGBA")
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([W * 0.05, H * 0.25, W * 0.95, H * 0.7], fill=(120, 90, 255, 60))
    bg.alpha_composite(glow.filter(ImageFilter.GaussianBlur(150)))
    from mascot_rig import Mascot
    mas = Mascot()
    badge = R.pill("CALCULATION TIP", 34, (20, 16, 28), fg=HY.YEL, padx=30, pady=12)
    badge_y = HY.SAFE_TOP + badge.height // 2
    hook_img = HY.fit_phrase(script.get("screen_hook", tip[1]).split(), 92, 900, 2)
    hook_y = badge_y + badge.height // 2 + 30 + (hook_img.height + 70) // 2
    HOOK_T = 2.3
    title = R.pill(tip[1].upper()[:30], 40, HY.YEL, fg=HY.INK, padx=36, pady=14)
    SC, CY = 0.80, 960
    cards_s = [c.resize((int(c.width * SC), int(c.height * SC)), Image.LANCZOS) for c in cards]

    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-i", wav, "-shortest"] + HY.enc_args(tip_mp4), stdin=subprocess.PIPE)
    for fi in range(int(total * FPS)):
        t = fi / FPS
        i = min(len(starts) - 1, int(np.searchsorted(starts, t, side="right") - 1)); lt = t - starts[i]
        fr = bg.copy()
        hook_on = t < HOOK_T + 0.3
        card = cards_s[min(i, 2)]
        enter = HY.eob(min(1, max(0, (t - HOOK_T) / 0.45)))   # board slides in after the hook (no overlap)
        if t >= HOOK_T:
            R.paste_center(fr, R.shadowed(card, 30, (0, 20), 160)[0], W / 2, CY + (1 - enter) * 900)
        if i and legend[min(i, 2)]:
            col = (230, 60, 60) if i == 1 else (242, 150, 46)
            R.paste_center(fr, R.pill(legend[min(i, 2)], 40, col, fg=HY.WHITE, padx=32, pady=12), W / 2 + 200, 470, HY.eob(lt / 0.3))
        mi = mas.render(t, mouth=float(env[min(fi, len(env) - 1)]), mood="excited" if i == 2 else "neutral", look=(0.6, 0.2),
                        bounce=5 * abs(math.sin(t * 3)), tilt=3 * math.sin(t * 1.6))
        if hook_on:                                      # big presenter under the hook, then small top-left
            mi = mi.resize((int(mi.width * 0.6), int(mi.height * 0.6)), Image.BILINEAR)
            fr.alpha_composite(mi, (int(W / 2 - mi.width / 2), int(1350 - mi.height)))
        else:
            mi = mi.resize((int(mi.width * 0.3), int(mi.height * 0.3)), Image.BILINEAR)
            fr.alpha_composite(mi, (20, int(530 - mi.height)))
        if hook_on:
            a_ = HY.eob(t / 0.25) * (1 if t < HOOK_T else max(0, 1 - (t - HOOK_T) / 0.3))
            R.paste_center(fr, badge, W / 2, badge_y, a_)
            R.paste_center(fr, HY.band_img(hook_img.height + 70), W / 2, hook_y, a_)
            R.paste_center(fr, hook_img, W / 2, hook_y, a_)
        else:
            R.paste_center(fr, title, W / 2, HY.SAFE_TOP + 30, HY.eob(min(1, (t - HOOK_T) / 0.3)))
        cur = [(ts, w) for si, ts, w in words if si == i and ts <= t and ts >= HOOK_T]
        if cur and t >= HOOK_T:
            idx = len(cur) - 1; st_ = (idx // 3) * 3
            ph = HY.phrase_img([w for _, w in cur[st_:idx + 1]], t - cur[-1][0], 78)
            R.paste_center(fr, HY.band_img(ph.height + 70), W / 2, 1480)
            R.paste_center(fr, ph, W / 2, 1480)
        fr.alpha_composite(HY.vignette())
        proc.stdin.write(HY.grain(fr, fi))
    proc.stdin.close(); proc.wait(); os.remove(wav)

    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tip_mp4, "-i", puzzle_mp4, "-filter_complex",
                    "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]"]
                   + HY.enc_args(out, scale=False), check=True)
    rng = random.Random(seed)
    reveal = meta.get("reveal", True)
    cap = (f"{script.get('caption_hook', tip[1])}\n"
           f"Calculation tip: {tip[1]}. {tip[2]}\n\n"
           + ("Now try it on the puzzle and comment your move!\n\n" if reveal else
              "Try it on the puzzle and comment your move. Answer in the comments tomorrow!\n\n")
           + "Save this for your next game and send it to a chess friend.\n\n"
           "Parents: StreakChess turns chess practice into a fun daily game. Free to play, founder offer for the first 500 accounts, link in bio.\n\n"
           + " ".join(R.hashtags(rng)))
    open(out.replace(".mp4", ".txt"), "w").write(cap)
    for f in (tip_mp4, puzzle_mp4, puzzle_mp4.replace(".mp4", ".txt")):
        if os.path.exists(f): os.remove(f)
    if not mock:
        log = json.load(open(LOG)) if os.path.exists(LOG) else []
        log.append({"tip": tip[0]}); json.dump(log[-100:], open(LOG, "w"), indent=0)
    meta.update(story=f"Tip: {tip[1]}", hook=script.get("caption_hook"), mode="tip", arms=arms)
    return meta


if __name__ == "__main__":
    P = json.load(open(sys.argv[1]))
    print(json.dumps(build(P, int(sys.argv[2]), sys.argv[3]), indent=1))
