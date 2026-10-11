"""Builds the plan of one long video (8-12 min): chapters made of beats the renderer turns into picture + voice.

The chess is always produced by code (positions, solution moves, captured material, real game moves); Gemini only
writes the words around it and is told the exact facts, so it cannot invent a move. Three formats:
  lesson     - one tactical idea, explained, with 4 examples of growing difficulty (pause and calculate)
  challenge  - 10 puzzles from ~800 to ~2400 with a timer, keep your score
  legendary  - a famous real game replayed, stopping at the critical moments to let the viewer calculate

Beats:
  {"t": "title", "text", "sub"}                         chapter card
  {"t": "say", "text", "card"?, "fen"?, "flip"?, "arrows"?, "hl"?}
  {"t": "countdown", "seconds", "fen", "flip", "prompt"}
  {"t": "move", "fen", "uci", "flip", "text"?}          piece slides, then the line is spoken
"""
import json, os, random, re, sys
import chess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
import yt_puzzles as PZ                                    # noqa: E402
import yt_library as LIB                                   # noqa: E402
import yt_strategy as ST                                   # noqa: E402

MOCK = bool(os.environ.get("YT_MOCK"))
APP_URL = os.environ.get("APP_URL", "streakchess.com")

STYLE = f"""You write scripts for StreakChess, a YouTube channel about calculation and tactics for chess players who
want to get better (teenagers and adults, roughly 800-2000 rating). StreakChess is also a free daily calculation
training app ({APP_URL}). Voice: a friendly, sharp chess coach talking to ONE viewer ("you"). Spoken English,
short sentences (max 25 words each), concrete, energetic but never cheesy, no filler, no emojis, no hashtags in lines.
Every line is read aloud by a text-to-speech voice: write numbers and squares the way they are said ("e5" is fine,
"300" is fine), never use markdown, brackets or stage directions.
TRUTH RULES: never name a chess move, square or piece position that is not in the facts given to you. When you talk
about a solution, use exactly the moves provided. Do not invent statistics, quotes or historical details; if you are
not sure about a fact, leave it out. Make the viewer WANT to keep watching: open loops ("in a minute I'll show you
the trick that..."), payoffs, and frequent invitations to pause and calculate."""

RETENTION = """Pacing rules for retention: the hook must create a question in the first 15 seconds and never start with
"hi" or "welcome". Never announce the structure in a boring way. Every chapter ends with a reason to watch the next."""


def _pieces_words(fen):
    b = chess.Board(fen); out = []
    for color, name in ((chess.WHITE, "White"), (chess.BLACK, "Black")):
        ps = [f"{chess.piece_name(p.piece_type)} {chess.square_name(s)}" for s, p in
              sorted(b.piece_map().items(), key=lambda x: -x[1].piece_type) if p.color == color]
        out.append(f"{name}: " + ", ".join(ps))
    return "; ".join(out)


def _pz_facts(i, p):
    return (f"Example {i + 1}: rating {p['rating']}, {p['side']} to move. Position (FEN) {p['fen']}. Pieces: "
            f"{_pieces_words(p['fen'])}. Solution (SAN, both sides): {' '.join(p['san'])}. Lichess themes: "
            f"{', '.join(p['themes'])}. Result: {p['material']}.")


def _ask(prompt, temperature=0.9):
    import yt_gemini as G
    return G.ask_json(prompt, temperature)


def _lines(x):
    """Accept ["..."] or [{"say": "...", "card": "..."}] -> [(say, card)]."""
    out = []
    for it in x or []:
        if isinstance(it, str):
            out.append((it.strip(), None))
        elif isinstance(it, dict) and (it.get("say") or "").strip():
            out.append((it["say"].strip(), (it.get("card") or None)))
    return [(s, c) for s, c in out if s]


def _say(lines, fen=None, flip=False, card=None):
    beats = []
    for s, c in lines:
        b = {"t": "say", "text": s, "card": c or card}
        if fen:
            b.update(fen=fen, flip=flip)
        beats.append(b)
    return beats


def _speak_move(board, mv, mover_first=True):
    import make_reel as R
    san = board.san(mv)
    who = "White" if board.turn == chess.WHITE else "Black"
    return f"{who} plays {R.san_say(san)}" if mover_first else R.san_say(san)


