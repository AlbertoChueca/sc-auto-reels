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
    ("backrank", "The back rank trap", "A king with no escape square loses to any check on the last rank. Count the escape squares."),
    ("discovered", "The discovered attack", "Move the front piece with a threat and the piece behind it attacks too: two threats in one move."),
    ("trapped", "Trap the piece", "A piece with no safe squares is already lost. Count its escape squares before you chase it."),
    ("removal", "Remove the defender", "If one piece protects the key square, capture it or chase it away first, then strike."),
]

TOPIC_TAG = {"pin": "chesspin", "xray": "xrayattack", "fork": "chessfork", "sac": "chesssacrifice", "deflect": "deflection",
             "overload": "overloadeddefender", "loose": "hangingpiece", "count": "chesscalculation", "king": "kingsafety",
             "threat": "chessthreats", "cct": "checkscapturesthreats", "forcing": "forcingmoves", "blunder": "blundercheck",
             "candidates": "candidatemoves", "end": "chesscalculation", "visual": "chessvisualization", "slow": "chessmindset",
             "backrank": "backrankmate", "discovered": "discoveredattack", "trapped": "trappedpiece", "removal": "removethedefender"}

# The puzzle's own themes decide what today's lesson teaches, so every reel explains something different and real.
THEME_TIP = [("pin", "pin"), ("xRayAttack", "xray"), ("skewer", "xray"), ("discoveredAttack", "discovered"),
             ("doubleCheck", "discovered"), ("fork", "fork"), ("sacrifice", "sac"), ("deflection", "deflect"),
             ("attraction", "deflect"), ("overloading", "overload"), ("capturingDefender", "removal"),
             ("clearance", "removal"), ("hangingPiece", "loose"), ("backRankMate", "backrank"),
             ("smotheredMate", "king"), ("kingsideAttack", "king"), ("exposedKing", "king"), ("trappedPiece", "trapped"),
             ("defensiveMove", "threat"), ("quietMove", "candidates"), ("intermezzo", "forcing"),
             ("mateIn2", "forcing"), ("mateIn3", "end"), ("long", "end"), ("crushing", "cct")]

PROMPT = """You write the hooks of a premium chess reel: a short calculation masterclass for chess players of every
age (club level). TIP: {name} - {idea}
Position facts (engine-computed, use them to be concrete): {facts}
{brief}
{rules}
screen_hook: the BIG cover text AND the first spoken words, max 6 words, concrete (name the piece or tactic), no
emoji, no digits (e.g. "This knight defends nothing"). caption_hook: the first caption line, 5-11 words, max one
emoji, a different formula from screen_hook. Both must respect the hook rules above.
Return JSON: {{"screen_hook": str, "caption_hook": str}}"""


def lesson_scores():
    """Real Instagram results per lesson (from performance.json): {tip_key: (n, mean reward)}."""
    try:
        import strategy
        perf = json.load(open(os.path.join(HERE, "performance.json")))
    except Exception:
        return {}
    names = {t[1]: t[0] for t in TIPS}
    acc = {}
    for r in perf.values():
        k = names.get((r.get("story") or "").replace("Tip: ", ""))
        rw = strategy.reward(r) if k else None
        if k and rw is not None:
            n, s = acc.get(k, (0, 0.0)); acc[k] = (n + 1, s + rw)
    return {k: (n, s / n) for k, (n, s) in acc.items()}


def pick_tip(seed, P=None, recent=None):
    """Which lesson today: it must not have run recently; among the rest, lessons that FIT this puzzle's themes
    come first, and the choice learns from real results (Thompson sampling on the reward of each lesson, so the
    patterns people watch and share - pins, loose pieces, overloaded defenders - come back more often, while every
    lesson still gets tested now and then)."""
    import math
    rng = random.Random(seed)
    if recent is None:
        log = json.load(open(LOG)) if os.path.exists(LOG) else []
        recent = [e.get("tip") or e.get("lesson") for e in log[-6:]]
    by = {t[0]: t for t in TIPS}
    themes = set(((P or {}).get("themes") or "").split())
    fit = [k for th, k in THEME_TIP if th in themes and k not in recent and k in by]
    pool = list(dict.fromkeys(fit)) or [t[0] for t in TIPS if t[0] not in recent] or [t[0] for t in TIPS]
    sc = lesson_scores()
    vals = [m for n, m in sc.values()]
    mu = sum(vals) / len(vals) if vals else 0.0
    sd = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5 if len(vals) > 1 else 1.0
    sd = max(sd, 0.3)
    best, best_v = None, -1e9
    for k in pool:
        n, m = sc.get(k, (0, mu))
        v = rng.gauss((m * n + mu) / (n + 1), sd / math.sqrt(n + 1))
        if v > best_v:
            best, best_v = k, v
    return by[best]


