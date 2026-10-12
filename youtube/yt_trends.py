"""What is happening in chess right now (for the Trend Scout and the 'This Week in Chess' format).

- chess_news():      Gemini with Google Search grounding -> this week's chess stories, with sources.
- yt_suggest(q):     YouTube search autocomplete (what people type right now) for SEO.
- recent_games():    games from this week's official Lichess broadcasts (top tournaments, CC0 data).
- trending_moments(): Stockfish-verified tactical moments in those games (the 'shot' a GM found or missed).
Everything is best effort: on any error the caller falls back to evergreen content.
"""
import datetime, io, json, os, time
import requests
import chess, chess.pgn

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "yt_trends.json")
UA = {"User-Agent": "StreakChess-YouTube/1.0 (streakchess.com)"}


def yt_suggest(q):
    try:
        r = requests.get("https://suggestqueries.google.com/complete/search", timeout=15, headers=UA,
                         params={"client": "firefox", "ds": "yt", "q": q, "hl": "en"})
        return [s for s in r.json()[1] if isinstance(s, str)][:10]
    except Exception as e:
        print("suggest failed:", str(e)[:120], flush=True)
        return []


def suggestions(seeds):
    out = {}
    for s in seeds[:8]:
        out[s] = yt_suggest(s); time.sleep(0.3)
    return out


def chess_news():
    import yt_gemini as G
    today = datetime.date.today()
    data, srcs = G.ask_grounded(f"""Today is {today}. Search the web for what is happening in the chess world in the last
10 days: elite tournaments and who is leading, viral games or moments, records, big chess news, chess on social media.
Only include items you found in search results from the last 10 days; never guess.
Return JSON: {{"items": [{{"headline": str, "detail": "1-2 factual sentences", "date": "YYYY-MM-DD or approx",
"people": [names], "event": str|null, "why_viewers_care": str}}] (max 6), "search_terms": [5 phrases people search
on YouTube about chess this week]}}""")
    data["sources"] = srcs[:12]
    return data


# ------------------------------------------------------------------ Lichess broadcasts
def _broadcast_rounds(days=8):
    now = time.time() * 1000; cutoff = now - days * 86400 * 1000; rounds = []
    try:
        r = requests.get("https://lichess.org/api/broadcast", params={"nb": 40}, headers=UA, timeout=30)
        for line in r.text.splitlines():
            if not line.strip():
                continue
            j = json.loads(line); tour = j.get("tour", {})
            tier = tour.get("tier") or 0
            for rd in j.get("rounds", []):
                st = rd.get("startsAt") or rd.get("createdAt") or 0
                if cutoff <= st <= now and (rd.get("finished") or rd.get("ongoing") or st < now - 3 * 3600 * 1000):
                    rounds.append({"tour": tour.get("name"), "tier": tier, "round": rd.get("name"), "id": rd["id"], "t": st})
    except Exception as e:
        print("broadcast list failed:", str(e)[:150], flush=True)
    rounds.sort(key=lambda x: (-(x["tier"] or 0), -x["t"]))
    return rounds


def recent_games(max_games=40, min_elo=2450, days=8):
    games = []
    for rd in _broadcast_rounds(days)[:25]:
        try:
            r = requests.get(f"https://lichess.org/api/broadcast/round/{rd['id']}.pgn", headers=UA, timeout=60)
            pgn = io.StringIO(r.text)
            while len(games) < max_games:
                g = chess.pgn.read_game(pgn)
                if g is None:
                    break
                h = g.headers
                try:
                    we, be = int(h.get("WhiteElo", 0)), int(h.get("BlackElo", 0))
                except ValueError:
                    continue
                if min(we, be) < min_elo or len(list(g.mainline_moves())) < 24:
                    continue
                g.headers["_tour"] = rd["tour"] or h.get("Event", ""); g.headers["_round"] = rd["round"] or ""
                games.append(g)
        except Exception as e:
            print("round pgn failed:", str(e)[:120], flush=True)
        if len(games) >= max_games:
            break
        time.sleep(1)
    return games


def trending_moments(n=4, budget_s=600):
    """Best tactical moments of the week (one per game), ranked by drama: decisive swing, famous players, and
    'missed' shots first (even a GM missed it)."""
    import yt_engine as E
    if not E.available():
        return []
    t0 = time.time(); found = []
    for g in recent_games():
        if time.time() - t0 > budget_s:
            break
        try:
            ms = E.find_moments(g)
        except Exception as e:
            print("analysis failed:", str(e)[:100], flush=True); continue
        if not ms:
            continue
        h = g.headers
        m = max(ms, key=lambda x: min(x["swing"], 2000))
        elo = (int(h.get("WhiteElo", 0)) + int(h.get("BlackElo", 0))) / 2
        m.update(white=h.get("White"), black=h.get("Black"), white_elo=h.get("WhiteElo"), black_elo=h.get("BlackElo"),
                 event=h.get("_tour") or h.get("Event"), round=h.get("_round") or h.get("Round"), date=h.get("Date"),
                 result=h.get("Result"), score=min(m["swing"], 2000) / 100 + (elo - 2400) / 60 + (3 if not m["found"] else 0))
        found.append(m)
    found.sort(key=lambda x: -x["score"])
    return found[:n]


def brief(force=False):
    """Trend brief for today (cached in yt_trends.json so several agents share one search)."""
    today = datetime.date.today().isoformat()
    try:
        c = json.load(open(CACHE))
        if c.get("date") == today and not force:
            return c
    except Exception:
        pass
    out = {"date": today, "news": {}, "suggest": {}}
    if not os.environ.get("YT_MOCK"):
        try:
            out["news"] = chess_news()
        except Exception as e:
            print("news search failed:", str(e)[:200], flush=True)
        seeds = ["chess tactics", "chess puzzles", "how to calculate in chess", "chess tricks"] + \
                [s for s in (out["news"].get("search_terms") or [])[:3]]
        out["suggest"] = suggestions(seeds)
    json.dump(out, open(CACHE, "w"), indent=1)
    return out
