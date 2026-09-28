"""Select a fresh Lichess puzzle for a given level, never repeating one already used.

The full Lichess puzzle database (~5M puzzles, CC0) is downloaded once and reduced to a
small, high-quality subset that is cached between runs (data/puzzles_filtered.csv).
"""
import csv, io, json, os, random, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
FILTERED = os.path.join(DATA, "puzzles_filtered.csv")
USED = os.path.join(HERE, "used.json")
DB_URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"

LEVEL_RANGES = {"basic": (800, 1200), "intermediate": (1200, 1900), "advanced": (1900, 2500)}
MAX_PLIES = {"basic": 5, "intermediate": 7, "advanced": 7}   # solution length incl. replies


def good(row):
    """Quality filter: popular, well-rated puzzles with a clear, satisfying finish."""
    try:
        r, rd, pop, plays = int(row["Rating"]), int(row["RatingDeviation"]), int(row["Popularity"]), int(row["NbPlays"])
    except (KeyError, ValueError):
        return False
    if not (800 <= r <= 2500) or rd > 90 or pop < 90 or plays < 800:
        return False
    th = row["Themes"].split()
    if not any(t.startswith("mate") or t == "crushing" for t in th):
        return False
    return len(row["Moves"].split()) - 1 <= 7


def build_filtered():
    import zstandard
    os.makedirs(DATA, exist_ok=True)
    print("Downloading Lichess puzzle database...", flush=True)
    kept = 0
    with urllib.request.urlopen(DB_URL) as resp, open(FILTERED, "w", newline="") as out:
        reader = io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(resp), encoding="utf-8")
        rows = csv.DictReader(reader)
        w = csv.DictWriter(out, fieldnames=["PuzzleId", "FEN", "Moves", "Rating", "Popularity", "NbPlays", "Themes"])
        w.writeheader()
        for row in rows:
            if good(row):
                w.writerow({k: row[k] for k in w.fieldnames}); kept += 1
    print(f"Kept {kept} puzzles", flush=True)


def load_used():
    return json.load(open(USED)) if os.path.exists(USED) else []


def mark_used(pid):
    used = load_used(); used.append(pid)
    json.dump(used, open(USED, "w"), indent=0)


def pick(level, seed=None):
    if not os.path.exists(FILTERED):
        build_filtered()
    lo, hi = LEVEL_RANGES[level]
    used = set(load_used())
    cands = []
    with open(FILTERED) as f:
        for row in csv.DictReader(f):
            r = int(row["Rating"])
            plies = len(row["Moves"].split()) - 1
            if lo <= r < hi and plies <= MAX_PLIES[level] and row["PuzzleId"] not in used:
                cands.append(row)
    if not cands:
        raise SystemExit(f"No unused puzzles left for {level}")
    # prefer checkmates (more satisfying reveal), then popularity
    mates = [c for c in cands if any(t.startswith("mateIn") for t in c["Themes"].split())]
    pool = mates if len(mates) > 50 else cands
    pool.sort(key=lambda c: -int(c["Popularity"]))
    pool = pool[:5000]
    row = random.Random(seed).choice(pool)
    return {"level": level, "id": row["PuzzleId"], "rating": int(row["Rating"]),
            "fen": row["FEN"], "moves": row["Moves"], "themes": row["Themes"]}


if __name__ == "__main__":
    print(json.dumps(pick(sys.argv[1]), indent=1))
