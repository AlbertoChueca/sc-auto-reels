"""The writers' room: 5 specialist agents that each polish one part of every reel and keep their own notebook of
lessons, rewritten every day from real Instagram results and what the audience says in the comments.

  1. hook       - Hook Specialist: the first 2 seconds (on-screen hook, first spoken line, caption first line).
  2. story      - Story Editor: arc, emotion, continuity of Vektor's journey, clear link to the puzzle.
  3. visual     - Visual Director: image prompts before drawing, image check after, design of the final frames.
  4. growth     - Growth Marketer: caption, comment prompt, follow/share lines, hashtags -> reach, follows, shares,
                  and chess players who end up trying StreakChess.
  5. community  - Community Analyst: reads the comments every day (no usernames stored) and tells the others what
                  the audience loves, asks, gets wrong, finds too easy/hard.

Notebooks live in agents/<name>.md (committed to the repo, readable on GitHub). They are short (<= ~150 words),
rewritten - not appended - so they stay focused. Every agent call is optional: on any error the reel continues.
"""
import datetime, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
NB_DIR = os.path.join(HERE, "agents")
STAMP = os.path.join(NB_DIR, "last_update.txt")

ROLES = {
    "hook": "HOOK SPECIALIST. You own the first 2 seconds: the big on-screen hook text, the first spoken sentence and "
            "the first line of the caption. Your only goal is that chess players of every age (kids, teens, adults) and chess parents stop scrolling and keep watching.",
    "story": "STORY EDITOR. You own the storytelling: a clear mini arc, emotion, humour, continuity of Vektor's journey "
             "to become World Champion, and a natural reason why today's chess position matters.",
    "visual": "VISUAL DIRECTOR. You own image quality: framing, composition, lighting, colour, consistency of Vektor "
              "and the recurring characters, readability on a phone, premium animated-film look.",
    "growth": "GROWTH MARKETER. You own conversion and organic growth: the caption, the comment prompt, the follow and "
              "share lines and hashtags, so that more chess players comment, share, follow and try StreakChess.",
    "community": "COMMUNITY ANALYST. You read what the audience says in the comments and turn it into concrete "
                 "insights for the team (what they love, ask, get wrong, find too easy or too hard, ideas they suggest).",
}
NAMES = list(ROLES)


def _ask(prompt, temperature=0.6):
    import reviewer
    return reviewer._ask([{"text": prompt}], temperature)


def notebook(name):
    try:
        return open(os.path.join(NB_DIR, f"{name}.md")).read().strip()[:1500]
    except Exception:
        return ""


def _brief(name):
    nb, com = notebook(name), notebook("community")
    out = f"You are the {ROLES[name]}"
    if nb:
        out += f"\nYOUR NOTEBOOK (lessons from our real results - follow them):\n{nb}"
    if name != "community" and com:
        out += f"\nAUDIENCE INSIGHTS from the Community Analyst:\n{com}"
    return out


def _words(v, n):
    v = re.sub(r"\s+", " ", str(v or "")).strip()
    return v if 1 <= len(v.split()) <= n else None


def _log(kind, data):
    try:
        import reviewer
        reviewer._log(kind, data)
    except Exception:
        pass


