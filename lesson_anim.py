"""Animated, step-by-step calculation lesson on the REAL puzzle position.

Every fact on screen is computed by python-chess (checks, captures, threats, loose pieces, attackers vs defenders,
king safety, candidate moves): nothing is invented. Each step gets its own narration line, arrows that grow one by one
with a soft tonal pop, pulsing square rings, a big counter ("2 CHECKS"), a checklist (STEP 1/3 -> 3/3) and notation
chips under the board. Used by the calculation-tip reels (with a designed cover) and by story episodes (compact).
"""
import math, os, re, subprocess
import chess
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter
import make_reel as R
import make_hype as HY

W, H, FPS, SR = HY.W, HY.H, HY.FPS, HY.SR
VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
PN = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook", chess.QUEEN: "queen",
      chess.KING: "king"}
C_CHECK, C_CAP, C_THREAT = (206, 92, 92), (222, 168, 92), (156, 130, 224)          # premium, slightly muted
C_ATT, C_DEF, C_CAND, C_LOOSE = (110, 188, 140), (156, 130, 224), (122, 170, 226), (232, 204, 150)
NUMW = "zero one two three four five six seven eight nine ten eleven twelve".split()

# which computed steps illustrate each tip (keys from make_tip.TIPS)
TIP_STEPS = {
    "cct": ["checks", "captures", "threats"], "forcing": ["checks", "captures", "candidates"],
    "blunder": ["their_threats", "loose", "candidates"], "candidates": ["checks", "captures", "candidates"],
    "loose": ["loose", "captures", "candidates"], "count": ["count", "captures", "candidates"],
    "king": ["king", "checks", "candidates"], "end": ["checks", "captures", "candidates"],
    "threat": ["their_threats", "loose", "candidates"], "overload": ["overload", "captures", "candidates"],
    "pin": ["pins", "candidates"], "xray": ["lines", "candidates"], "fork": ["loose", "candidates"],
    "sac": ["king", "candidates"], "deflect": ["overload", "candidates"],
    "visual": ["checks", "captures", "candidates"], "slow": ["their_threats", "checks", "candidates"],
}


def nw(n):
    return NUMW[n] if 0 <= n < len(NUMW) else str(n)


def plural(n, word):
    return f"{nw(n)} {word}{'' if n == 1 else 's'}"


# ------------------------------------------------------------------ chess facts (python-chess, no guessing)
def _side(c):
    return "White" if c == chess.WHITE else "Black"


def _defended(b, sq, color):
    return bool(b.attackers(color, sq))


def _checks(b):
    return [m for m in b.legal_moves if b.gives_check(m)]


def _captures(b):
    out = []
    for m in b.legal_moves:
        if b.is_capture(m) and not b.gives_check(m):
            out.append(m)
    def gain(m):
        v = b.piece_at(m.to_square); return VAL[v.piece_type] if v else 1
    return sorted(out, key=lambda m: -gain(m))


def _free(b, m):
    b2 = b.copy(); b2.push(m)
    return not b2.is_attacked_by(b2.turn, m.to_square)


def _quiet_threats(b):
    """Quiet moves (no check, no capture) after which the moved piece attacks an undefended or bigger enemy piece."""
    me, out = b.turn, []
    for m in b.legal_moves:
        if b.is_capture(m) or b.gives_check(m):
            continue
        b2 = b.copy(); b2.push(m)
        if b2.is_attacked_by(not me, m.to_square) and VAL[b.piece_at(m.from_square).piece_type] > 1:
            continue                                        # the piece just hangs there
        mv = b2.piece_at(m.to_square)
        for sq in b2.attacks(m.to_square):
            p = b2.piece_at(sq)
            if p and p.color != me and p.piece_type != chess.KING and \
                    (not _defended(b2, sq, not me) or VAL[p.piece_type] > VAL[mv.piece_type]):
                out.append((m, sq)); break
    out.sort(key=lambda x: -VAL[b.piece_at(x[1]).piece_type])
    return out


def _their_threats(b):
    """What the opponent would do if it were their move again (null move)."""
    if b.is_check():
        return None
    b2 = b.copy(); b2.push(chess.Move.null()); out = []
    for m in b2.legal_moves:
        tgt = b2.piece_at(m.to_square)
        if b2.gives_check(m) or (tgt and (not _defended(b2, m.to_square, tgt.color)
                                          or VAL[tgt.piece_type] > VAL[b2.piece_at(m.from_square).piece_type])):
            out.append(m)
    out.sort(key=lambda m: (not b2.gives_check(m), -(VAL[b2.piece_at(m.to_square).piece_type] if b2.piece_at(m.to_square) else 0)))
    return out, b2


def _loose(b):
    """Hanging pieces (attacked, undefended) first; then undefended pieces off their home rank."""
    out = []
    for sq, p in b.piece_map().items():
        if p.piece_type == chess.KING or _defended(b, sq, p.color):
            continue
        hanging = b.is_attacked_by(not p.color, sq)
        home = chess.square_rank(sq) == (0 if p.color == chess.WHITE else 7)
        if hanging or (not home and p.piece_type != chess.PAWN):
            out.append((sq, p, hanging))
    out.sort(key=lambda x: (not x[2], x[1].piece_type == chess.PAWN, -VAL[x[1].piece_type]))
    return out


