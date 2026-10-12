"""Packaging and discoverability: Trend Scout angles, Thumbnail & Title Designer, SEO Specialist, Caption Editor."""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import yt_agents as AG                                     # noqa: E402

APP_URL = os.environ.get("APP_URL", "streakchess.com")
LANGS = {"es": "Spanish", "pt": "Portuguese (Brazil)", "hi": "Hindi", "fr": "French", "de": "German"}


def scout(trends, playbook=""):
    """Trend Scout: turn the raw brief into usable angles + search phrases."""
    news = (trends.get("news") or {}).get("items", [])
    sug = trends.get("suggest") or {}
    r = AG.ask("trend_scout", f"""This week's chess news (from web search, with dates): {json.dumps(news, ensure_ascii=False)}
What people type on YouTube right now: {json.dumps(sug, ensure_ascii=False)}
Give the team: 3 angles that connect a calculation/tactics video to what's hot this week, and the 15 most useful search
phrases for our titles/tags (exact phrases from the autocomplete list when possible).
Return JSON: {{"angles": [str], "phrases": [str], "avoid": [str]}}""", 0.6, playbook) or {}
    trends["scout"] = r
    return trends


def _summary(plan):
    s = plan["sources"]; lines = plan.get("lines") or {}
    first = " ".join((lines.get("cold_open") or [])[:2])
    return (f"Series: {plan['series']} episode {plan['episode']}. Format details: {json.dumps(s, ensure_ascii=False)[:600]}. "
            f"Concept: {json.dumps(plan.get('concept') or {}, ensure_ascii=False)[:500]}. Cold open: {first}. "
            f"Coach's rule: {plan.get('coach_rule')}. Chapters: {[c['title'] for c in plan['chapters']]}")


def package(plan, trends, playbook=""):
    """Title/thumbnail pairs (packaging) then SEO (final title, description, tags, translations)."""
    arms = plan["arms"]; summ = _summary(plan); scout_ = trends.get("scout") or {}
    hard = plan["hard"]
    default_title = {"gym": f"{plan['sources'].get('topic_name', 'Chess tactics')} | Calculation Gym #{plan['episode']}",
                     "streak": f"10 Chess Puzzles From 800 to 2400: How Far Can You Go?",
                     "legendary": f"{plan['sources'].get('game_name', 'A legendary game')}: Could You Find The Moves?",
                     "trending": "The Best Chess Tactics Of This Week"}[plan["format"]]
    pk = AG.ask("packaging", f"""Create 3 title + thumbnail pairs for this video.
VIDEO: {summ}
Title style to test: {arms.get('title_style')}. Thumbnail style to test: {arms.get('thumb_style')} (board_text = big words
next to the board; big_number = a huge number; question = big question mark and the board).
Trend angles: {scout_.get('angles')}
The thumbnail shows the critical position WITHOUT the answer. Titles max 60 characters, thumbnail text max 4 words and
different from the title. 'badge' = optional 1-2 word tag (e.g. 'RATING 2100', 'GM MISSED').
Return JSON: {{"pairs": [{{"title": str, "thumb_text": str, "badge": str|null, "number": str|null, "why": str}}]}}""", 0.9, playbook) or {}
    pairs = [p for p in (pk.get("pairs") or []) if isinstance(p, dict) and p.get("title") and p.get("thumb_text")]
    if not pairs:
        pairs = [{"title": default_title, "thumb_text": {"streak": "CAN YOU REACH 10?", "legendary": "FIND THE SHOT",
                                                         "trending": "GM MISSED THIS", "gym": "SPOT IT?"}[plan["format"]],
                  "badge": None, "number": "10 PUZZLES" if plan["format"] == "streak" else None},
                 {"title": default_title, "thumb_text": "ONE MOVE WINS", "badge": None, "number": None}]
    seo = AG.ask("seo", f"""Optimise this video for YouTube search and suggested videos.
VIDEO: {summ}
CANDIDATE TITLES (from the thumbnail designer, keep the click appeal): {[p['title'] for p in pairs]}
SEARCH PHRASES PEOPLE USE NOW: {scout_.get('phrases') or trends.get('suggest')}
Write: final title (max 60 chars, main keyword early, may lightly edit the best candidate), description_intro (2-3
sentences, keyword in the first sentence, natural, says what the viewer will learn), bullet list 'you_will_learn' (3-4
bullets), tags (15-25, mix broad + specific, total under 450 characters), 3 hashtags, and translations of the final
title and description_intro for: {LANGS}.
Return JSON: {{"title": str, "title_index": number, "description_intro": str, "you_will_learn": [str], "tags": [str],
"hashtags": [str], "localizations": {{"<lang code>": {{"title": str, "description": str}}}}}}""", 0.5, playbook) or {}
    idx = seo.get("title_index") if isinstance(seo.get("title_index"), int) and 0 <= seo.get("title_index") < len(pairs) else 0
    main = pairs[idx]; alt = pairs[(idx + 1) % len(pairs)]
    title = (seo.get("title") or main["title"]).strip()[:95]
    tags, total = [], 0
    for t in (seo.get("tags") or ["chess", "chess tactics", "chess puzzles", "chess calculation", "StreakChess"]):
        t = re.sub(r"[<>,]", "", str(t)).strip()
        if t and total + len(t) + 2 < 480:
            tags.append(t); total += len(t) + 2
    plan["title"], plan["alt_title"] = title, alt["title"][:95]
    plan["seo"] = {"intro": seo.get("description_intro") or "", "learn": seo.get("you_will_learn") or [],
                   "tags": tags, "hashtags": [h if h.startswith("#") else "#" + h for h in (seo.get("hashtags") or
                                                                                             ["chess", "chesstactics", "chesspuzzle"])][:3],
                   "localizations": {k: v for k, v in (seo.get("localizations") or {}).items()
                                     if k in LANGS and isinstance(v, dict) and v.get("title")}}
    styles = ["board_text", "question", "big_number"]
    st = arms.get("thumb_style", "board_text")
    plan["thumb"] = {"text": main["thumb_text"][:30], "alt_text": alt["thumb_text"][:30], "fen": hard["fen"],
                     "flip": hard.get("flip"), "style": st, "alt_style": styles[(styles.index(st) + 1) % 3] if st in styles else "question",
                     "badge": main.get("badge") or (f"RATING {hard['rating']}" if hard.get("rating") else None),
                     "number": main.get("number") or ("10 PUZZLES" if plan["format"] == "streak" else None)}
    return plan