# ------------------------------------------------------------------ per-reel passes
def hook_pass(story):
    """Hook Specialist: sharpen screen_hook, the first spoken sentence and caption_hook."""
    try:
        sc = story["scenes"]
        res = _ask(f"""{_brief('hook')}

Today's episode script (JSON): {json.dumps(story, ensure_ascii=False)}
Improve ONLY: screen_hook (max 6 words, no emoji, curiosity gap), the narration of scene 1 (max 12 words, spoken,
numbers as words, same story facts) and caption_hook (max 10 words, max one emoji). Keep what is already great.
Return JSON: {{"screen_hook": str, "scene1_narration": str, "caption_hook": str, "why": str}}""", 0.7)
        changed = {}
        if _words(res.get("screen_hook"), 6) and "#" not in res["screen_hook"]:
            changed["screen_hook"] = story["screen_hook"] = re.sub(r"[^\w\s'?!,.-]", "", res["screen_hook"]).strip()
        n1 = _words(res.get("scene1_narration"), 12)
        if n1 and not re.search(r"\b[a-h][1-8]\b", n1):
            changed["scene1"] = sc[0]["narration"] = n1
        if _words(res.get("caption_hook"), 10) and "#" not in res["caption_hook"]:
            changed["caption_hook"] = story["caption_hook"] = res["caption_hook"].strip()
        _log("agent_hook", {"changes": changed, "why": res.get("why")})
        print(f"agent hook: {changed.get('screen_hook') or story.get('screen_hook')!r}", flush=True)
    except Exception as e:
        print("agent hook skipped:", str(e)[:150], flush=True)
    return story


def visual_prompts_pass(story, character):
    """Visual Director (before drawing): rewrite each image prompt into a strong, consistent cinematic shot."""
    try:
        sc = story["scenes"]
        res = _ask(f"""{_brief('visual')}
Character sheet: {character}
Rewrite these 4 image prompts so each is ONE striking vertical 9:16 frame of a premium animated film: clear subject,
camera framing, lighting, colour mood, depth, expressive pose; Vektor always "the knight mascot from the reference
images, standing upright" (never lying down, tipped over or fallen), same look in every frame; other characters exactly
as in this cast sheet:
{__import__('series').cast_sheet()}
Vary the shots (wide / medium / close-up / dramatic) and make every image clearly different from the others; keep the main subject in the middle 60% of the frame (phone UI covers edges);
no text, letters, numbers or logos. Keep each scene's story meaning.
Prompts: {json.dumps([s['image_prompt'] for s in sc], ensure_ascii=False)}
Return JSON: {{"prompts": [str, str, str, str]}}""", 0.5)
        ps = res.get("prompts") or []
        if len(ps) == len(sc) and all(isinstance(p, str) and 8 <= len(p.split()) <= 120 for p in ps):
            for s_, p in zip(sc, ps):
                s_["image_prompt"] = p
            print("agent visual: image prompts upgraded", flush=True)
    except Exception as e:
        print("agent visual skipped:", str(e)[:150], flush=True)
    return story


def growth_lines(story, mode):
    """Growth Marketer (before render): follow + share lines shown on the end card."""
    try:
        res = _ask(f"""{_brief('growth')}
Episode: "{story.get('title')}" ({'friend challenge' if mode == 'tagfriend' else 'normal puzzle'}).
Write the end-card lines: follow_line (max 6 words, makes people follow for Vektor's next day) and share_line
(max 7 words, an ACTIVE challenge that starts with a verb like Challenge, Dare or Tag - never a passive
"send this"). Return JSON: {{"follow_line": str, "share_line": str}}""", 0.7)
        out = {}
        if _words(res.get("follow_line"), 6): out["follow_line"] = re.sub(r"[^\w\s'?!,.-]", "", res["follow_line"]).strip()
        if _words(res.get("share_line"), 7): out["share_line"] = re.sub(r"[^\w\s'?!,.-]", "", res["share_line"]).strip()
        return out
    except Exception as e:
        print("agent growth (lines) skipped:", str(e)[:150], flush=True)
        return {}