def _solution_beats(p, flip):
    """Animated solution: every move slides in and is spoken; the solver's moves get a highlight."""
    b = chess.Board(p["fen"]); me = b.turn; beats = []
    for k, u in enumerate(p["sol"]):
        mv = chess.Move.from_uci(u)
        import make_reel as R
        san = b.san(mv)
        if b.turn == me:
            text = ("The answer: " if k == 0 else "Then ") + R.san_say(san)
        else:
            text = f"{'Black' if b.turn == chess.BLACK else 'White'} replies {R.san_say(san)}"
        beats.append({"t": "move", "fen": b.fen(), "uci": u, "flip": flip, "text": text})
        b.push(mv)
    return beats, b.fen()


def think_seconds(base, rating):
    return int(max(8, min(45, base * (0.75 + (rating - 800) / 1600 * 0.75))))


# ============================================================================ lesson
def lesson(arms, seed):
    topic = arms.get("topic") or "fork"
    name, themes = PZ.TOPICS[topic]
    pz = PZ.pick(themes, [1000, 1350, 1700, 2050], seed=seed)
    if len(pz) < 3:
        pz = PZ.pick(None, [1000, 1350, 1700, 2050], seed=seed)
    base = ST.THINK_SECONDS[arms.get("think_time", "normal")]
    facts = "\n".join(_pz_facts(i, p) for i, p in enumerate(pz))
    if MOCK:
        S = _mock_lesson(name, len(pz))
    else:
        S = _ask(f"""{STYLE}
{RETENTION}
PLAYBOOK FROM OUR REAL RESULTS (follow it):
{ST.playbook_text() or '(none yet)'}

Write a {name!r} lesson video (8-10 minutes of narration in total, about 1150-1350 spoken words).
Hook style to use: {arms['hook_style']}
Title style: {arms['title_style']}
The {len(pz)} example positions (shown on screen, the viewer pauses and calculates, then we reveal):
{facts}

Return JSON:
{{"titles": [3 YouTube titles, max 60 characters, no clickbait lies, in the title style],
 "thumb_texts": [3 thumbnail texts, max 4 words each, UPPERCASE],
 "hook": [3-4 lines, the first 20-30 seconds; the hardest example is on screen while you speak],
 "intro": [2-3 lines: why this idea wins games and what the viewer will be able to do by the end],
 "teach1": {{"title": "chapter title (max 5 words)", "lines": [{{"say": str, "card": "max 6 words key point or null"}}, 7-10 items]}},
 "examples": [one per example, in order: {{"setup": [1-2 lines before the timer, no spoilers], "explain": [3-5 lines after the reveal: why it works, the pattern to spot, the mistake most people make]}}],
 "teach2": {{"title": "chapter title", "lines": [{{"say": str, "card": str|null}}, 6-9 items: how to FIND this in your own games, a calculation routine, common traps]}},
 "plug": [2 lines: natural mention that StreakChess, free at {APP_URL}, trains exactly this calculation every day],
 "recap": [{{"say": str, "card": str}}, 3-4 items],
 "outro": [2-3 lines: ask a question for the comments, subscribe for the next calculation lesson],
 "description": "2-3 sentences for the YouTube description",
 "tags": [8-12 tags]}}""")
    flip = lambda p: p["side"] == "Black"
    hard = pz[-1]
    ch = [{"title": "Hook", "beats": _say(_lines(S["hook"]), hard["fen"], flip(hard))},
          {"title": "Why this wins games", "beats": [{"t": "title", "text": name, "sub": "StreakChess calculation lesson"}]
           + _say(_lines(S["intro"]))},
          {"title": S["teach1"].get("title", "The idea"), "beats": [{"t": "title", "text": S["teach1"].get("title", "The idea")}]
           + _say(_lines(S["teach1"]["lines"]), pz[0]["fen"], flip(pz[0]))}]
    ex = S.get("examples") or []
    for i, p in enumerate(pz):
        e = ex[i] if i < len(ex) else {}
        beats = [{"t": "title", "text": f"Example {i + 1}", "sub": f"Rating {p['rating']} · {p['side']} to move"}]
        beats += _say(_lines(e.get("setup")) or [(f"{p['side']} to move. Find the winning idea.", None)], p["fen"], flip(p))
        beats.append({"t": "countdown", "seconds": think_seconds(base, p["rating"]), "fen": p["fen"], "flip": flip(p),
                      "prompt": f"{p['side']} to move"})
        sb, final = _solution_beats(p, flip(p)); beats += sb
        beats += _say(_lines(e.get("explain")), final, flip(p))
        ch.append({"title": f"Example {i + 1} ({p['rating']})", "beats": beats})
        if i == 1:
            t2 = S["teach2"]
            ch.append({"title": t2.get("title", "Find it in your games"),
                       "beats": [{"t": "title", "text": t2.get("title", "Find it in your games")}]
                       + _say(_lines(t2["lines"])) + _say(_lines(S.get("plug")), card=f"Free daily training: {APP_URL}")})
    ch.append({"title": "Recap", "beats": [{"t": "title", "text": "Recap"}] + _say(_lines(S["recap"])) + _say(_lines(S["outro"]))})
    return _meta(S, ch, arms, hard, {"topic": topic, "puzzles": [p["id"] for p in pz]})