def description(plan, chapters, fmt_ts):
    s = plan.get("seo") or {}
    out = [s.get("intro", "").strip(), ""]
    if s.get("learn"):
        out += ["In this video:"] + [f"• {x}" for x in s["learn"]] + [""]
    out += [f"🔥 Keep your calculation streak alive (free): https://{APP_URL}/?utm_source=youtube&utm_medium=video", ""]
    out += ["Chapters:"] + [f"{fmt_ts(t)} {name}" for t, name in chapters] + [""]
    if plan.get("coach_rule"):
        out += [f"Coach's rule: {plan['coach_rule']}", ""]
    if plan["format"] in ("gym", "streak"):
        out.append("Puzzles from the Lichess open puzzle database (CC0).")
    if plan["format"] == "trending":
        out.append("Games from this week's official broadcasts on lichess.org.")
    out += ["", " ".join(s.get("hashtags") or [])]
    return "\n".join(out).strip()


def translate_captions(cues, playbook=""):
    """Caption Editor: translate the English cues (notation unchanged) -> {lang: [text per cue]}."""
    texts = [t for _, _, t in cues]
    out = {}
    for code, name in LANGS.items():
        res = AG.ask("captions", f"""Translate these subtitle cues into natural {name} for chess players. Keep chess
notation EXACTLY as written (Nxf7+, O-O, 17...Be6!!), keep the same number of cues and order, keep each cue short.
CUES: {json.dumps(texts, ensure_ascii=False)}
Return JSON: {{"cues": [str, ...]}}""", 0.3, playbook) or {}
        tr = res.get("cues")
        if isinstance(tr, list) and len(tr) == len(texts) and all(isinstance(x, str) for x in tr):
            out[code] = tr
        else:
            print(f"captions {code}: skipped (bad translation)", flush=True)
    return out
