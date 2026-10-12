"""Builds one long video (8-12 min) with the 10-agent team.

Chess material always comes from code (Lichess puzzles, verified historic games, this week's top games analysed by
Stockfish). The agents only write and shape the words around it, and every move they mention is checked against the
moves allowed for that moment (no invented moves, no spoilers before a timer).

Formats (the autopilot rotates them and learns which works):
  gym        Calculation Gym     - one tactical idea: demo, 4 reps of rising difficulty, the tempting mistake, Coach's rule
  streak     Streak Challenge    - 10 puzzles 800 -> 2400, keep your streak alive, boss puzzle, rank at the end
  legendary  Legendary Games     - a famous real game, stopping at the critical moments: what would you play?
  trending   This Week in Chess  - the best shots (found or missed!) from this week's elite tournaments

Beats (what the renderer draws):
  sting     {title, sub}                                  branded title card after the cold open
  say       {text, fen, flip, ctx, eval, pop?, squares?, arrows?, pause?}
  countdown {seconds, fen, flip, ctx, prompt, hint?}
  move      {fen, uci, flip, ctx, label, text?, ply}
`text` is the on-screen line with algebraic notation; the voice reads yt_notation.spoken(text).
"""
import datetime, json, os, random, re, sys
import chess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import yt_puzzles as PZ                                    # noqa: E402
import yt_library as LIB                                   # noqa: E402
import yt_strategy as ST                                   # noqa: E402
import yt_agents as AG                                     # noqa: E402
import yt_notation as NT                                   # noqa: E402
import yt_engine as EN                                     # noqa: E402

MOCK = bool(os.environ.get("YT_MOCK"))
APP_URL = os.environ.get("APP_URL", "streakchess.com")
SERIES = {"gym": "Calculation Gym", "streak": "Streak Challenge", "legendary": "Legendary Games",
          "trending": "This Week in Chess"}
CURRICULUM = ["fork", "pin", "skewer", "discovered", "backrank", "deflection", "attraction", "checklist", "intermezzo",
              "clearance", "xray", "quiet", "sacrifice", "smothered", "mate3", "candidates"]
RANKS = ["Pawn", "Knight", "Bishop", "Rook", "Queen", "Grandmaster"]


# ============================================================================ chess facts helpers
def labels(fen, ucis):
    """SAN with move numbers for a line starting at fen: ['23.Qxf7+', '23...Kh8', ...]."""
    b = chess.Board(fen); out = []
    for k, u in enumerate(ucis):
        m = chess.Move.from_uci(u)
        san = b.san(m)
        if b.turn == chess.WHITE:
            out.append(f"{b.fullmove_number}.{san}")
        else:
            out.append(f"{b.fullmove_number}...{san}" if k == 0 else san)
        b.push(m)
    return out


def pieces(fen):
    b = chess.Board(fen); out = []
    for color, name in ((chess.WHITE, "White"), (chess.BLACK, "Black")):
        ps = [f"{p.symbol().upper() if p.piece_type != chess.PAWN else ''}{chess.square_name(s)}"
              for s, p in sorted(b.piece_map().items(), key=lambda x: -x[1].piece_type) if p.color == color]
        out.append(f"{name}: " + " ".join(ps))
    return "; ".join(out)


def enrich(p):
    """Add notation labels + engine facts (eval after the solution, tempting wrong moves) to a puzzle."""
    p["labels"] = labels(p["fen"], p["sol"])
    p["flip"] = p["side"] == "Black"
    p["traps"], p["eval_after"] = [], None
    if EN.available():
        try:
            p["traps"] = EN.traps(p["fen"], p["sol"][0])
            p["eval_after"] = EN.fmt(EN.eval_white(p["final_fen"]))
        except Exception as e:
            print("engine facts skipped:", str(e)[:120], flush=True)
    return p


def allowed(*lines):
    s = set()
    for ln in lines:
        for x in ln:
            s.add(NT.norm(re.sub(r"^\d+\.(\.\.)?", "", x)))
    return s


def puzzle_facts(p, name):
    t = [f"{name}: {p['side']} to move, puzzle rating {p['rating']}. Pieces: {pieces(p['fen'])}.",
         f"Solution: {' '.join(p['labels'])} ({p['material']}).",
         f"Lichess themes: {', '.join(p['themes'][:6])}."]
    if p.get("eval_after"):
        t.append(f"Engine evaluation after the line: {p['eval_after']} (White's point of view).")
    for tr in p.get("traps", []):
        t.append(f"Tempting wrong move: {tr['san']}? refuted by {' '.join(tr['refutation'])} (eval {tr['eval_after']}).")
    return " ".join(t)


