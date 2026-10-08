"""Autopilot optimiser: every reel is a small experiment, and the account learns what works by trial and error.

Each reel picks one option ("arm") for each lever below. After a reel has been live for 3+ days its real Instagram
results (performance.json, from insights.py) become its reward. Next choices use Thompson sampling: options that
perform better are chosen more and more often, weak ones fade out, and ~15% of reels keep exploring so the system
never gets stuck. Once a week a strategist agent (Gemini) reads all the results, writes playbook.md (plain-English
lessons used by the script writer and the reviewer) and may propose a couple of new options to test.

Files: strategy_arms.json (current options), strategy_report.md (what's winning, readable on GitHub), playbook.md.
"""
import datetime, json, math, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
ARMS_FILE = os.path.join(HERE, "strategy_arms.json")
REPORT = os.path.join(HERE, "strategy_report.md")
PLAYBOOK = os.path.join(HERE, "playbook.md")
PERF = os.path.join(HERE, "performance.json")
EXPLORE = float(os.environ.get("EXPLORE_RATE", "0.15"))
MIN_AGE_DAYS = 3

DEFAULT_ARMS = {
    "hook_style": [
        "mystery: open on something strange or unexpected that makes kids ask 'what happened?'",
        "challenge: open by daring the viewer ('only true chess heroes can solve this')",
        "funny_fail: open on Vektor's funny little disaster",
        "cliffhanger: open at the most tense moment, then rewind a bit",
        "big_dream: open on Vektor's dream of becoming World Champion, then today's obstacle",
        "rival: open with Bishop Blaze showing off and challenging Vektor",
    ],
    "theme": [
        "tournament game with everything at stake",
        "blitz battle against Bishop Blaze",
        "lesson or secret test from Coach King",
        "daily training to keep the streak alive",
        "school chess club with friends",
        "travelling to a new place for a tournament",
        "helping Pip or a friend who is stuck",
    ],
    "difficulty": ["basic", "intermediate", "advanced"],
    "think_time": ["fast", "normal", "long"],
    "story_length": ["short", "normal"],
}
THINK_FACTOR = {"fast": 0.75, "normal": 1.0, "long": 1.3}
WORDS = {"short": "18-24", "normal": "24-34"}


def arms():
    try:
        a = json.load(open(ARMS_FILE))
        for k, v in DEFAULT_ARMS.items():
            a.setdefault(k, v)
        return a
    except Exception:
        return {k: list(v) for k, v in DEFAULT_ARMS.items()}


def reward(r):
    """Higher is better. Views (reach) + weighted engagement (shares/saves/comments are what the algorithm loves)."""
    views = r.get("views") or r.get("reach")
    eng = (r.get("likes") or 0) + 3 * (r.get("comments") or 0) + 4 * (r.get("shares") or 0) + 3 * (r.get("saved") or 0)
    if views:
        watch = (r.get("ig_reels_avg_watch_time") or 0) / 1000.0
        return math.log1p(views) + 0.6 * math.log1p(eng) + 0.08 * min(watch, 30)
    if r.get("like_count") is not None or r.get("likes") is not None:      # no insights permission: public counts
        return math.log1p((r.get("like_count") or r.get("likes") or 0) + 3 * (r.get("comments_count") or r.get("comments") or 0))
    return None


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
    """{lever: {arm: (n, mean)}} plus the global mean/sd of rewards."""
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


def _recent_arms(n=2):
    out = []
    try:
        for line in open(os.path.join(HERE, "log.jsonl")):
            a = json.loads(line).get("arms")
            if a: out.append(a)
    except Exception:
        pass
    return out[-n:]


def choose(seed=None, fixed=None):
    """Pick one option per lever (Thompson sampling with a prior centred on the account average).
    Variety rule: the creative levers (hook_style, theme) never repeat an option used in the last 2 reels."""
    rng = random.Random(seed)
    st, mu, sd, n_total = stats()
    recent = _recent_arms(2)
    pick = {}
    for lev, d in st.items():
        if fixed and lev in fixed:
            pick[lev] = fixed[lev]; continue
        if lev in ("hook_style", "theme"):
            banned = {r.get(lev) for r in recent}
            if len(d) - len(banned & set(d)) >= 2:
                d = {a: v for a, v in d.items() if a not in banned}
        if rng.random() < EXPLORE or n_total < 6:
            pick[lev] = rng.choice(list(d)); continue
        best, best_v = None, -1e9
        for a, (n, mean) in d.items():
            m = mean if mean is not None else mu
            v = rng.gauss((m * n + mu * 1) / (n + 1), sd / math.sqrt(n + 1))
            if v > best_v:
                best, best_v = a, v
        pick[lev] = best
    return pick


