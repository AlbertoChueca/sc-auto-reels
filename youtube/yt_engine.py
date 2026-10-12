"""Stockfish helper: evaluation bar, best lines, 'tempting wrong move' facts, and tactic finding in real games.

Every chess fact the writers receive comes from here or from the puzzle/game data, never from the language model.
Stockfish path: $STOCKFISH, or `stockfish` on PATH, or /usr/games/stockfish. Without an engine everything degrades
gracefully (no eval bar, no trap facts, no trending format).
"""
import os, shutil, threading
import chess, chess.engine

_ENG = [None]
_CACHE = {}


def path():
    for p in (os.environ.get("STOCKFISH"), shutil.which("stockfish"), "/usr/games/stockfish"):
        if p and os.path.exists(p):
            return p
    return None


def engine():
    if _ENG[0] is None:
        p = path()
        if not p:
            _ENG[0] = False
        else:
            try:
                e = chess.engine.SimpleEngine.popen_uci(p)
                e.configure({"Threads": max(1, (os.cpu_count() or 2) - 1), "Hash": 256})
                _ENG[0] = e
                threading._register_atexit(close)     # before Python waits for the engine thread
            except Exception as ex:
                print("engine unavailable:", ex, flush=True); _ENG[0] = False
    return _ENG[0] or None


def close():
    e = _ENG[0]
    if e:
        try:
            e.quit()
        except Exception:
            pass
    _ENG[0] = None


def available():
    return engine() is not None


def _cp(score, pov):
    s = score.pov(pov)
    if s.is_mate():
        m = s.mate()
        return 10000 - abs(m) * 10 if m > 0 else -10000 + abs(m) * 10
    return s.score()


def analyse(fen, depth=16, multipv=1):
    """[{'cp': white-POV centipawns, 'cp_stm': side-to-move POV, 'mate': n|None, 'pv': [uci]}] best first."""
    key = (fen, depth, multipv)
    if key in _CACHE:
        return _CACHE[key]
    e = engine()
    if not e:
        return None
    b = chess.Board(fen)
    if b.is_game_over():
        res = [{"cp": (-10000 if b.turn == chess.WHITE else 10000) if b.is_checkmate() else 0, "cp_stm": -10000 if b.is_checkmate() else 0,
                "mate": 0 if b.is_checkmate() else None, "pv": []}]
        _CACHE[key] = res
        return res
    info = e.analyse(b, chess.engine.Limit(depth=depth), multipv=multipv)
    info = info if isinstance(info, list) else [info]
    res = []
    for i in info:
        sc = i["score"]
        m = sc.pov(b.turn).mate() if sc.is_mate() else None
        res.append({"cp": _cp(sc, chess.WHITE), "cp_stm": _cp(sc, b.turn), "mate": m, "pv": [x.uci() for x in i.get("pv", [])]})
    _CACHE[key] = res
    return res


def eval_white(fen, depth=14):
    r = analyse(fen, depth)
    return r[0]["cp"] if r else None


def fmt(cp):
    if cp is None:
        return ""
    if abs(cp) >= 9000:
        n = (10000 - abs(cp)) // 10
        return f"M{n}" if cp > 0 else f"-M{n}"
    return f"{cp / 100:+.1f}"


def pv_san(fen, pv, n=6):
    b = chess.Board(fen); out = []
    for u in pv[:n]:
        m = chess.Move.from_uci(u)
        if not b.is_legal(m):
            break
        out.append(b.san(m)); b.push(m)
    return out


def traps(fen, solution_first, k=2, depth=16):
    """Tempting alternatives to the solution: legal moves that look active (checks/captures/threats on the king side)
    but are clearly worse. Returns [{'san', 'refutation': [san...], 'eval_after': str}] (engine verified)."""
    e = engine()
    if not e:
        return []
    b = chess.Board(fen); me = b.turn
    cands = []
    for m in b.legal_moves:
        if m.uci() == solution_first:
            continue
        active = b.is_capture(m) or b.gives_check(m)
        if not active:
            continue
        val = b.piece_at(m.to_square)
        prio = (3 if b.gives_check(m) else 0) + (chess.PIECE_TYPES.index(val.piece_type) if val else 0)
        cands.append((prio, m))
    cands.sort(key=lambda x: -x[0])
    best = analyse(fen, depth)[0]["cp_stm"]
    out = []
    for _, m in cands[:8]:
        b2 = b.copy(); san = b.san(m); b2.push(m)
        r = analyse(b2.fen(), depth)
        if not r:
            continue
        mine = -r[0]["cp_stm"]
        if best - mine >= 200 and mine < 150:
            out.append({"san": san, "refutation": pv_san(b2.fen(), r[0]["pv"], 4),
                        "eval_after": fmt(r[0]["cp"])})
        if len(out) >= k:
            break
    return out


def find_moments(game, depth=12, min_swing=250, max_plies=160):
    """Tactical moments in a chess.pgn.Game: positions where the side to move had a decisive shot after the opponent's
    mistake. Returns [{'fen','side','best_san','pv':[san],'played_san','found':bool,'swing','eval_before','eval_after',
    'ply','move_label'}]."""
    e = engine()
    if not e:
        return []
    b = game.board(); prev_stm = None; out = []
    nodes = list(game.mainline())[:max_plies]
    for node in nodes:
        mv = node.move
        fen = b.fen()
        r = analyse(fen, depth, multipv=2)
        if not r:
            break
        best = r[0]; cur = best["cp_stm"]
        if prev_stm is not None:
            before = -prev_stm                                    # same side's view before the opponent's move
            second = r[1]["cp_stm"] if len(r) > 1 else -10000
            if cur - before >= min_swing and cur >= 250 and before <= 120 and cur - second >= 150 and best["pv"]:
                num = b.fullmove_number
                label = f"{num}." if b.turn == chess.WHITE else f"{num}..."
                out.append({"fen": fen, "side": "White" if b.turn == chess.WHITE else "Black",
                            "best_san": b.san(chess.Move.from_uci(best["pv"][0])), "pv": pv_san(fen, best["pv"], 5),
                            "pv_uci": best["pv"][:5], "played_san": b.san(mv), "found": mv.uci() == best["pv"][0],
                            "swing": cur - before, "eval_before": fmt(before if b.turn == chess.WHITE else -before),
                            "eval_after": fmt(best["cp"]), "move_label": label})
        prev_stm = cur
        b.push(mv)
    return out