# ============================================================================ challenge
def challenge(arms, seed):
    ratings = [800 + int(1600 * k / 9) for k in range(10)]
    pz = PZ.pick(None, ratings, seed=seed)
    base = ST.THINK_SECONDS[arms.get("think_time", "normal")]
    facts = "\n".join(_pz_facts(i, p) for i, p in enumerate(pz))
    if MOCK:
        S = _mock_challenge(len(pz))
    else:
        S = _ask(f"""{STYLE}
{RETENTION}
PLAYBOOK FROM OUR REAL RESULTS (follow it):
{ST.playbook_text() or '(none yet)'}

Write a PUZZLE CHALLENGE video: {len(pz)} positions of rising difficulty, a timer for each, the viewer keeps score.
About 900-1100 spoken words in total. Hook style: {arms['hook_style']}. Title style: {arms['title_style']}.
The positions:
{facts}

Return JSON:
{{"titles": [3 titles, max 60 characters], "thumb_texts": [3 texts, max 4 words, UPPERCASE],
 "hook": [3 lines; the last, hardest puzzle is on screen],
 "rules": [2 lines: you get a timer, pause if you need, one point per correct first move, keep score],
 "puzzles": [one per position, in order: {{"intro": "1 line before the timer (level feeling, no spoilers)", "explain": [1-3 lines after the reveal: why it works and the pattern]}}],
 "checkpoint": [2 lines said after puzzle 5: where they should be, it gets harder now],
 "plug": [2 lines: StreakChess, free at {APP_URL}, gives a new calculation streak every day],
 "scores": [{{"say": str, "card": "e.g. 0-3 points: ..."}}, 4 bands],
 "outro": [2 lines: comment your score, subscribe for the next challenge],
 "description": "2-3 sentences", "tags": [8-12 tags]}}""")
    flip = lambda p: p["side"] == "Black"
    hard = pz[-1]
    ch = [{"title": "Hook", "beats": _say(_lines(S["hook"]), hard["fen"], flip(hard))},
          {"title": "Rules", "beats": [{"t": "title", "text": f"{len(pz)} puzzles. One timer.", "sub": "Keep your score"}]
           + _say(_lines(S["rules"]))}]
    info = S.get("puzzles") or []
    for i, p in enumerate(pz):
        e = info[i] if i < len(info) else {}
        beats = [{"t": "title", "text": f"Puzzle {i + 1} of {len(pz)}", "sub": f"Rating {p['rating']} · {p['side']} to move"}]
        beats += _say([(e.get("intro") or f"Puzzle {i + 1}. {p['side']} to move.", None)], p["fen"], flip(p))
        beats.append({"t": "countdown", "seconds": think_seconds(base, p["rating"]), "fen": p["fen"], "flip": flip(p),
                      "prompt": f"{p['side']} to move"})
        sb, final = _solution_beats(p, flip(p)); beats += sb
        beats += _say(_lines(e.get("explain")), final, flip(p))
        if i == 4:
            beats += _say(_lines(S.get("checkpoint")), card="Halfway: count your points") + \
                     _say(_lines(S.get("plug")), card=f"Free daily training: {APP_URL}")
        ch.append({"title": f"Puzzle {i + 1} ({p['rating']})", "beats": beats})
    ch.append({"title": "Your score", "beats": [{"t": "title", "text": "Your score"}] + _say(_lines(S["scores"]))
               + _say(_lines(S["outro"]))})
    return _meta(S, ch, arms, hard, {"puzzles": [p["id"] for p in pz]}, number=f"{len(pz)} PUZZLES")


