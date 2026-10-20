"""One-off consultation: every agent proposes how to raise the reels' quality scores, then a showrunner
merges it into one prioritised plan. Output: agents/consultation.md (+ consultation.json).

python consult_agents.py
"""
import collections, datetime, json, os
import agents

HERE = os.path.dirname(os.path.abspath(__file__))


def recent_reviews(n=40):
    rows = []
    for line in open(os.path.join(HERE, "review_log.jsonl")):
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("kind") in ("video", "design", "script", "images"):
            rows.append(d)
    return rows[-n:]


def summary(rows):
    by = collections.defaultdict(list)
    for r in rows:
        if isinstance(r.get("overall"), (int, float)):
            by[r["kind"]].append(r["overall"])
    avg = {k: round(sum(v) / len(v), 2) for k, v in by.items()}
    sub = collections.defaultdict(list)
    for r in rows:
        for k, v in (r.get("scores") or {}).items():
            if isinstance(v, (int, float)):
                sub[f"{r['kind']}.{k}"].append(v)
    weakest = sorted(((round(sum(v) / len(v), 2), k) for k, v in sub.items()), key=lambda x: x[0])[:12]
    issues = [f"[{r['kind']} {r.get('overall')}] " + "; ".join(r.get("issues") or [])[:500] for r in rows[-25:]]
    return avg, weakest, issues


EXTRA_ROLES = {
    "producer": "SENIOR PRODUCER / VIDEO QA REVIEWER. You watch every finished reel and score hook, story clarity, "
                "pacing, audio, subtitles, voice, board and moves, visuals, call to action and engagement.",
    "art_director": "ART DIRECTOR. You score the design: scroll-stopping hook, copy, typography and readability, "
                    "safe-zone layout, visual polish, board clarity, end card and shareability.",
}

CONTEXT = """PRODUCT: StreakChess (free chess calculation app). Instagram/TikTok/YouTube Shorts reels, fully automated.
Formats: (1) 'story' = an AI-illustrated mini episode of Vektor (a flame-maned knight) + a short animated calculation
lesson on the real puzzle position (checks, captures, threats, candidates) + the puzzle with a countdown; the answer is
NOT shown, viewers comment it and the bot posts it the next day. (2) 'tip' = a calculation masterclass + the puzzle.
Audience: chess players of every age (kids, teens, adults) and chess parents. New premium look since today: night blue
+ champagne gold, Inter typography, slow fades, no shakes or flashes, calmer music. Target length <= 55 s.
Pipeline facts: voice = Gemini TTS (sometimes reads stage directions aloud; a filter was just added), subtitles from
speech recognition, images from Gemini, Python/PIL rendering, reviewer agents can re-render with tweaked copy/layout."""


def ask_role(name, desc, avg, weakest, issues):
    brief = agents._brief(name) if name in agents.ROLES else f"You are the {desc}"
    return agents._ask(f"""{brief}

{CONTEXT}

REAL QA DATA FROM THE LAST REELS
Average overall score by review kind: {json.dumps(avg)}
Weakest sub-scores (avg, area): {json.dumps(weakest)}
Recent issues found by QA:
{chr(10).join('- ' + i for i in issues)}

The owner wants clearly higher quality and higher review scores. From YOUR area of responsibility, propose the 5
changes with the biggest impact. Be concrete and implementable in the automated pipeline (what exactly to change in
prompts, timings, layout, audio, copy or checks), not generic advice. Rank by impact. English.
Return JSON: {{"diagnosis": str, "proposals": [{{"title": str, "change": str, "why": str, "impact": "high|medium|low",
"effort": "low|medium|high"}}]}}""", 0.5)


def main():
    rows = recent_reviews()
    avg, weakest, issues = summary(rows)
    answers = {}
    for name in agents.NAMES + list(EXTRA_ROLES):
        desc = agents.ROLES.get(name) or EXTRA_ROLES[name]
        try:
            answers[name] = ask_role(name, desc, avg, weakest, issues)
            print(f"{name}: {len(answers[name].get('proposals', []))} proposals", flush=True)
        except Exception as e:
            answers[name] = {"error": str(e)[:300]}; print(name, "failed:", str(e)[:200], flush=True)
    plan = agents._ask(f"""You are the SHOWRUNNER of the StreakChess reels team. {CONTEXT}
Scores: {json.dumps(avg)}; weakest areas: {json.dumps(weakest)}.
Your specialists proposed these changes:
{json.dumps(answers, ensure_ascii=False)[:14000]}

Merge duplicates, resolve conflicts and produce ONE prioritised plan of the 8 changes that will raise quality the
most, ordered by impact/effort. For each: which specialist(s) proposed it, the exact change, expected effect.
Return JSON: {{"summary": str, "plan": [{{"rank": int, "title": str, "owners": [str], "change": str,
"expected_effect": str, "effort": "low|medium|high"}}]}}""", 0.4)
    os.makedirs(os.path.join(HERE, "agents"), exist_ok=True)
    json.dump({"date": str(datetime.date.today()), "scores": avg, "weakest": weakest, "answers": answers, "plan": plan},
              open(os.path.join(HERE, "agents", "consultation.json"), "w"), indent=1, ensure_ascii=False)
    md = [f"# Agents consultation - {datetime.date.today()}", "",
          f"Average scores: {avg}", "", "## Showrunner plan", "", plan.get("summary", ""), ""]
    for p in plan.get("plan", []):
        md += [f"{p.get('rank')}. **{p.get('title')}** ({', '.join(p.get('owners', []))}, effort {p.get('effort')})",
               f"   - {p.get('change')}", f"   - Effect: {p.get('expected_effect')}"]
    md += ["", "## Each agent", ""]
    for name, a in answers.items():
        md += [f"### {name}", "", a.get("diagnosis", a.get("error", "")), ""]
        for p in a.get("proposals", []):
            md += [f"- **{p.get('title')}** [{p.get('impact')}/{p.get('effort')}]: {p.get('change')} _Why: {p.get('why')}_"]
        md += [""]
    open(os.path.join(HERE, "agents", "consultation.md"), "w").write("\n".join(md))
    print("\n".join(md)[:3000])


if __name__ == "__main__":
    main()
