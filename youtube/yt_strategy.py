"""Autopilot for the long-video channel: every video is an experiment.

Same idea as the reels' strategy.py, with YouTube's own success signals: click-through rate on the thumbnail,
how much of the video people watch (average view percentage), subscribers gained and views. Results arrive from
YouTube Analytics (yt_api.analytics) into yt_performance.json; videos count once they are 5+ days old.
Choices use Thompson sampling with ~15% exploration; creative levers never repeat the last video's option.
Mondays a strategist (Gemini) rewrites yt_playbook.md and may add or retire options.
"""
import datetime, json, math, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
ARMS_FILE = os.path.join(HERE, "yt_arms.json")
PERF = os.path.join(HERE, "yt_performance.json")
LOG = os.path.join(HERE, "yt_log.jsonl")
REPORT = os.path.join(HERE, "yt_report.md")
PLAYBOOK = os.path.join(HERE, "yt_playbook.md")
EXPLORE = float(os.environ.get("EXPLORE_RATE", "0.15"))
MIN_AGE_DAYS = 5

DEFAULT_ARMS = {
    "format": ["gym", "streak", "legendary", "trending"],
    "hook_style": [
        "cold_open: start on the hardest position of the video and say most players miss it",
        "shock_stat: open with a surprising, true observation about how club players lose games to missed tactics",
        "promise: promise one concrete skill the viewer will have by the end of the video",
        "story: open with a short, vivid scene of a game decided by one calculation",
        "challenge: dare the viewer to beat the video and keep score",
    ],
    "title_style": [
        "curiosity: a curiosity gap that makes people need to know the answer",
        "benefit: the concrete improvement the viewer gets",
        "challenge: dares the viewer (can you...?)",
        "number: a specific number (10 puzzles, 3 steps, 1 move)",
    ],
    "thumb_style": ["board_text", "big_number", "question"],
    "think_time": ["fast", "normal", "long"],
}
THINK_SECONDS = {"fast": 12, "normal": 20, "long": 30}
CREATIVE = ("format", "hook_style", "title_style")


def arms():
    try:
        a = json.load(open(ARMS_FILE))
        for k, v in DEFAULT_ARMS.items():
            a.setdefault(k, v)
        return a
    except Exception:
        return {k: list(v) for k, v in DEFAULT_ARMS.items()}


def short(a):
    return a.split(":")[0]


def reward(r):
    """Higher is better. Views on a log scale + watch share + subscribers + thumbnail CTR when YouTube reports it."""
    v = r.get("views")
    if v is None:
        return None
    s = math.log1p(v) + 0.04 * (r.get("averageViewPercentage") or 0) + 0.6 * math.log1p(r.get("subscribersGained") or 0)
    s += 0.3 * math.log1p((r.get("likes") or 0) + 3 * (r.get("comments") or 0) + 3 * (r.get("shares") or 0))
    if r.get("ctr") is not None:
        s += 0.15 * r["ctr"]                                   # ctr in percent (e.g. 5.2)
    return s


def _results():
    try:
        perf = json.load(open(PERF))
    except Exception:
        return []
    today = datetime.date.today(); out = []
    for r in perf.values():
        try:
            if (today - datetime.date.fromisoformat(r["date"])).days < MIN_AGE_DAYS:
                continue
        except Exception:
            continue
        rw = reward(r)
        if rw is not None and r.get("arms"):
            out.append((r["arms"], rw, r))
    return out


def stats():
    res = _results(); A = arms()
    vals = [rw for _, rw, _ in res]
    mu = sum(vals) / len(vals) if vals else 0.0
    sd = (sum((v - mu) ** 2 for v in vals) / len(vals)) ** 0.5 if len(vals) > 1 else 1.0
    st = {lev: {a: [0, 0.0] for a in opts} for lev, opts in A.items()}
    for chosen, rw, _ in res:
        for lev, a in chosen.items():
            if lev in st and a in st[lev]:
                st[lev][a][0] += 1; st[lev][a][1] += rw
    out = {lev: {a: (n, (s / n if n else None)) for a, (n, s) in d.items()} for lev, d in st.items()}
    return out, mu, max(sd, 0.3), len(res)


def recent(n=3):
    out = []
    try:
        for line in open(LOG):
            a = json.loads(line).get("arms")
            if a: out.append(a)
    except Exception:
        pass
    return out[-n:]