def _san(b, m):
    try:
        return b.san(m)
    except Exception:
        return m.uci()


def _ranked_candidates(b, n=3):
    """Forcing first: checks, then captures (biggest prize first), then quiet threats."""
    seen, out = set(), []
    def add(m):
        if m.uci() not in seen and len(out) < n:
            seen.add(m.uci()); out.append(m)
    ch = sorted(_checks(b), key=lambda m: -(VAL[b.piece_at(m.to_square).piece_type] if b.piece_at(m.to_square) else 0))
    for m in ch[:2]: add(m)
    for m in _captures(b): add(m)
    for m, _ in _quiet_threats(b): add(m)
    for m in ch: add(m)
    if len(out) < n:                       # never leave one lonely candidate (that would give the answer away):
        def activity(m):                   # fill with the most active quiet moves, like a real player would list
            b2 = b.copy(); b2.push(m)
            return len(b2.attacks(m.to_square))
        quiet = [m for m in b.legal_moves if m.uci() not in seen and b.piece_at(m.from_square).piece_type
                 not in (chess.KING, chess.PAWN)] or [m for m in b.legal_moves if m.uci() not in seen]
        for m in sorted(quiet, key=lambda m: -activity(m)): add(m)
    return out


OPT_COL = [(212, 175, 106), (122, 170, 226), (176, 140, 230), (110, 188, 140)]     # A gold, B blue, C violet, D green


def options(b, solution, n=4, seed=0):
    """The 4 candidate moves shown in the lesson AND asked in the puzzle (A-D). Always contains the solution, the
    others are the most forcing alternatives; the order is shuffled so the answer is not always A."""
    import random as _r
    ms = [m for m in _ranked_candidates(b, n + 3) if m != solution][: n - 1]
    if solution is not None and solution in b.legal_moves:
        ms.append(solution)
    _r.Random(f"{b.fen()}-{seed}").shuffle(ms)
    return ms[:n]


