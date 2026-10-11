"""Puzzles for the long videos, from the Lichess puzzle database (CC0) already used by the reels.

Shares used.json with the reels, so a puzzle never appears twice on the brand (reel or long video).
Normalised puzzle: {"id", "fen" (position to solve, side to move), "sol" [uci...], "rating", "themes" [..],
"san" [..], "side": "White"/"Black", "material": human summary of what the line wins}.
YT_MOCK=1 uses positions taken from the legendary-games library (offline tests, no download).
"""
import csv, os, random, sys
import chess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import pick_puzzles as PP                      # noqa: E402

VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
PNAME = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop", chess.ROOK: "rook", chess.QUEEN: "queen"}

# lesson topics -> Lichess themes (each video teaches one idea with 4 examples of growing difficulty)
TOPICS = {
    "fork": ("The fork: one move, two targets", ["fork"]),
    "pin": ("Pins: the piece that cannot move", ["pin"]),
    "skewer": ("Skewers: attack through the big piece", ["skewer"]),
    "deflection": ("Deflection: drag the defender away", ["deflection"]),
    "attraction": ("Decoys: lure the king into the trap", ["attraction"]),
    "discovered": ("Discovered attacks: the hidden second attacker", ["discoveredAttack"]),
    "backrank": ("The back rank: the most common mate in club chess", ["backRankMate"]),
    "intermezzo": ("In-between moves that change everything", ["intermezzo"]),
    "quiet": ("Quiet moves: when the best move is not a check", ["quietMove"]),
    "sacrifice": ("Sacrifices: calculate before you give material", ["sacrifice"]),
    "clearance": ("Clearance: get your own piece out of the way", ["clearance"]),
    "checklist": ("Checks, captures, threats: how strong players calculate", ["mateIn2", "mateIn3", "crushing"]),
    "mate3": ("Calculating forced mates three moves deep", ["mateIn3"]),
    "smothered": ("Smothered mate: when the king is trapped by its own army", ["smotheredMate"]),
    "xray": ("X-rays: seeing through pieces", ["xRayAttack"]),
    "candidates": ("Candidate moves: the habit that stops blunders", ["advantage", "crushing"]),
}


def normalise(row):
    b = chess.Board(row["FEN"])
    mv = row["Moves"].split()
    b.push_uci(mv[0])
    fen = b.fen(); side = "White" if b.turn == chess.WHITE else "Black"
    return finish({"id": row["PuzzleId"], "fen": fen, "sol": mv[1:], "rating": int(row["Rating"]),
                   "themes": row["Themes"].split(), "side": side})


def finish(p):
    """Add SAN moves and a factual material summary (computed, never guessed by the writer)."""
    b = chess.Board(p["fen"]); me = b.turn; san, won, lost = [], [], []
    for u in p["sol"]:
        m = chess.Move.from_uci(u)
        if not b.is_legal(m):
            raise ValueError(f"illegal solution move {u} in {p['id']}")
        cap = b.piece_at(m.to_square) or (b.piece_at(chess.square(chess.square_file(m.to_square), chess.square_rank(m.from_square)))
                                          if b.is_en_passant(m) else None)
        san.append(b.san(m))
        if cap:
            (won if b.turn == me else lost).append(cap.piece_type)
        b.push(m)
    p["san"] = san
    if b.is_checkmate():
        p["material"] = "it ends in checkmate"
    else:
        net = sum(VAL[x] for x in won) - sum(VAL[x] for x in lost)
        got = ", ".join(PNAME[x] for x in won) or "nothing"
        p["material"] = f"the line captures {got}; net gain {net:+d} points of material"
    p["final_fen"] = b.fen()
    return p


def _rows():
    if not os.path.exists(PP.FILTERED):
        PP.build_filtered()
    with open(PP.FILTERED) as f:
        yield from csv.DictReader(f)


def pick(themes, ratings, seed=None):
    """One unused puzzle per target rating (±150), matching any of `themes` (None = any). Marks them used."""
    if os.environ.get("YT_MOCK"):
        return mock(len(ratings), seed)
    rng = random.Random(seed); used = set(PP.load_used())
    buckets = {i: [] for i in range(len(ratings))}
    for row in _rows():
        if row["PuzzleId"] in used:
            continue
        th = row["Themes"].split()
        if themes and not any(t in th for t in themes):
            continue
        r = int(row["Rating"])
        for i, target in enumerate(ratings):
            if abs(r - target) <= 150 and len(buckets[i]) < 400:
                buckets[i].append(row); break
    out, taken = [], set()
    for i in range(len(ratings)):
        pool = [r for r in buckets[i] if r["PuzzleId"] not in taken]
        if not pool:
            continue
        pool.sort(key=lambda r: -int(r["Popularity"]))
        row = rng.choice(pool[:60])
        try:
            p = normalise(row)
        except ValueError:
            continue
        taken.add(row["PuzzleId"]); out.append(p)
    for p in out:
        PP.mark_used(p["id"])
    return out


def mock(n, seed=None):
    """Offline test puzzles: the key moments of the legendary games (solution = next 1-3 plies)."""
    import yt_library as L
    out = []
    for g in L.GAMES:
        p = L.validate(g); labels = [x[0] for x in p]
        for k in g["keys"]:
            i = labels.index(k)
            sol = [m.uci() for _, _, _, m in p[i:i + 3]]
            if len(sol) % 2 == 0:
                sol = sol[:-1]
            out.append(finish({"id": f"mock-{g['id']}-{i}", "fen": p[i][2].fen(), "sol": sol,
                               "rating": 1000 + 120 * len(out), "themes": ["sacrifice"],
                               "side": "White" if p[i][2].turn else "Black"}))
    random.Random(seed).shuffle(out)
    out = sorted(out[:n], key=lambda x: x["rating"])
    for k, p in enumerate(out):
        p["rating"] = 900 + int(1500 * k / max(1, n - 1))
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(pick(TOPICS[sys.argv[1]][1] if len(sys.argv) > 1 else None, [1000, 1500, 2000]), indent=1))