# ============================================================================ legendary game
def legendary(arms, seed, used_games=()):
    games = LIB.available(set(used_games))
    if not games:
        print("legendary: library exhausted, making a challenge video instead", flush=True)
        arms["format"] = "challenge"
        return challenge(arms, seed)
    g = random.Random(seed).choice(games)
    plies = LIB.validate(g)
    labels = [x[0] for x in plies]
    hero_black = g.get("hero") == "black"
    flip = bool(hero_black)
    keys = [labels.index(k) for k in g["keys"]]
    base = ST.THINK_SECONDS[arms.get("think_time", "normal")]
    moves = " ".join(labels)
    if MOCK:
        S = _mock_legendary(g, labels, keys)
    else:
        S = _ask(f"""{STYLE}
{RETENTION}
PLAYBOOK FROM OUR REAL RESULTS (follow it):
{ST.playbook_text() or '(none yet)'}

Write a LEGENDARY GAME video (about 1000-1250 spoken words). The game, replayed on screen:
{g['white']} vs {g['black']}, {g['event']}, {g['year']} ("{g['nickname']}").
All moves: {moves}
The video STOPS before these moves and asks the viewer to calculate: {', '.join(g['keys'])}.
Hook style: {arms['hook_style']}. Title style: {arms['title_style']}.
Only state historical facts you are sure about. Comment on moves only using the move list above.

Return JSON:
{{"titles": [3 titles, max 60 characters], "thumb_texts": [3 texts, max 4 words, UPPERCASE],
 "hook": [3 lines; the first critical position is on screen],
 "context": [{{"say": str, "card": str|null}}, 4-6 items: who, when, why this game is famous, without spoiling the moves],
 "comments": [{{"at": "a move label from the list before the first stop, e.g. '7.Qb3'", "say": "1-2 sentences"}}, 4-8 items],
 "stops": [one per stop, in order: {{"setup": [1-2 lines, no spoiler], "explain": [3-5 lines after the reveal: the calculation behind it]}}],
 "between": [{{"at": "a move label after a stop", "say": str}}, 0-6 items: comments while the game continues],
 "lessons": [{{"say": str, "card": str}}, 3 items: what this game teaches about calculation for YOUR games],
 "plug": [2 lines: StreakChess, free at {APP_URL}, daily calculation streaks],
 "outro": [2 lines: which legendary game next? ask in comments, subscribe],
 "description": "2-3 sentences", "tags": [8-12 tags]}}""")
    comments = {c.get("at"): c.get("say") for c in (S.get("comments") or []) + (S.get("between") or []) if c.get("at") in labels}
    first = plies[keys[0]][2].fen()
    ch = [{"title": "Hook", "beats": _say(_lines(S["hook"]), first, flip)},
          {"title": "The story", "beats": [{"t": "title", "text": g["nickname"], "sub": f"{g['white']} vs {g['black']} · {g['year']}"}]
           + _say(_lines(S["context"]), chess.STARTING_FEN, flip)}]
    stops = S.get("stops") or []
    i = 0; part = {"title": "The opening", "beats": [{"t": "title", "text": "The game begins"}]}
    import make_reel as R
    for si, k in enumerate(keys + [len(plies)]):
        while i < k:
            lab, san, b, mv = plies[i]
            beat = {"t": "move", "fen": b.fen(), "uci": mv.uci(), "flip": flip, "label": lab}
            if lab in comments:
                beat["text"] = f"{R.san_say(san)}. {comments[lab]}"
            beats_fast = part["beats"]; beats_fast.append(beat); i += 1
        if si == len(keys):
            break
        ch.append(part)
        lab, san, b, mv = plies[k]
        st = stops[si] if si < len(stops) else {}
        side = "White" if b.turn == chess.WHITE else "Black"
        beats = [{"t": "title", "text": f"Critical moment {si + 1}", "sub": f"{side} to move · move {b.fullmove_number}"}]
        beats += _say(_lines(st.get("setup")) or [(f"{side} to move. What would you play?", None)], b.fen(), flip)
        beats.append({"t": "countdown", "seconds": base + 10, "fen": b.fen(), "flip": flip, "prompt": f"{side} to move"})
        beats.append({"t": "move", "fen": b.fen(), "uci": mv.uci(), "flip": flip, "text": f"{g[side.lower()].split()[-1]} played {R.san_say(san)}"})
        after = b.copy(); after.push(mv)
        beats += _say(_lines(st.get("explain")), after.fen(), flip)
        i = k + 1
        part = {"title": f"Critical moment {si + 1}", "beats": beats}
    ch.append(part)
    end = plies[-1][2].copy(); end.push(plies[-1][3])
    ch.append({"title": "What it teaches you", "beats": [{"t": "title", "text": "What this game teaches you"}]
               + _say(_lines(S["lessons"]), end.fen(), flip) + _say(_lines(S.get("plug")), card=f"Free daily training: {APP_URL}")
               + _say(_lines(S["outro"]))})
    return _meta(S, ch, arms, {"fen": first, "rating": None, "side": "White" if plies[keys[0]][2].turn else "Black"},
                 {"game": g["id"]}, flip_override=flip)