def step_facts(b, kind, options=None):
    """One lesson step: what to draw and the true facts to narrate."""
    me, opp = _side(b.turn), _side(not b.turn)
    s = {"kind": kind, "arrows": [], "rings": [], "chips": [], "badges": []}
    if kind == "checks":
        ms = _checks(b)
        s.update(title="CHECKS", count=f"{len(ms)} CHECK{'S' if len(ms) != 1 else ''}" if ms else "NO CHECKS", color=C_CHECK,
                 arrows=[(m.from_square, m.to_square, C_CHECK) for m in ms[:5]], chips=[_san(b, m) for m in ms[:5]], moves=ms[:5])
        pieces = sorted({PN[b.piece_at(m.from_square).piece_type] for m in ms})
        s["fact"] = (f"{me} has {plural(len(ms), 'check')} here, with the {' and the '.join(pieces)}."
                     if ms else f"{me} has no checks here, so move straight on.")
        s["say"] = (f"{me} has {plural(len(ms), 'check')}. Look at every single one, even the crazy ones."
                    if ms else "There are none here, so we move straight on.")
    elif kind == "captures":
        ms = _captures(b)[:5]
        free = [m for m in ms if _free(b, m)]
        s.update(title="CAPTURES", count=f"{len(ms)} CAPTURE{'S' if len(ms) != 1 else ''}" if ms else "NO CAPTURES", color=C_CAP,
                 arrows=[(m.from_square, m.to_square, C_CAP) for m in ms],
                 rings=[(m.to_square, C_CAP) for m in ms],
                 chips=[_san(b, m) + (" FREE" if m in free else "") for m in ms], moves=ms)
        s["fact"] = (f"{me} has {plural(len(ms), 'capture')}; {nw(len(free))} of them win{'s' if len(free) == 1 else ''} "
                     f"a piece that is not defended." if ms else f"{me} has no captures.")
        s["say"] = (f"{plural(len(ms), 'capture').capitalize()}, and {nw(len(free))} "
                    f"{'takes' if len(free) == 1 else 'take'} something for free. Ask: who recaptures?"
                    if ms else "None here, so the next step matters even more.")
    elif kind == "threats":
        ts = _quiet_threats(b)[:3]
        s.update(title="THREATS", count=f"{len(ts)} THREAT{'S' if len(ts) != 1 else ''}" if ts else "NO THREATS", color=C_THREAT,
                 arrows=[(m.from_square, m.to_square, C_THREAT) for m, _ in ts],
                 rings=[(sq, C_THREAT) for _, sq in ts], chips=[_san(b, m) for m, _ in ts], moves=[m for m, _ in ts])
        s["fact"] = (f"{me} has {plural(len(ts), 'quiet move')} that attack an undefended or bigger enemy piece."
                     if ts else "There are no strong quiet threats.")
        s["say"] = (f"Quiet moves that attack something. {plural(len(ts), 'move').capitalize()} like that here."
                    if ts else "Quiet moves that attack something. None strong here.")
    elif kind == "their_threats":
        res = _their_threats(b)
        if res is None:
            kings = b.king(b.turn); chk = list(b.checkers())
            s.update(title="THEIR THREAT", count="YOU ARE IN CHECK", color=C_THREAT,
                     arrows=[(c, kings, C_THREAT) for c in chk], rings=[(kings, C_CHECK)], chips=[])
            s["fact"] = f"{me} is in check, so the first job is to answer the check."
            s["say"] = f"What does {opp} want? Here {me} is in check, so that comes first."
        else:
            ms, b2 = res
            ms = ms[:4]
            s.update(title="THEIR THREATS", count=f"{len(ms)} THREAT{'S' if len(ms) != 1 else ''}" if ms else "NO THREATS",
                     color=C_THREAT, arrows=[(m.from_square, m.to_square, C_THREAT) for m in ms],
                     rings=[(m.to_square, C_THREAT) for m in ms if b2.piece_at(m.to_square)],
                     chips=[_san(b2, m) for m in ms])
            s["fact"] = (f"If {opp} could move again, they would have {plural(len(ms), 'dangerous move')} "
                         f"(checks or winning captures)." if ms else f"{opp} has no direct threat right now.")
            s["say"] = (f"Imagine it is {opp}'s move. They have {plural(len(ms), 'dangerous idea')}. Know them before you attack."
                        if ms else f"Imagine it is {opp}'s move. No direct threat, so you are free to attack.")
    elif kind == "loose":
        ls = _loose(b)[:6]
        mine = [x for x in ls if x[1].color == b.turn]; theirs = [x for x in ls if x[1].color != b.turn]
        s.update(title="LOOSE PIECES", count=f"{len(ls)} LOOSE" if ls else "ALL DEFENDED", color=C_LOOSE,
                 rings=[(sq, C_CHECK if hang else C_LOOSE) for sq, p, hang in ls],
                 chips=[f"{PN[p.piece_type].upper()} {chess.square_name(sq)}" + (" HANGS" if hang else "") for sq, p, hang in ls[:4]])
        s["fact"] = f"{opp} has {plural(len(theirs), 'undefended piece')}, {me} has {nw(len(mine))}."
        s["say"] = (f"Nobody defends them. {opp} has {nw(len(theirs))}, {me} has {nw(len(mine))}. "
                    f"Loose pieces drop off.")
    elif kind == "count":
        best = None
        for sq, p in b.piece_map().items():
            if p.color == b.turn or p.piece_type == chess.KING:
                continue
            a, d = b.attackers(b.turn, sq), b.attackers(not b.turn, sq)
            if a:
                key = (len(a) - len(d), VAL[p.piece_type])
                if best is None or key > best[0]:
                    best = (key, sq, a, d)
        if best is None:
            return step_facts(b, "captures")
        _, sq, a, d = best
        s.update(title="COUNT", count=f"{len(a)} VS {len(d)}", color=C_ATT,
                 arrows=[(x, sq, C_ATT) for x in list(a)[:4]] + [(x, sq, C_DEF) for x in list(d)[:4]],
                 rings=[(sq, C_LOOSE)], chips=[f"ATTACKERS {len(a)}", f"DEFENDERS {len(d)}"])
        nm = PN[b.piece_at(sq).piece_type]
        s["fact"] = f"The {opp} {nm} is attacked {nw(len(a))} times and defended {nw(len(d))} times."
        s["say"] = (f"Count on the key square. The {nm} has {plural(len(a), 'attacker')} and {plural(len(d), 'defender')}. "
                    f"{'More attackers means it can fall.' if len(a) > len(d) else 'Not enough attackers yet.'}")
    elif kind == "king":
        k = b.king(not b.turn)
        zone = list(b.attacks(k))
        hit = [z for z in zone if b.is_attacked_by(b.turn, z)]
        defs = [z for z in zone if b.piece_at(z) and b.piece_at(z).color != b.turn]
        att = []
        for z in hit:
            for x in b.attackers(b.turn, z):
                if (x, z) not in att: att.append((x, z))
        rank = chess.square_rank(k); back = rank in (0, 7)
        fwd = 1 if rank == 0 else -1
        luft = [chess.square(f, rank + fwd) for f in range(max(0, chess.square_file(k) - 1), min(7, chess.square_file(k) + 1) + 1)] if back else []
        weak = back and all(b.piece_at(q) and b.piece_at(q).color != b.turn for q in luft)
        s.update(title="KING SAFETY", count=f"{len(hit)} SQUARE{'S' if len(hit) != 1 else ''} HIT", color=C_CHECK,
                 arrows=[(x, z, C_CHECK) for x, z in att[:5]], rings=[(z, C_CHECK) for z in hit] + [(k, C_LOOSE)],
                 chips=[f"DEFENDERS {len(defs)}", f"BACK RANK {'WEAK' if weak else 'OK'}"])
        s["fact"] = (f"{plural(len(hit), 'square').capitalize()} around the {opp} king {'is' if len(hit) == 1 else 'are'} attacked; it has {plural(len(defs), 'defender')} "
                     f"next to it{'; the back rank is weak' if weak else ''}.")
        s["say"] = (f"Look at the {opp} king. {plural(len(hit), 'square').capitalize()} around it {'is' if len(hit) == 1 else 'are'} attacked, and it has "
                    f"{plural(len(defs), 'defender')}{'. The back rank is weak' if weak else ''}.")
    elif kind == "overload":
        found = None
        for sq, p in b.piece_map().items():
            if p.color == b.turn:
                continue
            guards = [t for t in b.attacks(sq) if b.piece_at(t) and b.piece_at(t).color == p.color
                      and b.is_attacked_by(b.turn, t) and len(b.attackers(p.color, t)) == 1]
            if len(guards) >= 2:
                found = (sq, guards); break
        if not found:
            return step_facts(b, "loose")
        sq, g = found
        s.update(title="OVERLOADED", count="1 DEFENDER, 2 JOBS", color=C_THREAT,
                 arrows=[(sq, t, C_DEF) for t in g[:3]], rings=[(sq, C_CHECK)] + [(t, C_LOOSE) for t in g[:3]],
                 chips=[f"{PN[p.piece_type].upper()} {chess.square_name(sq)}"])
        s["fact"] = f"One {opp} {PN[b.piece_at(sq).piece_type]} is the only defender of {nw(len(g))} attacked pieces."
        s["say"] = (f"This {PN[b.piece_at(sq).piece_type]} guards {nw(len(g))} pieces alone. "
                    f"It cannot do both jobs.")
    elif kind == "pins":
        pins = []
        for sq, p in b.piece_map().items():
            if p.color != b.turn and p.piece_type != chess.KING and b.is_pinned(p.color, sq):
                ray = [x for x in b.pin(p.color, sq) if b.piece_at(x) and b.piece_at(x).color == b.turn
                       and b.piece_at(x).piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN)]
                if ray: pins.append((ray[0], sq, b.king(p.color)))
        if not pins:
            return step_facts(b, "loose")
        s.update(title="PINS", count=f"{len(pins)} PINNED", color=C_THREAT,
                 arrows=[(a, k, C_THREAT) for a, sq, k in pins[:3]], rings=[(sq, C_CHECK) for a, sq, k in pins[:3]],
                 chips=[f"{PN[b.piece_at(sq).piece_type].upper()} {chess.square_name(sq)} PINNED" for a, sq, k in pins[:3]])
        nm = PN[b.piece_at(pins[0][1]).piece_type]
        s["fact"] = f"The {opp} {nm} is pinned to its king: it cannot move, so it does not really defend."
        s["say"] = f"That {nm} is pinned. It looks like a defender, but it cannot move. Count it as zero."
    elif kind == "lines":
        xr = []
        for sq, p in b.piece_map().items():
            if p.color != b.turn or p.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
                continue
            for d in ([1, -1, 8, -8] if p.piece_type == chess.ROOK else [7, 9, -7, -9] if p.piece_type == chess.BISHOP
                      else [1, -1, 8, -8, 7, 9, -7, -9]):
                x, hit = sq, []
                while True:
                    f0 = chess.square_file(x); x += d
                    if not 0 <= x < 64 or abs(chess.square_file(x) - f0) > 1: break
                    if b.piece_at(x): hit.append(x)
                    if len(hit) == 2: break
                if len(hit) == 2 and b.piece_at(hit[1]).color != b.turn and \
                        VAL[b.piece_at(hit[1]).piece_type] >= 3:
                    xr.append((sq, hit[0], hit[1]))
        if not xr:
            return step_facts(b, "king")
        s.update(title="HIDDEN LINES", count=f"{len(xr)} X-RAY{'S' if len(xr) != 1 else ''}", color=C_CAND,
                 arrows=[(a, t, C_CAND) for a, mid, t in xr[:3]], rings=[(mid, C_LOOSE) for a, mid, t in xr[:3]],
                 chips=[f"{PN[b.piece_at(a).piece_type].upper()} → {PN[b.piece_at(t).piece_type].upper()}" for a, mid, t in xr[:3]])
        s["fact"] = (f"{me} has {plural(len(xr), 'line')} where one piece stands between a long-range piece and a "
                     f"valuable target: if it moves or is removed, the line opens.")
        s["say"] = "Look through the pieces, not at them. One piece is blocking a line. Move it, and the line explodes."
    elif kind == "candidates":
        ms = options or _ranked_candidates(b, 4)
        s.update(title="CANDIDATES", count=f"{len(ms)} CANDIDATE{'S' if len(ms) != 1 else ''}", color=C_CAND,
                 arrows=[(m.from_square, m.to_square, OPT_COL[k % 4]) for k, m in enumerate(ms)],
                 badges=[(m.to_square, "ABCD"[k]) for k, m in enumerate(ms)],
                 chips=[f"{'ABCD'[k]}  {_san(b, m)}" for k, m in enumerate(ms)], moves=ms)
        s["fact"] = f"The {plural(len(ms), 'candidate move')} worth calculating, labelled A to D."
        s["say"] = (f"{nw(len(ms)).capitalize()} candidates, A to D. Calculate each one to the end before you choose.")
    return s