# ============================================================================ skeleton
class Show:
    """Collects segments (for the writers) and the timeline of beats (for the renderer) at the same time."""

    def __init__(self):
        self.segments, self.chapters, self.cur = [], [], None

    def chapter(self, cid, default_title):
        self.cur = {"id": cid, "title": default_title, "beats": []}
        self.chapters.append(self.cur)

    def seg(self, sid, purpose, n, words, fen, flip, ctx, allow=(), facts="", eval_on=True):
        """A block of spoken lines the writer fills in. n = (min, max) lines."""
        self.segments.append({"id": sid, "purpose": purpose, "lines": f"{n[0]}-{n[1]}", "words": words,
                              "position": pieces(fen) if fen else None, "allowed_moves": sorted(allow), "facts": facts})
        self.cur["beats"].append({"t": "seg", "id": sid, "fen": fen, "flip": flip, "ctx": ctx, "eval": eval_on,
                                  "allow": sorted(allow)})

    def add(self, beat):
        self.cur["beats"].append(beat)

    def moves(self, fen, ucis, flip, ctx, comments=None, start_ply=0):
        """Animate a line; labels go to the move list. comments: {label: segment id} spoken right after that move."""
        b = chess.Board(fen); labs = labels(fen, ucis)
        for k, u in enumerate(ucis):
            beat = {"t": "move", "fen": b.fen(), "uci": u, "flip": flip, "ctx": ctx, "label": labs[k], "ply": start_ply + k + 1}
            self.add(beat)
            if comments and labs[k] in comments:
                after = b.copy(); after.push(chess.Move.from_uci(u))
                self.add({"t": "seg", "id": comments[labs[k]], "fen": after.fen(), "flip": flip, "ctx": ctx, "eval": True,
                          "allow": [], "ply": start_ply + k + 1})
            b.push(chess.Move.from_uci(u))
        return b.fen()


def surname(n):
    n = (n or "").strip()
    return n.split(",")[0].strip() if "," in n else (n.split()[-1] if n else "?")


def think_seconds(base, rating):
    return int(max(8, min(40, base * (0.7 + (rating - 800) / 1600 * 0.8))))


def puzzle_block(S, p, i, n, base, kind, ctx_extra=None, trap=True, explain=(2, 4), setup=(1, 2), boss=False):
    """setup -> countdown (+hint) -> reveal -> animated solution -> explain -> tempting move."""
    ctx = {"kind": "puzzle", "side": p["side"], "rating": p["rating"], "moves": p["labels"], "num": i, "of": n,
           "series": kind, **(ctx_extra or {})}
    sol = allowed(p["labels"]); traps = [allowed([t["san"]] + t["refutation"]) for t in p.get("traps", [])]
    S.seg(f"p{i}_setup", ("BOSS PUZZLE setup: raise the stakes, " if boss else "") +
          "set up the position before the timer: who is to move, what to look at, without giving away the answer "
          "(no solution moves)", setup, "15-35", p["fen"], p["flip"], ctx, (), puzzle_facts(p, f"Puzzle {i}"), eval_on=False)
    S.add({"t": "countdown", "seconds": think_seconds(base, p["rating"]) + (8 if boss else 0), "fen": p["fen"],
           "flip": p["flip"], "ctx": ctx, "prompt": f"{p['side']} to move", "hint_id": f"p{i}"})
    S.seg(f"p{i}_reveal", "reveal: one punchy sentence that names the first solution move", (1, 1), "5-15", p["fen"],
          p["flip"], ctx, sol, eval_on=False)
    final = S.moves(p["fen"], p["sol"], p["flip"], ctx)
    S.seg(f"p{i}_explain", "why it works: the pattern, the key square/piece, what the opponent can't do", explain,
          "25-60", final, p["flip"], ctx, sol | set().union(*traps) if traps else sol)
    if trap and p.get("traps"):
        tr = p["traps"][0]
        S.seg(f"p{i}_trap", f"the tempting move {tr['san']} and why it fails ({' '.join(tr['refutation'])})", (1, 2), "15-35",
              p["fen"], p["flip"], ctx, sol | traps[0])