def short(a):
    return a.split(":")[0]


def write_report():
    st, mu, sd, n = stats()
    lines = [f"# StreakChess autopilot - what is winning\n", f"_Updated {datetime.date.today()} · {n} reels with results "
             f"(3+ days old) · average score {mu:.2f}_\n"]
    if n < 6:
        lines.append("\nStill collecting data: options are being tested evenly for now.\n")
    for lev, d in st.items():
        lines.append(f"\n## {lev}\n\n| option | reels | avg score |\n|---|---|---|")
        for a, (k, m) in sorted(d.items(), key=lambda x: -(x[1][1] if x[1][1] is not None else -1e9)):
            lines.append(f"| {short(a)} | {k} | {'-' if m is None else f'{m:.2f}'} |")
    if os.path.exists(PLAYBOOK):
        lines.append("\n---\n" + open(PLAYBOOK).read())
    open(REPORT, "w").write("\n".join(lines) + "\n")
    return "\n".join(lines)


def playbook_text():
    try:
        return open(PLAYBOOK).read().strip()
    except Exception:
        return ""


def weekly_strategist(force=False):
    """Once a week (Mondays): Gemini reads all results and writes the playbook; may add up to 2 new options."""
    if not force and datetime.date.today().weekday() != 0:
        return "strategist: not today"
    if os.path.exists(PLAYBOOK) and not force:
        if datetime.date.fromtimestamp(os.path.getmtime(PLAYBOOK)) == datetime.date.today():
            return "strategist: already ran today"
    res = _results()
    if len(res) < 6:
        return "strategist: waiting for more results"
    import reviewer
    rows = sorted(res, key=lambda x: -x[1])
    table = "\n".join(f"- score {rw:.2f} | views {r.get('views')} | likes {r.get('likes') or r.get('like_count')} | "
                      f"comments {r.get('comments') or r.get('comments_count')} | shares {r.get('shares')} | saves {r.get('saved')} | "
                      f"\"{r.get('story')}\" | " + ", ".join(f"{k}={short(v)}" for k, v in a.items())
                      for a, rw, r in rows[:40])
    A = arms()
    out = reviewer._ask([{"text": f"""{reviewer.PRODUCER}
You are now the channel STRATEGIST. Below are real results of our reels (best first) and the options we test.
RESULTS:
{table}

CURRENT OPTIONS:
{json.dumps({k: [short(x) for x in v] for k, v in A.items()}, indent=1)}

1) Write a PLAYBOOK (max 220 words, bullet points, plain English) with concrete lessons: what hooks, themes, story
   beats, difficulty, pacing and caption styles work best for OUR audience, and what to avoid. Be specific.
2) Propose at most 2 NEW options to test (only for hook_style or theme), each as "name: one-line description",
   different from existing ones and inspired by what works.
Return JSON: {{"playbook": str, "new_options": [{{"lever": "hook_style"|"theme", "option": str}}]}}"""}], 0.5)
    pb = (out.get("playbook") or "").strip()
    if pb:
        open(PLAYBOOK, "w").write(f"# Playbook (updated {datetime.date.today()})\n\n{pb}\n")
    added = []
    for o in (out.get("new_options") or [])[:2]:
        lev, opt = o.get("lever"), (o.get("option") or "").strip()
        if lev in ("hook_style", "theme") and opt and short(opt) not in [short(x) for x in A[lev]] and len(A[lev]) < 10:
            A[lev].append(opt); added.append(short(opt))
    # retire clear losers so the pool stays focused (kept in file history)
    st, mu, sd, _ = stats()
    for lev in ("hook_style", "theme"):
        ranked = [(a, n, m) for a, (n, m) in st[lev].items() if m is not None]
        if len(A[lev]) > 4 and len(ranked) >= 4:          # at most one retirement per lever per week
            best = max(m for _, _, m in ranked)
            median = sorted(m for _, _, m in ranked)[len(ranked) // 2]
            losers = [(m, a) for a, n, m in ranked
                      if n >= 8 and m < median and m < best - 2.5 * sd / math.sqrt(n)]
            if losers:
                a = min(losers)[1]; A[lev].remove(a); added.append(f"retired {short(a)}")
    json.dump(A, open(ARMS_FILE, "w"), indent=1)
    return f"strategist: playbook updated; changes: {', '.join(added) or 'none'}"