def solution_move(P):
    """First move of the puzzle's solution (the one the viewer must find), or None."""
    try:
        u = P["moves"].split()[1] if "fen" in P else P["sol"][0]
        return chess.Move.from_uci(u)
    except Exception:
        return None


def hide_solution(s, hide):
    """The lesson explains the PROCESS honestly: the winning move is listed like any other check, capture or
    candidate (never singled out as the answer). Masking it made the method impossible to follow."""
    s.pop("moves", None)
    return s
    mv = []
    key = (hide.from_square, hide.to_square)
    s["arrows"] = [a for a in s["arrows"] if (a[0], a[1]) != key]
    for i, m in enumerate(mv):
        if m == hide and i < len(s["chips"]):
            s["chips"][i] = (s["chips"][i].split(".")[0] + ". ?") if s["kind"] == "candidates" else "?"
            s["badges"] = [bd for bd in s["badges"] if bd[0] != m.to_square]
            if s["kind"] == "captures" and not any(o.to_square == m.to_square for o in mv if o != hide):
                s["rings"] = [r for r in s["rings"] if r[0] != m.to_square]
    return s


def lesson_steps(b, tip_key, n=2, hide=None):
    kinds = TIP_STEPS.get(tip_key, ["checks", "captures", "candidates"])
    if n < len(kinds):                      # compact version keeps the first step and the candidates
        kinds = [kinds[0], kinds[-1]] if n == 2 else kinds[:n]
    opts = options(b, hide) if hide is not None else None
    steps = [hide_solution(step_facts(b, k, opts) if k == "candidates" else step_facts(b, k), hide) for k in kinds]
    return steps