# ============================================================================ formats
def fmt_gym(S, arms, concept, seed, log):
    done = [e.get("sources", {}).get("topic") for e in log if e.get("format") == "gym"]
    topic = next((t for t in CURRICULUM if t not in done), CURRICULUM[len(done) % len(CURRICULUM)])
    name, themes = PZ.TOPICS[topic]
    ps = PZ.pick(themes, [900, 1150, 1450, 1750, 2100], seed=seed)
    if len(ps) < 4:
        ps = PZ.pick(None, [900, 1150, 1450, 1750, 2100], seed=seed)
    ps = [enrich(p) for p in ps]
    base = ST.THINK_SECONDS[arms.get("think_time", "normal")]
    demo, reps = ps[0], ps[1:]
    hard = reps[-1]
    tag = "gym"
    S.chapter("open", "The position")
    S.seg("cold_open", "COLD OPEN on the hardest rep: hook in the first sentence, open a loop (you'll be able to solve "
          "this by the end), no greeting", (2, 4), "35-60", hard["fen"], hard["flip"], {"kind": "talk"}, (),
          puzzle_facts(hard, "Hardest rep (do NOT reveal)"), eval_on=False)
    S.add({"t": "sting"})
    S.chapter("idea", name)
    S.seg("intro", "the promise of this episode + one-line callback to the previous episode + how the reps work",
          (2, 3), "35-60", demo["fen"], demo["flip"], {"kind": "talk"}, (), "", eval_on=False)
    dctx = {"kind": "puzzle", "side": demo["side"], "rating": demo["rating"], "moves": demo["labels"], "demo": True, "series": tag}
    dsol = allowed(demo["labels"])
    S.seg("demo_a", f"teach the idea '{name}' on this demo position: what to notice BEFORE moving", (3, 5), "60-100",
          demo["fen"], demo["flip"], dctx, (), puzzle_facts(demo, "Demo"), eval_on=False)
    S.seg("demo_reveal", "show the move (name it)", (1, 1), "5-14", demo["fen"], demo["flip"], dctx, dsol, eval_on=False)
    fin = S.moves(demo["fen"], demo["sol"], demo["flip"], dctx)
    S.seg("demo_b", "explain the pattern so the viewer can spot it again; give it a memorable name", (3, 5), "50-90",
          fin, demo["flip"], dctx, dsol)
    for i, p in enumerate(reps, 1):
        S.chapter(f"rep{i}", f"Rep {i} ({p['rating']})")
        puzzle_block(S, p, i, len(reps), base, tag)
        if i == 2:
            S.chapter("method", "How to find it in your games")
            S.seg("method", "the calculation routine to find this idea in YOUR games + common traps; end with the "
                  "Coach's rule", (4, 6), "80-130", p["final_fen"], p["flip"], {"kind": "talk"}, (), "", eval_on=False)
            S.seg("plug", f"natural, honest mention: StreakChess ({APP_URL}) is free and trains exactly this every day, "
                  "keep a daily streak", (1, 2), "20-40", p["final_fen"], p["flip"], {"kind": "app"}, (), "", eval_on=False)
    S.chapter("recap", "Recap")
    S.seg("recap", "recap the idea in 3 quick points + Coach's rule", (2, 4), "40-70", hard["final_fen"], hard["flip"],
          {"kind": "talk"}, (), "", eval_on=False)
    S.seg("outro", "tease the next Calculation Gym topic and ask a specific question for the comments", (2, 2), "25-45",
          hard["final_fen"], hard["flip"], {"kind": "end"}, (), "", eval_on=False)
    nxt = CURRICULUM[(CURRICULUM.index(topic) + 1) % len(CURRICULUM)]
    return {"topic": topic, "topic_name": name, "next_topic": PZ.TOPICS[nxt][0], "puzzles": [p["id"] for p in ps]}, hard


def fmt_streak(S, arms, concept, seed, log):
    ratings = [800 + int(1600 * k / 9) for k in range(10)]
    ps = [enrich(p) for p in PZ.pick(None, ratings, seed=seed)]
    base = ST.THINK_SECONDS[arms.get("think_time", "normal")]
    n = len(ps); hard = ps[-1]
    S.chapter("open", "The boss puzzle")
    S.seg("cold_open", "COLD OPEN on the boss puzzle: dare the viewer, explain nothing yet, open a loop", (2, 3), "30-50",
          hard["fen"], hard["flip"], {"kind": "tease", "side": hard["side"], "rating": hard["rating"],
                                      "headline": "THE BOSS PUZZLE", "sub": "10 puzzles stand between you and this one."}, (), puzzle_facts(hard, "Boss puzzle (do NOT reveal)"), eval_on=False)
    S.add({"t": "sting"})
    S.chapter("rules", "Rules")
    S.seg("rules", f"rules of the game: {n} puzzles, a timer each, one point per correct first move, keep your streak "
          "alive, pause if you need; callback to last challenge", (2, 3), "40-60", ps[0]["fen"], ps[0]["flip"],
          {"kind": "talk"}, (), "", eval_on=False)
    for i, p in enumerate(ps, 1):
        S.chapter(f"p{i}", f"Puzzle {i} ({p['rating']})" if i < n else f"Boss puzzle ({p['rating']})")
        puzzle_block(S, p, i, n, base, "streak", {"streak": True}, trap=(i == n), explain=(1, 2), setup=(1, 1),
                     boss=(i == n))
        if i == 5:
            S.seg("checkpoint", "halfway check: where a good player should be, it gets harder now", (1, 2), "20-35",
                  p["final_fen"], p["flip"], {"kind": "talk"}, (), "", eval_on=False)
            S.seg("plug", f"StreakChess ({APP_URL}) is free and gives you a new calculation streak every day", (1, 2),
                  "20-35", p["final_fen"], p["flip"], {"kind": "app"}, (), "", eval_on=False)
    S.chapter("score", "Your score")
    S.seg("score", f"scores to ranks: 0-2 {RANKS[0]}, 3-4 {RANKS[1]}, 5-6 {RANKS[2]}, 7-8 {RANKS[3]}, 9 {RANKS[4]}, "
          f"10 {RANKS[5]} - fun one-liners for each", (3, 4), "50-80", hard["final_fen"], hard["flip"], {"kind": "ranks"},
          (), "", eval_on=False)
    S.seg("outro", "ask them to comment their score honestly + tease next challenge", (2, 2), "20-40", hard["final_fen"],
          hard["flip"], {"kind": "end"}, (), "", eval_on=False)
    return {"puzzles": [p["id"] for p in ps]}, hard