def choose(seed=None, fixed=None):
    rng = random.Random(seed)
    st, mu, sd, n_total = stats()
    last = recent(3)
    pick = {}
    for lev, d in st.items():
        if fixed and fixed.get(lev):
            pick[lev] = fixed[lev]; continue
        ban = {r.get(lev) for r in last[-1:]} if lev in CREATIVE else set()
        dd = {a: v for a, v in d.items() if a not in ban} or d
        if rng.random() < EXPLORE or n_total < 8:
            pick[lev] = rng.choice(list(dd)); continue
        best, best_v = None, -1e9
        for a, (n, mean) in dd.items():
            m = mean if mean is not None else mu
            v = rng.gauss((m * n + mu) / (n + 1), sd / math.sqrt(n + 1))
            if v > best_v:
                best, best_v = a, v
        pick[lev] = best
    return pick


def write_report():
    st, mu, sd, n = stats()
    lines = ["# StreakChess YouTube autopilot - what is winning\n",
             f"_Updated {datetime.date.today()} · {n} videos with results (5+ days old) · average score {mu:.2f}_\n"]
    if n < 8:
        lines.append("\nStill collecting data: options are being tested evenly for now.\n")
    for lev, d in st.items():
        lines.append(f"\n## {lev}\n\n| option | videos | avg score |\n|---|---|---|")
        for a, (k, m) in sorted(d.items(), key=lambda x: -(x[1][1] if x[1][1] is not None else -1e9)):
            lines.append(f"| {short(a)} | {k} | {'-' if m is None else f'{m:.2f}'} |")
    if os.path.exists(PLAYBOOK):
        lines.append("\n---\n" + open(PLAYBOOK).read())
    open(REPORT, "w").write("\n".join(lines) + "\n")


def playbook_text():
    try:
        return open(PLAYBOOK).read().strip()
    except Exception:
        return ""


def weekly_strategist(force=False):
    if not force and datetime.date.today().weekday() != 0:
        return "strategist: not today"
    res = _results()
    if len(res) < 6:
        return "strategist: waiting for more results"
    import yt_gemini as G
    rows = sorted(res, key=lambda x: -x[1])
    table = "\n".join(f"- score {rw:.2f} | views {r.get('views')} | ctr {r.get('ctr')} | avg% {r.get('averageViewPercentage')} "
                      f"| subs {r.get('subscribersGained')} | \"{r.get('title')}\" | "
                      + ", ".join(f"{k}={short(v)}" for k, v in a.items()) for a, rw, r in rows[:40])
    A = arms()
    out = G.ask_json(f"""You are the strategist of the StreakChess YouTube channel (long videos, 8-12 min, about chess
calculation and tactics for players who want to improve). Real results, best first:
{table}

Current options per lever:
{json.dumps({k: [short(x) for x in v] for k, v in A.items()}, indent=1)}

1) Write a PLAYBOOK (max 220 words, bullets, plain English): concrete lessons about formats, topics, hooks, titles,
   thumbnails and pacing that work for OUR audience, and what to avoid.
2) Propose at most 2 NEW options (levers hook_style or title_style only), "name: one-line description".
Return JSON: {{"playbook": str, "new_options": [{{"lever": str, "option": str}}]}}""", 0.5)
    pb = (out.get("playbook") or "").strip()
    if pb:
        open(PLAYBOOK, "w").write(f"# Playbook (updated {datetime.date.today()})\n\n{pb}\n")
    added = []
    for o in (out.get("new_options") or [])[:2]:
        lev, opt = o.get("lever"), (o.get("option") or "").strip()
        if lev in ("hook_style", "title_style") and opt and short(opt) not in [short(x) for x in A[lev]] and len(A[lev]) < 9:
            A[lev].append(opt); added.append(short(opt))
    st, mu, sd, _ = stats()
    for lev in ("hook_style", "title_style"):
        ranked = [(a, n, m) for a, (n, m) in st[lev].items() if m is not None]
        if len(A[lev]) > 3 and len(ranked) >= 4:
            best = max(m for _, _, m in ranked)
            losers = [(m, a) for a, n, m in ranked if n >= 5 and m < best - 2.5 * sd / math.sqrt(n)]
            if losers:
                a = min(losers)[1]; A[lev].remove(a); added.append(f"retired {short(a)}")
    json.dump(A, open(ARMS_FILE, "w"), indent=1)
    return f"strategist: playbook updated; changes: {', '.join(added) or 'none'}"