# ------------------------------------------------------------------ narration (Gemini, from the computed facts)
PROMPT = """You are a brilliant, funny chess coach recording a short calculation lesson for a vertical reel
(chess players of every age, club level). The lesson: {name} - {idea}
The position: {me} to move. These facts are COMPUTED by an engine - use them exactly, do not add others:
{facts}
Write narration: {intro}one line per step ({n} lines){outro}.
GOAL: the viewer learns HOW to calculate (a concrete action they can repeat in their own games) AND has fun.
Rules: each line {words} words, spoken style, witty and vivid (a metaphor, a playful image, a tiny joke is welcome),
precise chess, numbers as words, NO square names or notation (the notation is on screen), no invented facts or
statistics, no hype words like 'insane'. Do NOT start lines with 'Step one/two' (the screen shows the step).
Never give away which candidate wins. Each line explains what to DO in this position and why it matters here.
Be ORIGINAL: do not reuse these lines or their structure from our recent reels:
{recent}
Return JSON: {{{keys}}}"""

LINES_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lesson_lines.json")


def _recent_lines(n=24):
    try:
        import json as _j
        return _j.load(open(LINES_LOG))[-n:]
    except Exception:
        return []


def remember_lines(lines):
    """Keep the last spoken lesson lines so tomorrow's lesson sounds different."""
    try:
        import json as _j
        _j.dump((_recent_lines(200) + [l for l in lines if l])[-120:], open(LINES_LOG, "w"), indent=0)
    except Exception:
        pass


def write_lines(steps, tip, me, intro=True, mock=False):
    fallback = {"intro": f"Strong players never guess. They run the same checklist every move: {tip[1].lower()}.",
                "steps": [s["say"] for s in steps],
                "outro": "Your turn. Four candidates, one winner. Calculate!" if intro else "Your turn. Calculate!"}
    if mock:
        return fallback
    facts = "\n".join(f"Step {i + 1} ({s['title'].lower()}): {s['fact']}" for i, s in enumerate(steps))
    keys = ('"intro": str, ' if intro else "") + '"steps": [str], "outro": str'
    try:
        import reviewer
        res = reviewer._ask([{"text": PROMPT.format(name=tip[1], idea=tip[2], me=me, facts=facts, n=len(steps),
                                                    words="8-15" if intro else "7-12",
                                                    recent="\n".join("- " + l for l in _recent_lines()) or "- (none yet)",
                                                    intro="one hook line on why this method matters, then " if intro else "",
                                                    outro=", then one short line handing over to the puzzle", keys=keys)}], 0.6)
        st = [l.strip() for l in res.get("steps", []) if isinstance(l, str)]
        lines = st + [res.get("outro", "")] + ([res.get("intro", "")] if intro else [])
        bad = (len(st) != len(steps) or any(not l or len(l.split()) > (18 if intro else 15) for l in lines)
               or re.search(r"\b[a-h][1-8]\b|\d|%|percent", " ".join(lines)))
        if bad:
            raise RuntimeError("lesson lines invalid")
        out = {"intro": res.get("intro", fallback["intro"]) if intro else "", "steps": st, "outro": res["outro"]}
        remember_lines([out["intro"]] + st + [out["outro"]])
        return out
    except Exception as e:
        print("lesson narration: using computed fallback lines (", str(e)[:120], ")", flush=True)
        return fallback


# ------------------------------------------------------------------ drawing
def arrow_partial(im, frm, to, flip, color, p, width=22):
    x1, y1 = R.sq_xy(frm, flip); x2, y2 = R.sq_xy(to, flip)
    x1 += R.SQ / 2; y1 += R.SQ / 2; x2 += R.SQ / 2; y2 += R.SQ / 2
    ang = math.atan2(y2 - y1, x2 - x1); L = math.hypot(x2 - x1, y2 - y1) * max(0.05, min(1, p))
    hw, hl = 50, min(58, L * 0.6)
    pts = [(0, -width / 2), (L - hl, -width / 2), (L - hl, -hw / 2), (L, 0), (L - hl, hw / 2), (L - hl, width / 2), (0, width / 2)]
    ca, sa = math.cos(ang), math.sin(ang)
    pts = [(x1 + px * ca - py * sa, y1 + px * sa + py * ca) for px, py in pts]
    ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    d.polygon(pts, fill=color + (215,))
    d.ellipse([x1 - 14, y1 - 14, x1 + 14, y1 + 14], fill=color + (215,))
    im.alpha_composite(ov)