def write_script(tip, facts="", **fb):
    import reviewer, hooks
    try:
        import agents
        brief = agents._brief("hook")
    except Exception:
        brief = ""
    res = {}
    for attempt in range(2):
        try:
            res = reviewer._ask([{"text": PROMPT.format(name=tip[1], idea=tip[2], brief=brief, facts=facts or "-",
                                                        rules=hooks.rules())}], 0.9)
        except Exception as e:
            print("tip hooks: model call failed:", str(e)[:120], flush=True); res = {}
        sh = re.sub(r"[^\w\s'?!,.-]", "", (res.get("screen_hook") or "")).strip()
        ch = (res.get("caption_hook") or "").strip()
        if sh and len(sh.split()) <= 7 and not re.search(r"\d", sh) and hooks.is_fresh(sh) \
                and 4 <= len(ch.split()) <= 12 and hooks.is_fresh(ch):
            return {"screen_hook": sh, "caption_hook": ch}
        print(f"tip hooks: attempt {attempt + 1} rejected ({sh!r} / {ch!r})", flush=True)
    cap = hooks.fallback(tip[0], tip[1], **fb)
    sh = re.sub(r"[^\w\s'?!,.-]", "", hooks.fallback(tip[0], tip[1], seed=f"{cap}-screen", **fb)).strip()
    if sh.lower() == cap.lower() or len(sh.split()) > 7:
        sh = tip[1]
    return {"screen_hook": sh, "caption_hook": cap}


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
    if "fen" in P:
        board = chess.Board(P["fen"]); board.push(chess.Move.from_uci(P["moves"].split()[0]))
    else:
        board = chess.Board()
        for m in P["pgn"].split(): board.push_san(m)
    _lv = R.LEVELS.get(P.get("level"), {})
    lvl = f"{_lv.get('name', '')} LEVEL".strip()
    L = lesson_anim.Lesson(board, tip, 2, cover=True, hook=tip[1], level_label=lvl.upper(), mock=mock,
                           hide=lesson_anim.solution_move(P))
    side = "White" if board.turn else "Black"
    fb = dict(level_name=_lv.get("name", "club"), side=side, secs=max(5, int(round(_lv.get("count", 8)))),
              seed=f"{P.get('id')}-{seed}")
    try:
        sol = lesson_anim.solution_move(P)
        if sol is not None and board.piece_at(sol.from_square):
            fb["piece"] = lesson_anim.PN[board.piece_at(sol.from_square).piece_type]
    except Exception:
        pass
    facts = "; ".join(s.get("fact", "") for s in L.steps)
    try:
        import hooks
        script = ({"screen_hook": tip[1], "caption_hook": hooks.fallback(tip[0], tip[1], **fb)} if mock
                  else write_script(tip, facts, **fb))
    except Exception as e:
        print("tip hooks fallback:", str(e)[:120]); script = {"screen_hook": tip[1], "caption_hook": f"{tip[1]} ♟️"}
    L.set_hook(script["screen_hook"])
    print("Tip reel:", tip[1], "|", script["screen_hook"], "|", script["caption_hook"], flush=True)
    puzzle_mp4 = out.replace(".mp4", "_puzzle.mp4"); tip_mp4 = out.replace(".mp4", "_tip.mp4")
    MAX = float(os.environ.get("REEL_MAX_SECONDS", "45"))
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
           + " ".join(R.hashtags(rng, TOPIC_TAG.get(tip[0]))))
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
    meta.update(story=f"Tip: {tip[1]}", hook=script.get("caption_hook"), mode="tip", arms=arms, thumb_offset_ms=0, tip_key=tip[0],
                review_score=review.get("overall"))
    return meta


if __name__ == "__main__":
    P = json.load(open(sys.argv[1]))
    print(json.dumps(build(P, int(sys.argv[2]), sys.argv[3]), indent=1))