def fmt_legendary(S, arms, concept, seed, log):
    used = [e.get("sources", {}).get("game") for e in log]
    games = LIB.available(set(used))
    if not games:
        return None
    g = random.Random(seed).choice(games)
    plies = LIB.validate(g); labs = [x[0] for x in plies]
    flip = g.get("hero") == "black"
    keys = [labs.index(k) for k in g["keys"]]
    base = ST.THINK_SECONDS[arms.get("think_time", "normal")]
    all_moves = allowed(labs)
    ctx = {"kind": "game", "white": g["white"], "black": g["black"], "event": g["event"], "year": g["year"],
           "moves": labs, "series": "legendary"}
    first = plies[keys[0]][2].fen()
    facts = f"{g['white']} vs {g['black']}, {g['event']} {g['year']} ('{g['nickname']}'). Moves: {' '.join(labs)}."
    S.chapter("open", "The position")
    S.seg("cold_open", f"COLD OPEN on the first critical moment ({g['keys'][0]} is about to be played - do NOT reveal it): "
          "drama, stakes, dare the viewer", (2, 4), "35-60", first, flip,
          {"kind": "tease", "side": "White" if plies[keys[0]][2].turn else "Black", "headline": "WHAT WOULD YOU PLAY?",
           "sub": f"{g['white']} vs {g['black']}, {g['year']}"}, (), facts, eval_on=False)
    S.add({"t": "sting"})
    S.chapter("story", "The story")
    S.seg("story", "who played, when, why this game is famous (only facts given or very well known), set the scene "
          "without spoiling the key moves", (3, 5), "60-100", chess.STARTING_FEN, flip, {**ctx, "upto": 0}, (), facts, eval_on=False)
    i = 0
    for si, k in enumerate(keys + [len(plies)]):
        if k > i:
            # replay up to the next stop, with a few spoken comments on chosen moves
            chunk = list(range(i, k))
            picks = chunk[1::max(2, len(chunk) // 3)][:3] if len(chunk) > 2 else []
            comments = {labs[j]: f"c{j}" for j in picks}
            for j in picks:
                S.segments.append({"id": f"c{j}", "purpose": f"one short comment (max 18 words) right after {labs[j]} "
                                   "is played: plan, threat or psychology", "lines": "1-1", "words": "6-18",
                                   "position": None, "allowed_moves": sorted(all_moves), "facts": ""})
            S.chapter(f"replay{si}", "The game" if si == 0 else f"After moment {si}")
            S.moves(plies[i][2].fen(), [plies[j][3].uci() for j in chunk], flip, ctx, comments, start_ply=i)
        if si == len(keys):
            break
        lab, san, b, mv = plies[k]
        side = "White" if b.turn == chess.WHITE else "Black"
        player = g["white"] if side == "White" else g["black"]
        S.chapter(f"km{si + 1}", f"Critical moment {si + 1}")
        pv = []
        trs = []
        if EN.available():
            try:
                r = EN.analyse(b.fen(), 16)
                pv = EN.pv_san(b.fen(), r[0]["pv"], 5)
                trs = EN.traps(b.fen(), mv.uci())
            except Exception:
                pass
        kfacts = (f"{side} to move ({player}). Real move played: {lab}. Next moves in the game: {' '.join(labs[k:k + 4])}. "
                  + (f"Engine best line: {' '.join(pv)}. " if pv else "")
                  + " ".join(f"Tempting wrong move: {t['san']}? refuted by {' '.join(t['refutation'])}." for t in trs))
        kctx = {**ctx, "upto": k}
        S.seg(f"km{si + 1}_setup", f"set up the critical moment: what would YOU play as {side}? no spoilers", (1, 2), "15-35",
              b.fen(), flip, kctx, (), kfacts, eval_on=False)
        S.add({"t": "countdown", "seconds": base + 10, "fen": b.fen(), "flip": flip, "ctx": kctx,
               "prompt": f"{side} to move", "hint_id": f"km{si + 1}"})
        S.seg(f"km{si + 1}_reveal", f"reveal that {player.split()[-1]} played {lab}", (1, 1), "6-16", b.fen(), flip, kctx,
              allowed([lab]), eval_on=False)
        S.moves(b.fen(), [mv.uci()], flip, ctx, start_ply=k)
        after = b.copy(); after.push(mv)
        S.seg(f"km{si + 1}_explain", "the calculation behind the move: what it threatens, why it works", (3, 5), "50-90",
              after.fen(), flip, {**ctx, "upto": k + 1}, all_moves | allowed(pv) | set().union(*[allowed([t["san"]] + t["refutation"]) for t in trs]) if trs else all_moves | allowed(pv), kfacts)
        i = k + 1
    end = plies[-1][2].copy(); end.push(plies[-1][3])
    S.chapter("lessons", "What it teaches you")
    S.seg("lessons", "3 lessons for YOUR games + Coach's rule", (3, 4), "60-90", end.fen(), flip, {**ctx, "upto": len(labs)},
          all_moves, eval_on=True)
    S.seg("plug", f"StreakChess ({APP_URL}) trains this kind of calculation daily, free", (1, 2), "20-35", end.fen(), flip,
          {"kind": "app"}, (), eval_on=False)
    S.seg("outro", "ask which legendary game they want next + tease", (2, 2), "20-40", end.fen(), flip, {"kind": "end"}, (),
          eval_on=False)
    hard = {"fen": first, "flip": flip, "rating": None, "side": "White" if plies[keys[0]][2].turn else "Black"}
    return {"game": g["id"], "game_name": g["nickname"]}, hard


def fmt_trending(S, arms, concept, seed, log, moments):
    if len(moments) < 2:
        return None
    base = ST.THINK_SECONDS[arms.get("think_time", "normal")]
    ms = moments[:4]
    def mfacts(m, i):
        return (f"Moment {i}: {m['white']} ({m['white_elo']}) vs {m['black']} ({m['black_elo']}), {m['event']} "
                f"round {m['round']} ({m['date']}), result {m['result']}. {m['side']} to move after move {m['move_label']}. "
                f"Evaluation before the opponent's mistake: {m['eval_before']}; now {m['eval_after']}. "
                f"Winning line: {' '.join(m['pv'])}. In the game {m['side']} played {m['played_san']} - "
                + ("they FOUND it." if m["found"] else "they MISSED it!"))
    hard = ms[0]
    S.chapter("open", "This week's shot")
    S.seg("cold_open", "COLD OPEN: an elite game from THIS week, one move decides it (found or missed) - dare the viewer; "
          "no greeting, no spoiler", (2, 4), "35-60", hard["fen"], hard["side"] == "Black",
          {"kind": "tease", "side": hard["side"], "headline": "THIS WEEK'S SHOT",
           "sub": f"{hard['white']} vs {hard['black']} · {hard['event']}"}, (),
          mfacts(hard, 1), eval_on=False)
    S.add({"t": "sting"})
    S.chapter("intro", "This week in chess")
    S.seg("intro", "what's happening in chess this week (only from the trend brief) + how the video works", (2, 3), "40-70",
          hard["fen"], hard["side"] == "Black", {"kind": "talk"}, (), "", eval_on=False)
    for i, m in enumerate(ms, 1):
        flip = m["side"] == "Black"
        ctx = {"kind": "live", "side": m["side"], "found": m["found"], "white": m["white"], "black": m["black"], "welo": m["white_elo"], "belo": m["black_elo"],
               "event": m["event"], "round": m["round"], "moves": labels(m["fen"], m["pv_uci"]), "series": "trending"}
        sol = allowed(m["pv"] + [m["played_san"]])
        S.chapter(f"m{i}", f"{surname(m['white'])} vs {surname(m['black'])}")
        S.seg(f"m{i}_story", "who, where, what's at stake; then ask: find what the player " +
              ("found" if m["found"] else "missed"), (2, 3), "30-60", m["fen"], flip, ctx, (), mfacts(m, i), eval_on=False)
        S.add({"t": "countdown", "seconds": think_seconds(base, 1900), "fen": m["fen"], "flip": flip, "ctx": ctx,
               "prompt": f"{m['side']} to move", "hint_id": f"m{i}"})
        S.seg(f"m{i}_reveal", "reveal the winning move", (1, 1), "5-15", m["fen"], flip, ctx, sol, eval_on=False)
        fin = S.moves(m["fen"], m["pv_uci"], flip, ctx)
        S.seg(f"m{i}_explain", "why it wins; and what really happened in the game", (2, 4), "40-80", fin, flip, ctx, sol)
    last = ms[-1]
    S.chapter("recap", "Recap")
    S.seg("recap", "the common thread of these shots + Coach's rule", (2, 3), "40-60", hard["fen"], hard["side"] == "Black",
          {"kind": "talk"}, (), "", eval_on=False)
    S.seg("plug", f"StreakChess ({APP_URL}): train these patterns daily, free", (1, 2), "20-35", hard["fen"],
          hard["side"] == "Black", {"kind": "app"}, (), eval_on=False)
    S.seg("outro", "ask which game of the week they liked + see you next week", (2, 2), "20-40", hard["fen"],
          hard["side"] == "Black", {"kind": "end"}, (), eval_on=False)
    return {"moments": [f"{m['white']}-{m['black']}" for m in ms]}, {"fen": hard["fen"], "flip": hard["side"] == "Black",
                                                                       "rating": None, "side": hard["side"]}


# ============================================================================ the team
def team_write(S, plan_info, concept, trends, playbook, arms):
    """Writer -> Coach -> Voice/Humor editor -> Director. Returns (lines {sid: [text]}, hints, cues, rule, chapters)."""
    segs = S.segments
    spec = json.dumps(segs, ensure_ascii=False)
    hook = arms.get("hook_style", "")
    news = json.dumps((trends.get("news") or {}).get("items", [])[:5], ensure_ascii=False)
    w = AG.ask("writer", f"""Write the script of this episode.
EPISODE CONCEPT (from the Showrunner): {json.dumps(concept, ensure_ascii=False)}
FORMAT: {plan_info['series']} - episode {plan_info['episode']}. Previous episodes: {plan_info['previous']}
HOOK STYLE TO TEST: {hook}
THIS WEEK IN CHESS (only use these facts if you mention news): {news}
SEGMENTS TO WRITE, in order (fill every one; respect line counts and word ranges; 'allowed_moves' are the ONLY moves
you may write in that segment, in algebraic notation; segments with no allowed moves must not contain any move):
{spec}

Rules: each line is ONE spoken sentence or two short ones (max 30 words). Write moves like Nxf7+, O-O, exd5 (with
move numbers only for real games, e.g. 17...Be6!!). Never write 'Hook', 'Chapter', stage directions or emojis.
Return JSON: {{"segments": {{"<segment id>": ["line", ...]}}, "chapter_titles": {{"<chapter id>": "viewer-facing title, max 5 words"}},
"coach_rule": "one memorable rule, max 10 words"}}
Chapter ids: {[c['id'] for c in S.chapters]}""", 0.95, playbook) or {}
    lines = {s["id"]: [l for l in (w.get("segments") or {}).get(s["id"], []) if isinstance(l, str) and l.strip()] for s in segs}
    rule = w.get("coach_rule") or ""
    titles = w.get("chapter_titles") or {}

    def check(sid, ln):
        seg = next(s for s in segs if s["id"] == sid)
        ok = set(seg["allowed_moves"])
        bad = [m for m in NT.sans_in(ln) if NT.norm(m) not in ok]
        return bad

    # ---- Chess Coach: truth + teaching + hints
    problems = {sid: [(ln, check(sid, ln)) for ln in ls if check(sid, ln)] for sid, ls in lines.items()}
    problems = {k: v for k, v in problems.items() if v}
    hint_ids = [b["hint_id"] for c in S.chapters for b in c["beats"] if b.get("t") == "countdown"]
    c = AG.ask("coach", f"""Review this script for chess truth and teaching value.
SEGMENTS WITH FACTS: {spec}
DRAFT: {json.dumps(lines, ensure_ascii=False)}
MOVES THAT ARE NOT ALLOWED IN THOSE SEGMENTS (must be fixed - spoilers or not in the facts): {json.dumps(problems, ensure_ascii=False)}
1) Rewrite ONLY the segments that have a chess error, a weak explanation, or a not-allowed move.
2) Write one hint per timer id {hint_ids}: max 8 words, points to an idea (a square, a weak piece), never a move.
Return JSON: {{"fixes": {{"<segment id>": ["line", ...]}}, "hints": {{"<id>": str}}, "coach_rule": str,
"notes_for_writer": "what you had to fix, 1-2 sentences (for the writer's notebook)"}}""", 0.4, playbook) or {}
    for sid, ls in (c.get("fixes") or {}).items():
        if sid in lines and isinstance(ls, list) and ls:
            lines[sid] = [l for l in ls if isinstance(l, str)]
    hints = {k: v for k, v in (c.get("hints") or {}).items() if isinstance(v, str) and not NT.sans_in(v) and len(v.split()) <= 10}
    rule = c.get("coach_rule") or rule
    AG.note("writer", c.get("notes_for_writer"), "coach")

    # ---- Voice & humor: sound human, keep every move identical
    v = AG.ask("comedian", f"""Make this script sound like a real, funny chess YouTuber talking. Keep the meaning, the
chess facts and EXACTLY the same moves in each line (same notation). Remove anything that smells of AI. Add personality
and a few well-placed jokes. Keep line counts within each segment's range.
SEGMENTS: {json.dumps([{k: s[k] for k in ('id', 'purpose', 'lines', 'words')} for s in segs], ensure_ascii=False)}
SCRIPT: {json.dumps(lines, ensure_ascii=False)}
Return JSON: {{"segments": {{"<segment id>": ["line", ...]}}, "notes_for_writer": "voice lessons, 1-2 sentences"}}""", 0.8, playbook) or {}
    for sid, ls in (v.get("segments") or {}).items():
        if sid not in lines or not isinstance(ls, list) or not ls:
            continue
        old = sorted(NT.norm(m) for l in lines[sid] for m in NT.sans_in(l))
        new = sorted(NT.norm(m) for l in ls if isinstance(l, str) for m in NT.sans_in(l))
        if old == new and all(isinstance(l, str) for l in ls):
            lines[sid] = ls
    AG.note("writer", v.get("notes_for_writer"), "comedian")

    # final guard: drop not-allowed moves lines, AI phrases flagged for the notebook
    for sid, ls in lines.items():
        keep = []
        for ln in ls:
            if check(sid, ln):
                print(f"script: dropped line with not-allowed move in {sid}: {ln[:80]}", flush=True)
                continue
            if AG.ai_phrases(ln):
                AG.note("comedian", f"Still used AI-ish phrasing: {AG.ai_phrases(ln)} in '{ln[:60]}'", "qa")
            keep.append(ln.strip())
        lines[sid] = keep

    # ---- Director: emphasis per line
    d = AG.ask("director", f"""For each line decide what the viewer sees.
SCRIPT: {json.dumps(lines, ensure_ascii=False)}
For every line give: "pop" (0-3 words shown big on screen, or null - use it for key ideas, not on every line),
"squares" (0-3 board squares like "f7" that should glow, only squares mentioned or obviously involved), "pause"
(seconds of silence after the line, 0 to 1.2; use 0.8+ after reveals).
Return JSON: {{"cues": {{"<segment id>": [{{"pop": str|null, "squares": [str], "pause": number}}, ...one per line]}}}}""", 0.5, playbook) or {}
    cues = d.get("cues") or {}
    return lines, hints, cues, rule, titles


def mock_lines(S):
    """Offline test script: plausible lines that use the allowed moves (to test notation, captions, layout)."""
    out = {}
    for s in S.segments:
        n = int(s["lines"].split("-")[1])
        mv = [m for m in s["allowed_moves"]][:3]
        ls = []
        for k in range(n):
            if mv and k == 0:
                ls.append(f"Look at {mv[0]}! It hits the king and the loose piece on f7 at the same time.")
            else:
                ls.append(f"This is a test line for {s['id'].replace('_', ' ')}, roughly the length of a real sentence, nothing more.")
        out[s["id"]] = ls
    return out


def mock_moments():
    """Offline test: 'this week' moments built from the key positions of the historic games (engine required)."""
    out = []
    for g in LIB.GAMES[:4]:
        p = LIB.validate(g); labs = [x[0] for x in p]; i = labs.index(g["keys"][0]); b = p[i][2]
        r = EN.analyse(b.fen(), 14) if EN.available() else None
        pv = r[0]["pv"][:3] if r else [p[i][3].uci()]
        out.append({"fen": b.fen(), "side": "White" if b.turn else "Black", "pv": EN.pv_san(b.fen(), pv, 3),
                    "pv_uci": pv, "played_san": p[i][1], "found": True, "swing": 500, "eval_before": "+0.3",
                    "eval_after": "+5.0", "move_label": labs[i].split(".")[0] + ".", "white": g["white"], "black": g["black"],
                    "white_elo": "2750", "black_elo": "2730", "event": "Test Open", "round": "5", "date": "2026.10.10",
                    "result": "1-0"})
    return out


# ============================================================================ build
def previous(log, fmt):
    eps = [e for e in log if e.get("format") == fmt]
    return len(eps) + 1, [e.get("title") for e in eps[-3:]]


def build(arms, seed, log=(), trends=None):
    log = list(log); trends = trends or {}
    fmt = arms["format"]
    playbook = ST.playbook_text()
    moments = []
    if fmt == "trending":
        try:
            import yt_trends as TR
            moments = mock_moments() if MOCK else TR.trending_moments()
        except Exception as e:
            print("trending moments failed:", str(e)[:200], flush=True)
        if len(moments) < 2:
            print("trending: not enough fresh moments this week, making a Calculation Gym instead", flush=True)
            fmt = arms["format"] = "gym"
    ep, prev = previous(log, fmt)
    info = {"series": SERIES[fmt], "episode": ep, "previous": prev or "(first episode)"}
    concept = AG.ask("showrunner", f"""Plan episode {ep} of '{SERIES[fmt]}'.
Previous episodes of this series: {prev or 'none yet'}. Other recent videos: {[e.get('title') for e in log[-4:]]}
Trend brief: {json.dumps((trends.get('news') or {}).get('items', [])[:5], ensure_ascii=False)}
Experiment levers for this video: {json.dumps({k: ST.short(v) for k, v in arms.items()})}
Return JSON: {{"angle": "the fresh angle of this episode in one sentence", "fun_mechanic": str, "cold_open_idea": str,
"callback": "one line linking to the previous episode (or null)", "tease_next": str, "tone": str}}""", 0.9, playbook) or {}
    S = Show()
    maker = {"gym": fmt_gym, "streak": fmt_streak, "legendary": fmt_legendary}
    res = fmt_trending(S, arms, concept, seed, log, moments) if fmt == "trending" else maker[fmt](S, arms, concept, seed, log)
    if res is None:                                          # legendary library exhausted etc.
        arms["format"] = fmt = "gym"; S = Show(); res = fmt_gym(S, arms, concept, seed, log)
        ep, prev = previous(log, fmt); info = {"series": SERIES[fmt], "episode": ep, "previous": prev}
    sources, hard = res
    if MOCK:
        lines, hints, cues, rule, titles = mock_lines(S), {}, {}, "Checks, captures, threats - in that order.", {}
    else:
        lines, hints, cues, rule, titles = team_write(S, info, concept, trends, playbook, arms)
        verdict = AG.ask("showrunner", f"""Final quality gate. Read the script and score it 1-10 for: hook strength, fun,
teaching value, originality, sounds human. SCRIPT: {json.dumps(lines, ensure_ascii=False)[:12000]}
Return JSON: {{"score": number, "best_moment": str, "weakest_moment": str, "notes_for_writer": str, "notes_for_comedian": str}}""", 0.3, playbook) or {}
        AG.note("writer", verdict.get("notes_for_writer"), "showrunner")
        AG.note("comedian", verdict.get("notes_for_comedian"), "showrunner")
        sources["quality"] = verdict.get("score")
    # ---- safety net: a timer is never left without its setup/reveal line
    for sg in S.segments:
        if lines.get(sg["id"]):
            continue
        sid = sg["id"]
        if sid.endswith("_reveal") and sg["allowed_moves"]:
            first = next((b for c in S.chapters for b in c["beats"] if b.get("t") == "move" and b.get("ctx", {}).get("moves")
                          and any(b2.get("id") == sid for b2 in c["beats"])), None)
            lines[sid] = [f"The move is {first['label']}!" if first else "Here's the move."]
        elif sid.endswith("_setup"):
            lines[sid] = ["Your turn. Find the strongest move."]
    # ---- turn segments into beats
    chapters = []
    for ch in S.chapters:
        beats = []
        for b in ch["beats"]:
            if b["t"] != "seg":
                if b["t"] == "countdown":
                    b = dict(b, hint=hints.get(b.get("hint_id")))
                beats.append(b); continue
            ls = lines.get(b["id"]) or []
            cs = cues.get(b["id"]) or []
            for k, ln in enumerate(ls):
                cue = cs[k] if k < len(cs) and isinstance(cs[k], dict) else {}
                sq = [s for s in (cue.get("squares") or []) if isinstance(s, str) and re.fullmatch(r"[a-h][1-8]", s)][:3]
                arrows = []
                for m in NT.sans_in(ln):                    # arrows for moves that can be played in the shown position
                    mv = NT.resolve(b["fen"], m)
                    if mv:
                        arrows.append(mv.uci())
                pop = cue.get("pop") if isinstance(cue.get("pop"), str) and len(cue["pop"].split()) <= 3 else None
                beats.append({"t": "say", "text": ln, "fen": b["fen"], "flip": b["flip"], "ctx": b["ctx"],
                              "eval": b["eval"], "squares": sq, "arrows": arrows[:2], "pop": pop,
                              "pause": min(1.2, max(0.0, float(cue.get("pause") or 0))) if str(cue.get("pause", "0")).replace(".", "", 1).isdigit() else 0.0,
                              "ply": b.get("ply")})
        if beats:
            chapters.append({"id": ch["id"], "title": (titles.get(ch["id"]) or ch["title"])[:40], "beats": beats})
    sources.update(format=fmt, series=SERIES[fmt], episode=ep)
    return {"format": fmt, "arms": arms, "series": SERIES[fmt], "episode": ep, "series_tag": f"{SERIES[fmt].upper()} · EP {ep}",
            "concept": concept, "coach_rule": rule, "chapters": chapters, "sources": sources, "hard": hard,
            "segments": S.segments, "lines": lines}


def word_count(plan):
    return sum(len(b.get("text", "").split()) for c in plan["chapters"] for b in c["beats"] if b["t"] == "say")


if __name__ == "__main__":
    a = {"format": sys.argv[1] if len(sys.argv) > 1 else "gym", "hook_style": "cold_open", "title_style": "curiosity",
         "thumb_style": "board_text", "think_time": "fast"}
    p = build(a, "test")
    for c in p["chapters"]:
        print(f"== {c['title']}: {len(c['beats'])} beats")
    print("words:", word_count(p))
    print([b["text"] for c in p["chapters"] for b in c["beats"] if b["t"] == "say"][:6])