def growth_caption(caption, story, review):
    """Growth Marketer (after the QA review): final caption. Keeps the StreakChess line and 3-5 chess hashtags."""
    try:
        tags = re.findall(r"#\w+", caption)
        res = _ask(f"""{_brief('growth')}
Current caption:
{caption}

QA notes on the finished reel: {json.dumps(review, ensure_ascii=False)[:600]}
Rewrite the caption for maximum comments, shares, saves and follows from chess players and chess parents.
Rules: English; first line max 12 words (hook, max one emoji); a line inviting people to comment their move;
a line inviting to share with a chess friend; keep one line for every chess player (kids, adults and chess parents alike, never addressed
to parents only) that StreakChess is free with the founder offer and link in bio; end with 3-5 chess hashtags (you may swap them). Max 600 characters. Kid-safe, no fake claims.
Return JSON: {{"caption": str, "why": str}}""", 0.6)
        cap = (res.get("caption") or "").strip()
        n_tags = len(re.findall(r"#\w+", cap))
        if 80 <= len(cap) <= 800 and 3 <= n_tags <= 5 and "bio" in cap.lower() and "streakchess" in cap.lower():
            _log("agent_growth", {"why": res.get("why")})
            print("agent growth: caption rewritten", flush=True)
            return cap
        print("agent growth: caption kept (rewrite did not meet the rules)", flush=True)
    except Exception as e:
        print("agent growth skipped:", str(e)[:150], flush=True)
    return caption


# ------------------------------------------------------------------ daily learning loop
def daily_learning(force=False):
    """Once a day: every agent rewrites its notebook from real results + comments. Returns a status line."""
    os.makedirs(NB_DIR, exist_ok=True)
    today = str(datetime.date.today())
    if not force and os.path.exists(STAMP) and open(STAMP).read().strip() == today:
        return "agents: notebooks already updated today"
    try:
        perf = json.load(open(os.path.join(HERE, "performance.json")))
    except Exception:
        perf = {}
    rows = [r for r in perf.values() if r.get("story") or r.get("hook")]
    if len(rows) < 3:
        return "agents: waiting for results (need 3+ measured reels)"
    import strategy
    rows.sort(key=lambda r: -(strategy.reward(r) or 0))
    table = "\n".join(
        f"- score {strategy.reward(r) or 0:.2f} | views {r.get('views')} | likes {r.get('likes') or r.get('like_count')} | "
        f"comments {r.get('comments') or r.get('comments_count')} | shares {r.get('shares')} | saves {r.get('saved')} | "
        f"watch {r.get('ig_reels_avg_watch_time')} ms | \"{r.get('story')}\" | hook: {r.get('hook')} | "
        + ", ".join(f"{k}={strategy.short(v)}" for k, v in (r.get("arms") or {}).items())
        for r in rows[:30])
    comments = []
    try:
        import insights
        comments = insights.recent_comments()
    except Exception as e:
        print("agents: comments unavailable:", str(e)[:120], flush=True)
    com_txt = "\n".join(f"- [{c['story'] or 'reel'}] {c['text'][:160]}" for c in comments[:150]) or "(no comments yet)"
    old = {n: notebook(n) for n in NAMES}
    try:
        res = _ask(f"""You coordinate a writers' room of 5 specialist agents for "Vektor", a daily animated chess series
for chess players of every age and chess parents (StreakChess app). Roles:
{json.dumps(ROLES, indent=1)}

REAL INSTAGRAM RESULTS (best first; score = views + weighted shares/saves/comments + watch time):
{table}

RECENT AUDIENCE COMMENTS (anonymous):
{com_txt}

CURRENT NOTEBOOKS:
{json.dumps(old, ensure_ascii=False, indent=1)}

Rewrite each agent's notebook for tomorrow. Each notebook: max 120 words, bullet points, concrete and specific to
OUR data: "Keep doing", "Stop doing", "Try next". Only keep old lessons the data still supports. The community
notebook summarises what the audience says (no usernames, no personal data). Be honest when data is too thin.
Return JSON: {{"hook": str, "story": str, "visual": str, "growth": str, "community": str}}""", 0.4)
    except Exception as e:
        return f"agents: learning skipped ({str(e)[:120]})"
    n = 0
    for name in NAMES:
        txt = (res.get(name) or "").strip()
        if 20 <= len(txt) <= 1500:
            open(os.path.join(NB_DIR, f"{name}.md"), "w").write(f"# {name.title()} notebook ({today})\n\n{txt}\n")
            n += 1
    open(STAMP, "w").write(today)
    return f"agents: {n}/5 notebooks updated from {len(rows)} reels and {len(comments)} comments"
