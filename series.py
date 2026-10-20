"""Series bible for "Vektor": a growing cast, many episode formats and settings, and a rotation that guarantees
variety (no repeated format in the last 4 episodes, no repeated spotlight character in the last 2, fresh settings).
The Story Editor agent may add one new character per week (saved in series.json, committed to the repo).
"""
import datetime, json, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(HERE, "series.json")

DEFAULT = {
    "season": 1,
    "arc": "Road to the Chessville Cup: Vektor trains to qualify for the big youth tournament at the end of the season.",
    "cast": [
        {"name": "Pip", "role": "best friend", "look": "a tiny cheerful white pawn with a big blue scarf and freckles",
         "personality": "optimistic, a bit clumsy, dreams of promoting into a queen one day"},
        {"name": "Bishop Blaze", "role": "friendly rival", "look": "a tall white bishop with cool sunglasses and a red cape",
         "personality": "show-off, competitive, secretly kind and loyal"},
        {"name": "Coach King", "role": "mentor", "look": "a wise old black king with a white beard, round glasses and a wooden cane",
         "personality": "calm, funny one-liners, believes in Vektor"},
        {"name": "Grandma Queen", "role": "family", "look": "a purple queen with a pearl crown and a knitted shawl",
         "personality": "sweet, tells legends, secretly the fastest blitz player in town"},
        {"name": "Rooky and Rocco", "role": "comic duo", "look": "twin orange castle rooks with matching headbands",
         "personality": "strong, loud, clumsy, always finish each other's sentences"},
        {"name": "Luna", "role": "newcomer", "look": "a silver knight girl with a glowing blue star-shaped mane",
         "personality": "quiet puzzle prodigy from a faraway town, mysterious, becomes a friend"},
        {"name": "Professor Pawnsworth", "role": "inventor", "look": "an old pawn with brass goggles and a lab coat",
         "personality": "builds silly chess gadgets that go wrong in funny ways"},
        {"name": "Mister Zugzwang", "role": "playful villain", "look": "a grumpy dark-green bishop with a curly moustache and a top hat",
         "personality": "loves sneaky traps and riddles, never mean, always outsmarted in the end"},
    ],
}

FORMATS = [
    "comedy mishap: something silly goes wrong and Vektor has to fix it with chess",
    "mystery: something is missing or strange in Chessville and a chess position is the clue",
    "tournament drama: a key game with everything at stake",
    "rival showdown: a challenge from Bishop Blaze or a trap from Mister Zugzwang",
    "friendship: Vektor helps a friend who is stuck or sad",
    "adventure trip: Vektor travels somewhere new and exciting",
    "invention gone wrong: one of Professor Pawnsworth's gadgets causes chaos",
    "legend: Grandma Queen tells an epic old chess legend (shown as a storybook flashback)",
    "spotlight: today a side character is the hero and Vektor supports them",
    "dream: Vektor dreams of a magical chess world",
    "festival special: a holiday, fair or celebration in Chessville",
    "race against the clock: Vektor must solve something before time runs out",
    "training with a twist: a strange new training method from Coach King",
    "newcomer: Luna or a brand-new character arrives with a challenge",
]

SETTINGS = [
    "a sunny chess park with giant outdoor boards", "a snowy mountain tournament hall", "a steam train crossing a valley",
    "the school science fair", "a beach at sunset with sand-castle chessboards", "a space museum full of planets",
    "a cosy library at night with floating lanterns", "the top of an old castle tower", "a colourful carnival",
    "a rainy café with steaming hot chocolate", "Grandma Queen's warm kitchen", "a rooftop overlooking the city",
    "an underwater aquarium tunnel", "a desert festival with balloons", "a forest camp with a campfire",
    "a jungle treehouse", "a big city skyline at night", "a pirate ship on a calm sea", "a hot-air balloon above the clouds",
    "a robot workshop full of gadgets", "a frozen lake with skating pieces", "a flower garden in spring",
    "a giant clock tower", "a moonlit observatory",
]


def load():
    try:
        d = json.load(open(FILE))
        for k, v in DEFAULT.items():
            d.setdefault(k, v)
        return d
    except Exception:
        return json.loads(json.dumps(DEFAULT))


def plan(log, seed):
    """Today's episode plan, avoiding recent formats, spotlights and settings."""
    rng = random.Random(seed); s = load()
    recent = log[-6:]
    used_f = [e.get("format") for e in recent[-4:]]
    used_s = [e.get("spotlight") for e in recent[-2:]]
    used_set = [e.get("setting") for e in recent]
    fmt = rng.choice([f for f in FORMATS if f not in used_f] or FORMATS)
    names = [c["name"] for c in s["cast"]]
    spot = rng.choice([n for n in names if n not in used_s] or names)
    setting = rng.choice([x for x in SETTINGS if x not in used_set] or SETTINGS)
    extra = rng.choice([n for n in names if n != spot]) if rng.random() < 0.5 else None
    from make_tip import TIPS                        # every episode teaches one real calculation habit
    used_l = [e.get("lesson") for e in log[-6:]]
    lesson = rng.choice([t for t in TIPS if t[0] not in used_l] or TIPS)
    prev = log[-1] if log else {}
    return {"format": fmt, "spotlight": spot, "extra": extra, "setting": setting, "arc": s["arc"], "season": s["season"],
            "lesson": lesson, "previously": prev.get("summary", ""), "teaser": prev.get("teaser", ""),
            "prev_title": prev.get("title", "")}


def cast_sheet(names=None):
    s = load()
    rows = [c for c in s["cast"] if not names or c["name"] in names]
    return "\n".join(f"- {c['name']} ({c['role']}): {c['look']}. {c['personality']}." for c in rows)


def weekly_update(log):
    """Mondays: the Story Editor may advance the season arc and add ONE new character."""
    if datetime.date.today().weekday() != 0 or len(log) < 7:
        return "series: no update today"
    s = load()
    if s.get("updated") == str(datetime.date.today()):
        return "series: already updated today"
    try:
        import agents
        res = agents._ask(f"""{agents._brief('story')}
SERIES BIBLE: arc = {s['arc']}
CAST:
{cast_sheet()}
LAST EPISODES: {json.dumps([{k: e.get(k) for k in ('title', 'summary', 'format', 'spotlight')} for e in log[-10:]], ensure_ascii=False)}

1) Write the season arc for the coming week in one sentence (it must move forward from the last episodes).
2) Optionally invent ONE new kid-friendly chess-piece character that would make the series richer (or none).
Return JSON: {{"arc": str, "new_character": {{"name": str, "role": str, "look": str, "personality": str}} | null}}""", 0.8)
    except Exception as e:
        return f"series: update skipped ({str(e)[:100]})"
    msg = []
    if isinstance(res.get("arc"), str) and 8 <= len(res["arc"].split()) <= 50:
        s["arc"] = res["arc"].strip(); msg.append("arc moved forward")
    nc = res.get("new_character")
    if isinstance(nc, dict) and all(isinstance(nc.get(k), str) and nc[k] for k in ("name", "role", "look", "personality")) \
            and nc["name"] not in [c["name"] for c in s["cast"]] and len(s["cast"]) < 14:
        s["cast"].append({k: nc[k][:160] for k in ("name", "role", "look", "personality")}); msg.append(f"new character {nc['name']}")
    s["updated"] = str(datetime.date.today())
    json.dump(s, open(FILE, "w"), indent=1, ensure_ascii=False)
    return "series: " + (", ".join(msg) or "unchanged")