# ============================================================================ shared
def _meta(S, chapters, arms, hard, sources, number=None, flip_override=None):
    titles = [t for t in (S.get("titles") or []) if t][:3] or ["Calculate like a master"]
    thumbs = [t for t in (S.get("thumb_texts") or []) if t][:3] or ["FIND THE MOVE"]
    flip = flip_override if flip_override is not None else hard.get("side") == "Black"
    return {"format": arms["format"], "arms": arms, "title": titles[0][:95], "alt_title": (titles[1:] or titles)[0][:95],
            "thumb": {"text": thumbs[0].upper(), "alt_text": (thumbs[1:] or thumbs)[0].upper(), "fen": hard["fen"],
                      "flip": flip, "number": number, "rating": hard.get("rating")},
            "description": S.get("description", ""), "tags": [t for t in S.get("tags", []) if isinstance(t, str)][:15],
            "chapters": [c for c in chapters if c["beats"]], "sources": sources}


def build(arms, seed, used_games=()):
    f = arms["format"]
    if f == "lesson":
        return lesson(arms, seed)
    if f == "legendary":
        return legendary(arms, seed, used_games)
    return challenge(arms, seed)


def word_count(plan):
    return sum(len(b.get("text", "").split()) for c in plan["chapters"] for b in c["beats"])


# ============================================================================ offline mock scripts (tests only)
def _ml(n, what):
    return [f"This is test line {k + 1} about {what}. It has about the length of a real spoken sentence for timing." for k in range(n)]


def _mock_lesson(name, n):
    return {"titles": ["The Fork Trick Most Players Miss", "Win Material With One Move"], "thumb_texts": ["ONE MOVE WINS", "SPOT IT?"],
            "hook": _ml(3, "the hook"), "intro": _ml(2, "the intro"),
            "teach1": {"title": "The idea", "lines": [{"say": s, "card": "Look for two targets"} for s in _ml(6, name)]},
            "examples": [{"setup": _ml(1, "setup"), "explain": _ml(3, "why it works")} for _ in range(n)],
            "teach2": {"title": "Find it in your games", "lines": [{"say": s, "card": "Checks, captures, threats"} for s in _ml(5, "method")]},
            "plug": _ml(2, "the app"), "recap": [{"say": s, "card": "Recap point"} for s in _ml(3, "recap")],
            "outro": _ml(2, "outro"), "description": "Test description.", "tags": ["chess", "tactics"]}


def _mock_challenge(n):
    return {"titles": ["Only 1% Solve All 10 Puzzles", "10 Puzzles From 800 to 2400"], "thumb_texts": ["99% FAIL #10", "CAN YOU?"],
            "hook": _ml(3, "the hook"), "rules": _ml(2, "rules"),
            "puzzles": [{"intro": f"Puzzle {i + 1}, warm up.", "explain": _ml(2, "the pattern")} for i in range(n)],
            "checkpoint": _ml(2, "halfway"), "plug": _ml(2, "the app"),
            "scores": [{"say": s, "card": f"{k * 3}-{k * 3 + 2} points"} for k, s in enumerate(_ml(4, "scores"))],
            "outro": _ml(2, "outro"), "description": "Test.", "tags": ["chess"]}


def _mock_legendary(g, labels, keys):
    return {"titles": [f"{g['nickname']}: Could You Find It?", "The Most Famous Sacrifice"], "thumb_texts": ["HE SACRIFICED IT ALL", "FIND IT"],
            "hook": _ml(3, "the hook"), "context": [{"say": s, "card": None} for s in _ml(4, "context")],
            "comments": [{"at": labels[2], "say": "A natural developing move."}],
            "stops": [{"setup": _ml(1, "setup"), "explain": _ml(3, "the calculation")} for _ in keys],
            "between": [], "lessons": [{"say": s, "card": "Lesson"} for s in _ml(3, "lessons")],
            "plug": _ml(2, "the app"), "outro": _ml(2, "outro"), "description": "Test.", "tags": ["chess"]}


if __name__ == "__main__":
    a = {"format": sys.argv[1] if len(sys.argv) > 1 else "lesson", "hook_style": "cold_open", "title_style": "curiosity",
         "thumb_style": "board_text", "think_time": "fast", "topic": "fork"}
    p = build(a, "test")
    print(json.dumps({k: v for k, v in p.items() if k != "chapters"}, indent=1))
    for c in p["chapters"]:
        print(f"== {c['title']}: {len(c['beats'])} beats")
    print("words:", word_count(p))