def ring(im, sq, flip, color, pulse):
    x, y = R.sq_xy(sq, flip); ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    a = int(110 + 120 * pulse); g = int(4 + 6 * pulse)
    d.rounded_rectangle([x + g, y + g, x + R.SQ - g, y + R.SQ - g], 18, outline=color + (a,), width=10)
    d.rounded_rectangle([x + g, y + g, x + R.SQ - g, y + R.SQ - g], 18, fill=color + (int(40 * pulse),))
    im.alpha_composite(ov)


CORNERS = [(R.SQ - 26, 26), (26, 26), (26, R.SQ - 26), (R.SQ - 26, R.SQ - 26)]


def num_badge(im, sq, flip, txt, color, s=1.0, slot=0):
    """Letter badge on a square; slot picks another corner when two options land on the same square."""
    x, y = R.sq_xy(sq, flip); r = int(30 * s)
    if r < 3: return
    ox, oy = CORNERS[slot % 4]
    cx, cy = x + ox, y + oy
    d = ImageDraw.Draw(im)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color + (255,), outline=(245, 240, 230, 255), width=3)
    t = R.text_img(txt, int(34 * s), (255, 255, 255))
    im.alpha_composite(t, (int(cx - t.width / 2), int(cy - t.height / 2) - 2))


def checklist(steps, cur, done_all=False):
    """Row of step pills: done = green with a tick, current = yellow, next = dim."""
    items = []
    for k, s in enumerate(steps):
        state = "done" if (k < cur or done_all) else ("cur" if k == cur else "next")
        bg = {"done": (20, 20, 30), "cur": (255, 255, 255), "next": (20, 20, 30)}[state]
        fg = {"done": HY.YEL, "cur": HY.INK, "next": (140, 136, 150)}[state]
        txt = f"{k + 1}  {s['title']}"
        p = R.pill(txt, 30, bg, fg=fg, padx=26, pady=10)
        if state == "done":                                    # little tick drawn as lines (no emoji font needed)
            q = Image.new("RGBA", (p.width + 44, p.height), (0, 0, 0, 0)); q.alpha_composite(p, (44, 0))
            d = ImageDraw.Draw(q); h = p.height
            d.ellipse([0, h / 2 - 19, 38, h / 2 + 19], fill=HY.YEL)
            d.line([(9, h / 2), (17, h / 2 + 8), (30, h / 2 - 8)], fill=HY.INK, width=5)
            p = q
        items.append(p)
    gap = 14
    total = sum(i.width for i in items) + gap * (len(items) - 1)
    sc = min(1.0, 1000 / total)
    if sc < 1:
        items = [i.resize((int(i.width * sc), int(i.height * sc)), Image.LANCZOS) for i in items]
        total = sum(i.width for i in items) + int(gap * sc) * (len(items) - 1)
    out = Image.new("RGBA", (total, max(i.height for i in items)), (0, 0, 0, 0)); x = 0
    for i in items:
        out.alpha_composite(i, (x, (out.height - i.height) // 2)); x += i.width + int(gap * sc)
    return out


def chips_img(chips, color, maxw=1000):
    if not chips:
        return None
    ims = [R.pill(c, 34, (20, 20, 30), fg=HY.WHITE, padx=22, pady=9) for c in chips]
    for k, im in enumerate(ims):                               # coloured dot on each chip
        q = Image.new("RGBA", (im.width + 22, im.height), (0, 0, 0, 0)); q.alpha_composite(im, (22, 0))
        ImageDraw.Draw(q).ellipse([0, im.height / 2 - 14, 28, im.height / 2 + 14], fill=color, outline=(245, 240, 230), width=2)
        ims[k] = q
    total = sum(i.width for i in ims) + 12 * (len(ims) - 1)
    sc = min(1.0, maxw / total)
    if sc < 1:
        ims = [i.resize((int(i.width * sc), int(i.height * sc)), Image.LANCZOS) for i in ims]
    total = sum(i.width for i in ims) + int(12 * sc) * (len(ims) - 1)
    out = Image.new("RGBA", (total, max(i.height for i in ims)), (0, 0, 0, 0)); x = 0
    for i in ims:
        out.alpha_composite(i, (x, (out.height - i.height) // 2)); x += i.width + int(12 * sc)
    return out


def big_count(txt, color):
    return HY.word_img(txt, 84, color, stroke=9)


ARROW_T0, ARROW_DT, ARROW_GROW = 0.45, 0.38, 0.32


def board_overlay(base, step, lt, flip, show_all=False):
    """The board at time lt inside a step: arrows grow one by one, rings pulse, number badges pop."""
    im = base.copy()
    for k, (sq, col) in enumerate(step["rings"]):
        a = 1.0 if show_all else R.clamp((lt - ARROW_T0 - 0.15 * k) / 0.3)
        if a > 0:
            ring(im, sq, flip, col, a * (0.65 + 0.35 * math.sin(lt * 5 + k)))
    for k, (f, t, col) in enumerate(step["arrows"]):
        p = 1.0 if show_all else R.ease_out((lt - ARROW_T0 - ARROW_DT * k) / ARROW_GROW)
        if p > 0:
            arrow_partial(im, f, t, flip, col, p)
    seen = {}
    for k, (sq, txt) in enumerate(step.get("badges", [])):
        s = 1.0 if show_all else R.ease_out_back(R.clamp((lt - ARROW_T0 - ARROW_DT * k - ARROW_GROW) / 0.25))
        col = OPT_COL["ABCD".index(txt) % 4] if txt in "ABCD" else C_CAND
        num_badge(im, sq, flip, txt, col, s, seen.get(sq, 0)); seen[sq] = seen.get(sq, 0) + 1
    return im


def pop_times(step):
    n = max(len(step["arrows"]), len(step["rings"]) if not step["arrows"] else 0)
    return [ARROW_T0 + ARROW_DT * k + ARROW_GROW * 0.8 for k in range(n)]


# ------------------------------------------------------------------ the segment
class Lesson:
    """Record with .record() (inside the caller's voice retry loop), then .render(out_mp4)."""

    def __init__(self, board, tip, n_steps=3, cover=True, hook="", level_label="", mock=False, hide=None):
        self.b, self.tip, self.cover, self.mock = board, tip, cover, mock
        self.flip = board.turn == chess.BLACK
        self.steps = lesson_steps(board, tip[0], n_steps, hide=hide)
        self.hook = hook or tip[1]
        self.level_label = level_label
        self.lines = write_lines(self.steps, tip, _side(board.turn), intro=cover, mock=mock)
        self.A = None

    def texts(self):
        return ([self.lines["intro"]] if self.cover else []) + self.lines["steps"] + [self.lines["outro"]]

    def styles(self):
        return (["confident hook, like a top coach"] if self.cover else []) + \
               ["clear, precise, like a grandmaster explaining"] * len(self.steps) + ["excited, handing over the challenge"]

    def record(self):
        import voice
        self.A = voice.say_many(self.texts(), speed=1.06, styles=self.styles(), one_take=True)
        return self.A

    def durations(self):
        out = []
        segs = (["intro"] if self.cover else []) + list(range(len(self.steps))) + ["outro"]
        for seg, a in zip(segs, self.A):
            d = len(a) / SR + 0.45
            if isinstance(seg, int):
                st = self.steps[seg]
                d = max(d, ARROW_T0 + ARROW_DT * max(len(st["arrows"]), 1) + ARROW_GROW + 1.0)
            out.append(max(d, 2.2))
        return segs, out

    def length(self):
        return sum(self.durations()[1]) + 0.2

    def render(self, out):
        import voice
        segs, durs = self.durations()
        starts = np.cumsum([0.0] + durs[:-1]); total = float(sum(durs)) + 0.2
        n = int(SR * (total + 0.5)); vo = np.zeros(n, np.float32); fx = np.zeros(n, np.float32)

        def put(buf, a, at, g=1.0):
            i = int(at * SR)
            if i >= n: return
            j = min(n, i + len(a)); buf[i:j] += a[: j - i] * g
        for k, (seg, a) in enumerate(zip(segs, self.A)):
            put(vo, a, starts[k] + 0.15)
            if k: put(fx, R.shimmer([659.3, 784.0, 880.0][k % 3]), starts[k] - 0.05, 0.45)
            if isinstance(seg, int):
                for pt in pop_times(self.steps[seg]):
                    put(fx, R.place(), starts[k] + pt, 0.55)
        tb = np.arange(n) / SR
        pad = sum(np.sin(2 * np.pi * f * tb) for f in (130.8, 196.0, 261.6)) * 0.022 * np.clip(tb / 1.5, 0, 1)
        mix = HY.dehiss(np.tanh((vo * 1.15 + fx + pad.astype(np.float32)) * 1.1) * 0.92)
        wav = out.replace(".mp4", "_l.wav"); sf.write(wav, mix, SR)
        words = []
        for k, (seg, a) in enumerate(zip(segs, self.A)):
            for ts, w in voice.align(a, self.texts()[k]):
                words.append((k, starts[k] + 0.15 + ts, w))

        # ---- static layers (built once)
        y = np.linspace(0, 1, H)[:, None, None]
        bg = Image.fromarray(((np.array([24, 20, 44]) * (1 - y) + np.array([8, 7, 16]) * y) * np.ones((1, W, 3))).astype(np.uint8)).convert("RGBA")
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse([W * 0.02, H * 0.28, W * 0.98, H * 0.72], fill=(212, 175, 106, 34))
        bg.alpha_composite(glow.filter(ImageFilter.GaussianBlur(150)))
        last = self.b.peek() if self.b.move_stack else None
        base = R.draw_board(self.b, self.flip, (last.from_square, last.to_square) if last else ())
        SC, CY = 0.80, 925                                # bigger board (was 0.74), inside the safe zone
        title = R.pill(self.tip[1].upper()[:34], 38, HY.YEL, fg=HY.INK, padx=34, pady=12)
        lists = [checklist(self.steps, k) for k in range(len(self.steps))] + [checklist(self.steps, 99, True)]
        counts = [big_count(s["count"], s["color"]) for s in self.steps]
        chips = [chips_img(s["chips"], s["color"]) for s in self.steps]
        your_turn = big_count("YOUR TURN", HY.YEL)
        cover = self._cover_frame(bg, base) if self.cover else None
        sub_y = 1418

        def card_of(img):
            c = R.card(img); c = c.resize((int(c.width * SC), int(c.height * SC)), Image.LANCZOS)
            return R.shadowed(c, 26, (0, 18), 150)[0]

        proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                                 "-r", str(FPS), "-i", "-", "-i", wav, "-shortest"] + HY.enc_args(out), stdin=subprocess.PIPE)
        static_cache = {}
        for fi in range(int(total * FPS)):
            t = fi / FPS
            k = min(len(starts) - 1, int(np.searchsorted(starts, t, side="right") - 1)); lt = t - starts[k]
            seg = segs[k]
            if seg == "intro":
                fr = cover.copy()
                if lt > durs[k] - 0.35:                      # quick fade into the lesson
                    a = (lt - (durs[k] - 0.35)) / 0.35
                    nxt = bg.copy(); fr = Image.blend(fr, nxt, a)
                proc.stdin.write(fr.convert("RGB").tobytes()); continue
            fr = bg.copy()
            R.paste_center(fr, title, W / 2, HY.SAFE_TOP + 30)
            if isinstance(seg, int):
                st = self.steps[seg]
                R.paste_center(fr, lists[seg], W / 2, 365, R.ease_out_back(R.clamp(lt / 0.3)) if lt < 0.3 else 1.0)
                R.paste_center(fr, counts[seg], W / 2, 468, R.ease_out_back(R.clamp((lt - 0.2) / 0.3)))
                done = lt > ARROW_T0 + ARROW_DT * len(st["arrows"]) + ARROW_GROW + 0.4
                if done:
                    key = ("s", seg)
                    if key not in static_cache:
                        static_cache[key] = card_of(board_overlay(base, st, 99, self.flip, True))
                    bimg = static_cache[key]
                    if st["rings"]:                          # keep the rings breathing
                        bimg = card_of(board_overlay(base, st, lt, self.flip, True))
                else:
                    bimg = card_of(board_overlay(base, st, lt, self.flip))
                enter = 1.0 if seg > 0 or not self.cover else R.ease_out(R.clamp(lt / 0.4))
                R.paste_center(fr, bimg, W / 2, CY + (1 - enter) * 120)
                if chips[seg] is not None:
                    a = R.clamp((lt - ARROW_T0 - 0.2) / 0.3)
                    if a > 0:
                        R.paste_center(fr, chips[seg], W / 2, 1338, R.ease_out_back(a))
            else:                                            # outro: all steps ticked, candidates kept on the board
                st = self.steps[-1]
                key = ("s", len(self.steps) - 1)
                if key not in static_cache:
                    static_cache[key] = card_of(board_overlay(base, st, 99, self.flip, True))
                R.paste_center(fr, lists[-1], W / 2, 365)
                R.paste_center(fr, your_turn, W / 2, 468, R.ease_out_back(R.clamp(lt / 0.35)))
                R.paste_center(fr, static_cache[key], W / 2, CY)
            cur = [(ts, w) for si, ts, w in words if si == k and ts <= t]
            if cur:
                idx = len(cur) - 1; s0 = (idx // 3) * 3
                grp = [w for _, w in cur[s0:idx + 1]]
                for fs in (58, 50, 44, 38):                  # always one line (never touches the chips)
                    ph = HY.phrase_img(grp, t - cur[-1][0], fs, 1040)
                    if ph.height < 150: break
                R.paste_center(fr, HY.band_img(ph.height + 60), W / 2, sub_y)
                R.paste_center(fr, ph, W / 2, sub_y)
            fr.alpha_composite(HY.vignette())
            proc.stdin.write(fr.convert("RGB").tobytes())
        proc.stdin.close(); proc.wait(); os.remove(wav)
        return total

    def _cover_frame(self, bg, base):
        """Frame 0 = the grid thumbnail: big bold title, the board already full of arrows, level tag, Vektor."""
        fr = bg.copy()
        badge = R.pill("CALCULATION MASTERCLASS", 34, (20, 16, 28), fg=HY.YEL, padx=30, pady=12)
        R.paste_center(fr, badge, W / 2, HY.SAFE_TOP + 40)
        hook = HY.fit_phrase(self.hook.split()[:6], 116, 960, 2, 70)
        hy = HY.SAFE_TOP + 90 + hook.height // 2
        R.paste_center(fr, HY.band_img(hook.height + 60), W / 2, hy)
        R.paste_center(fr, hook, W / 2, hy)
        im = base.copy()
        for st in self.steps:
            for sq, col in st["rings"][:4]:
                ring(im, sq, self.flip, col, 0.9)
            for f, t, col in st["arrows"][:3]:
                arrow_partial(im, f, t, self.flip, col, 1.0)
        c = R.card(im); sc = 0.64
        c = c.resize((int(c.width * sc), int(c.height * sc)), Image.LANCZOS)
        # premium: board sits straight
        by = hy + hook.height // 2 + 40 + c.height // 2
        R.paste_center(fr, R.shadowed(c, 30, (0, 22), 170)[0], W / 2 + 40, by)
        tag = R.pill(f"{len(self.steps)} STEPS" + (f" · {self.level_label}" if self.level_label else ""), 36, HY.RED, fg=HY.WHITE, padx=30, pady=12)
        R.paste_center(fr, tag, W / 2 + 40, by + c.height // 2 + 10)
        try:
            from mascot_rig import Mascot
            mi = Mascot().render(0.0, mood="excited", look=(0.7, -0.2))
            mi = mi.resize((int(mi.width * 0.34), int(mi.height * 0.34)), Image.BILINEAR)
            fr.alpha_composite(mi, (10, int(by + c.height // 2 - mi.height + 60)))
        except Exception as e:
            print("cover mascot skipped:", e)
        fr.alpha_composite(HY.vignette())
        return fr
