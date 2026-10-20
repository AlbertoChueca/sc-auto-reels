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
    ("pin", "A pinned piece is not a defender", "A pinned piece cannot move, so count it as zero when you count defenders."),
    ("xray", "Look through the pieces", "Long-range pieces work through other pieces: find the line that opens when one moves."),
    ("fork", "Two targets, one move", "Look for undefended pieces and a square that attacks two of them at once."),
    ("sac", "Calculate the sacrifice", "A sacrifice is only good if you calculate the forced replies to the end."),
    ("deflect", "Pull the defender away", "If one piece holds the position together, find the move that drags it away."),
]

# The puzzle's own themes decide what today's lesson teaches, so every reel explains something different and real.
THEME_TIP = [("pin", "pin"), ("xRayAttack", "xray"), ("skewer", "xray"), ("discoveredAttack", "xray"),
             ("fork", "fork"), ("doubleCheck", "xray"), ("sacrifice", "sac"), ("deflection", "deflect"),
             ("attraction", "deflect"), ("overloading", "overload"), ("hangingPiece", "loose"),
             ("backRankMate", "king"), ("smotheredMate", "king"), ("kingsideAttack", "king"), ("trappedPiece", "count"),
             ("defensiveMove", "threat"), ("quietMove", "candidates"), ("intermezzo", "forcing"),
             ("mateIn2", "forcing"), ("mateIn3", "end"), ("long", "end"), ("crushing", "cct")]

PROMPT = """You write the hooks of a premium chess reel: a step-by-step calculation masterclass for club players
(1600+) and chess parents. TIP: {name} - {idea}
{brief}
screen_hook: the BIG cover text, max 6 words, a curiosity gap or bold promise, no emoji, no numbers as digits
(e.g. "How masters calculate in seconds"). caption_hook: max 10 words, one emoji max.
Return JSON: {{"screen_hook": str, "caption_hook": str}}"""


def pick_tip(seed, P=None, recent=None):
    """Prefer a lesson that fits THIS puzzle's themes and was not used recently; otherwise any fresh one."""
    if recent is None:
        log = json.load(open(LOG)) if os.path.exists(LOG) else []
        recent = [e.get("tip") or e.get("lesson") for e in log[-8:]]
    by = {t[0]: t for t in TIPS}
    themes = set(((P or {}).get("themes") or "").split())
    fit = [by[k] for th, k in THEME_TIP if th in themes and k not in recent]
    if fit:
        return fit[0]
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
    sh = (res.get("screen_hook") or "").strip()
    if not sh or len(sh.split()) > 7 or re.search(r"\d", sh):
        res["screen_hook"] = tip[1]
    return res


def forcing(board):
    """Real checks and captures for the side to move (python-chess)."""
    checks, caps = [], []
    for m in board.legal_moves:
        if board.gives_check(m): checks.append(m)
        elif board.is_capture(m): caps.append(m)
    return checks[:4], caps[:5]


def build(P, seed, out, mode="level", arms=None):
    """Cover (bold hook + annotated board) -> animated step-by-step lesson on the puzzle position -> the puzzle."""
    import lesson_anim, voice, strategy
    arms = arms or {}
    mock = os.environ.get("TIP_MOCK") == "1"
    tip = pick_tip(seed, P)
    try:
        script = {"screen_hook": tip[1], "caption_hook": "Save this calculation method ♟️"} if mock else write_script(tip)
    except Exception as e:
        print("tip hooks fallback:", str(e)[:120]); script = {"screen_hook": tip[1], "caption_hook": f"{tip[1]} ♟️"}
    print("Tip reel:", tip[1], "|", script["screen_hook"], flush=True)
    if "fen" in P:
        board = chess.Board(P["fen"]); board.push(chess.Move.from_uci(P["moves"].split()[0]))
    else:
        board = chess.Board()
        for m in P["pgn"].split(): board.push_san(m)
    _lv = R.LEVELS.get(P.get("level"), {})
    lvl = f"{_lv.get('name', '')} LEVEL".strip()
    L = lesson_anim.Lesson(board, tip, 2, cover=True, hook=script["screen_hook"], level_label=lvl.upper(), mock=mock,
                           hide=lesson_anim.solution_move(P))
    puzzle_mp4 = out.replace(".mp4", "_puzzle.mp4"); tip_mp4 = out.replace(".mp4", "_tip.mp4")
    MAX = float(os.environ.get("REEL_MAX_SECONDS", "50"))
    voice.reset()
    for attempt in range(3):
        try:
            L.record()
            meta = HY.build(P, seed, puzzle_mp4, mode=mode, skip_hook=True, keep_voice=True,
                            cta_lead="Save this method and use it in your next game! ",
                            think_factor=strategy.THINK_FACTOR.get(arms.get("think_time"), 1.0),
                            style={"follow_line": "Follow to build your calculation streak", "share_line": "Challenge a chess friend now",
                                   "streak_line": "Calculation masterclass"},
                            max_len=MAX - L.length(), reveal=False)
            break
        except voice.VoiceError as e:
            nxt = voice.next_engine(); print(f"voice changed ({e}); redoing with {nxt}", flush=True); voice.reset(nxt)
    else:
        raise RuntimeError("could not record a consistent voice")
    L.render(tip_mp4)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", tip_mp4, "-i", puzzle_mp4, "-filter_complex",
                    "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]"]
                   + HY.enc_args(out, scale=False), check=True)
    rng = random.Random(seed)
    reveal = meta.get("reveal", False)
    steps_txt = "\n".join(f"{i + 1}️⃣ {s['title'].title()}: {s['fact']}" for i, s in enumerate(L.steps))
    cap = (f"{script.get('caption_hook', tip[1])}\n"
           f"Calculation masterclass: {tip[1]}. {tip[2]}\n\nThe method, step by step, on this position:\n{steps_txt}\n\n"
           + ("Now calculate your candidates and comment your move!\n\n" if reveal else
              "Calculate your candidates and comment your move. Answer in the comments tomorrow!\n\n")
           + "Save this for your next game and send it to a chess friend.\n\n"
           "For every chess player, kids and adults: StreakChess turns calculation practice into a daily game. Free to play, founder offer for the first 500 accounts, link in bio.\n\n"
           + " ".join(R.hashtags(rng)))
    review = {}
    if not mock and os.environ.get("REVIEWER", "on") != "off" and os.environ.get("GEMINI_API_KEY"):
        import reviewer                             # same QA as the story reels: watch it, score it, polish caption
        try:
            cap, review = reviewer.review_video(out, {"title": f"Calculation masterclass: {tip[1]}"}, cap)
        except reviewer.RejectReel:
            raise
        except Exception as e:
            print("tip review skipped:", str(e)[:150], flush=True)
    open(out.replace(".mp4", ".txt"), "w").write(cap)
    for f in (tip_mp4, puzzle_mp4, puzzle_mp4.replace(".mp4", ".txt")):
        if os.path.exists(f): os.remove(f)
    if not mock:
        log = json.load(open(LOG)) if os.path.exists(LOG) else []
        log.append({"tip": tip[0]}); json.dump(log[-100:], open(LOG, "w"), indent=0)
    meta.update(story=f"Tip: {tip[1]}", hook=script.get("caption_hook"), mode="tip", arms=arms, thumb_offset_ms=0,
                review_score=review.get("overall"))
    return meta


if __name__ == "__main__":
    P = json.load(open(sys.argv[1]))
    print(json.dumps(build(P, int(sys.argv[2]), sys.argv[3]), indent=1))
