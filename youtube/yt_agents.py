"""The StreakChess YouTube team: 10 specialist agents. Each one owns one job and keeps its own notebook
(youtube/agents/<name>.md) that gets rewritten after every video from three sources:
  - what the other agents had to fix in its work (the 'inbox'),
  - real YouTube results (CTR, % watched, subscribers, comments) once videos are a few days old,
  - the Analyst's weekly playbook.
So the team gets better with every episode, and you can read on GitHub what each agent has learned.

  1. trend_scout  Trend Scout        what chess fans care about this week (news, live tournaments, searches)
  2. showrunner   Showrunner         episode concept, series continuity, the course path, final quality gate
  3. writer       Head Writer        the full script
  4. coach        Chess Coach        teaching value + chess truth (every move checked against Stockfish/data)
  5. comedian     Voice & Humor Ed.  makes it sound like a real, funny chess YouTuber; removes anything that smells of AI
  6. director     Visual Director    on-screen emphasis, highlighted squares, pauses, pacing
  7. captions     Caption Editor     clean subtitles and translations
  8. seo          SEO Specialist     title keywords, description, tags, chapters, translations of title/description
  9. packaging    Thumbnail Designer title + thumbnail text pairs (click-worthy, honest)
 10. analyst      Channel Analyst    reads results/comments, updates every notebook and the playbook
"""
import datetime, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
NB = os.path.join(HERE, "agents")
INBOX = os.path.join(NB, "inbox.jsonl")
MOCK = bool(os.environ.get("YT_MOCK"))
APP_URL = os.environ.get("APP_URL", "streakchess.com")

CHANNEL = f"""CHANNEL BIBLE - StreakChess on YouTube
- StreakChess ({APP_URL}) is a free app that trains chess calculation every day, like Duolingo for tactics: keep your
  daily streak alive. The channel is where players come to get sharper at calculation and have fun doing it.
- Audience: club and online players (about 800-2000 rating), teens and adults, mostly US/English speaking, who want to
  stop missing tactics and win more games. Smart, busy, allergic to fluff.
- Host persona: "the StreakChess coach" - a sharp, warm, funny chess coach with 15 years of teaching. Talks to ONE
  viewer. Confident, playful, a little cheeky, never cringe, never hype-bro. Loves a good sacrifice.
- Promise: follow the channel and your calculation improves week by week (a real course, not random clips).
- Running bits: viewers keep a "streak" score in every video; "the tempting move" (the move most players want to play
  and why it fails); "Coach's rule" (one memorable rule per video).
- Truth: never invent moves, games, quotes, statistics or news. Only use the facts given in the brief.
- Notation: write chess moves in standard algebraic notation (Nf3, Bxf7+, O-O, exd5, Qxh7#). Use move numbers only
  when talking about a real game (17...Be6!!). Squares in lowercase (f7, e4).
"""

ROLES = {
    "trend_scout": "TREND SCOUT. You find what chess fans are excited about THIS week (tournaments, viral moments, players "
                   "in the news, search trends) and turn it into angles that make a calculation video feel current.",
    "showrunner": "SHOWRUNNER. You decide the episode concept so every video is a fun, original episode of a series and a "
                  "step in the viewer's course. You protect the brand, continuity and variety, and you give the final "
                  "quality verdict.",
    "writer": "HEAD WRITER. You write the full spoken script: an irresistible cold open, open loops, payoffs, jokes that "
              "land, clear teaching, and a reason to keep watching every 60-90 seconds.",
    "coach": "CHESS COACH (15 years teaching). You guarantee the chess is TRUE and the viewer really LEARNS: the right "
             "explanation of why moves work, the calculation method, the tempting mistake and its refutation, hints that "
             "help without spoiling.",
    "comedian": "VOICE & HUMOR EDITOR. You make the script sound like a real, funny chess YouTuber talking, not like an AI: "
                "natural rhythm, contractions, specific images, light self-aware jokes, zero corporate or AI phrasing.",
    "director": "VISUAL DIRECTOR. You decide what the viewer sees with each line: which squares glow, which short word pops "
                "on screen, where a dramatic pause goes. Clean, purposeful, never cluttered.",
    "captions": "CAPTION EDITOR. You make subtitles that read perfectly and translate them naturally for other "
                "languages, keeping chess notation exactly as written.",
    "seo": "SEO SPECIALIST for YouTube. You make the video findable: keyword-first titles, a description that ranks and "
           "converts, tags, chapter titles, and translated titles/descriptions for other languages.",
    "packaging": "THUMBNAIL & TITLE DESIGNER. You create title + thumbnail-text pairs that make chess players click "
                 "(curiosity, stakes, challenge) while staying 100% honest about the content.",
    "analyst": "CHANNEL ANALYST. You read real results and audience comments and turn them into precise lessons for each "
               "team member.",
}
NAMES = list(ROLES)

# Notebooks start with expert craft notes; the Analyst rewrites them from real feedback after every video.
SEED = {
    "trend_scout": "- Prefer stories from the last 7 days with a chess moment we can show (a game, a blunder, a record).\n"
                   "- One current reference in the cold open is enough; the video must stay evergreen after that.",
    "showrunner": "- Every episode needs one clear promise, one fun mechanic and one Coach's rule.\n"
                  "- Callback to the previous episode in one line; tease the next one at the end.\n"
                  "- Vary the energy: game show, detective story, history drama, live-news breakdown.",
    "writer": "- Cold open: start mid-action on the hardest position; first sentence under 12 words; no greetings.\n"
              "- Open a loop in the first 20 s and close it late. Re-hook before each new section.\n"
              "- Short sentences. Specific > generic ('your knight is begging to jump to d5').\n"
              "- Before every timer: tell the viewer exactly what to look for without giving it away.\n"
              "- After every reveal: why it works, the pattern, the tempting move that fails.",
    "coach": "- Teach the method: checks, captures, threats - then the opponent's best reply.\n"
             "- Every explanation names the key square or piece and the reason (overloaded, pinned, back rank...).\n"
             "- Hints point to an idea, never to the move.",
    "comedian": "- Banned AI phrases: dive in, delve, unlock, elevate, game-changer, journey, tapestry, buckle up, "
                "in today's video, without further ado, let's get started, crucial, master the art, level up.\n"
                "- Use contractions, rhetorical questions, small exaggerations, self-aware jokes about blundering.\n"
                "- One joke per minute max; jokes never slow down the chess.",
    "director": "- Light up the 1-3 squares that matter; pop at most 3 words on screen per line.\n"
                "- Put a short pause after big reveals so the move can land.",
    "captions": "- Max 2 lines, break at natural phrases, keep notation exact (Nxf7+, O-O).",
    "seo": "- Main keyword in the first 40 characters of the title and the first sentence of the description.\n"
           "- Use the exact phrases people type (from the YouTube autocomplete list).\n"
           "- 3 hashtags max; tags mix broad (chess tactics) and specific (knight fork puzzle).",
    "packaging": "- Thumbnail text max 4 words, different from the title (they work together).\n"
                 "- Curiosity + stakes: 'GM MISSED THIS', '99% PLAY THE WRONG MOVE'. Never promise what the video lacks.",
    "analyst": "- Judge by CTR (packaging), average % viewed (script/pacing) and subscribers per view (value).",
}


def notebook(name):
    try:
        return open(os.path.join(NB, f"{name}.md")).read().strip()[-2200:]
    except Exception:
        return SEED.get(name, "")


def brief(name, playbook=""):
    out = f"{CHANNEL}\nYou are the team's {ROLES[name]}\nYOUR NOTEBOOK (lessons learned so far - follow them):\n{notebook(name)}\n"
    if playbook:
        out += f"\nCHANNEL PLAYBOOK FROM REAL RESULTS:\n{playbook}\n"
    return out


def ask(name, task, temperature=0.7, playbook=""):
    """Run one agent. Returns parsed JSON, or None in mock mode / on failure (callers always have a fallback)."""
    if MOCK:
        return None
    import yt_gemini as G
    for attempt in range(2):
        try:
            out = G.ask_json(brief(name, playbook) + "\n\nTASK:\n" + task, temperature)
            if isinstance(out, dict):
                print(f"agent {name}: ok", flush=True)
                return out
        except Exception as e:
            print(f"agent {name} failed (try {attempt + 1}): {str(e)[:200]}", flush=True)
    return None


def note(to, text, by="system"):
    """Feedback for an agent's next notebook update (e.g. the Coach telling the Writer what it had to fix)."""
    if not text or to not in ROLES:
        return
    os.makedirs(NB, exist_ok=True)
    with open(INBOX, "a") as f:
        f.write(json.dumps({"date": datetime.date.today().isoformat(), "to": to, "by": by, "note": str(text)[:400]}) + "\n")


def _inbox():
    try:
        return [json.loads(l) for l in open(INBOX) if l.strip()]
    except Exception:
        return []


def evolve(results_table="", comments=(), playbook=""):
    """Analyst rewrites every notebook (max ~150 words each) from the inbox + real results + comments."""
    os.makedirs(NB, exist_ok=True)
    for n in NAMES:                                       # make sure every notebook exists (seeded)
        p = os.path.join(NB, f"{n}.md")
        if not os.path.exists(p):
            open(p, "w").write(f"# {ROLES[n].split('.')[0].title()} - notebook\n\n{SEED[n]}\n")
    inbox = _inbox()
    if MOCK or (not inbox and not results_table and not comments):
        return "analyst: nothing new to learn"
    notes = {}
    for x in inbox[-120:]:
        notes.setdefault(x["to"], []).append(f"({x['by']}) {x['note']}")
    current = {n: notebook(n) for n in NAMES}
    res = ask("analyst", f"""Update the notebook of every team member.
CURRENT NOTEBOOKS: {json.dumps(current, ensure_ascii=False)}
FEEDBACK FROM THE TEAM SINCE LAST UPDATE (what others had to fix): {json.dumps(notes, ensure_ascii=False)}
REAL YOUTUBE RESULTS (best first): {results_table or '(no results yet - videos are too new)'}
AUDIENCE COMMENTS (anonymous): {json.dumps(list(comments)[:60], ensure_ascii=False)}

Rewrite each notebook as max 8 bullet points (max ~150 words): keep what still holds, add concrete new lessons,
remove what results contradict. Be specific and actionable (e.g. 'cold opens that start with a GM blunder got 2x
retention'). Return JSON: {{"notebooks": {{"<name>": "bullets as one string"}}, "summary": "what changed, 2 sentences"}}""", 0.4, playbook)
    if not res or not isinstance(res.get("notebooks"), dict):
        return "analyst: update failed, notebooks kept"
    for n, txt in res["notebooks"].items():
        if n in ROLES and isinstance(txt, str) and 20 < len(txt) < 3000:
            open(os.path.join(NB, f"{n}.md"), "w").write(
                f"# {ROLES[n].split('.')[0].title()} - notebook\n_Updated {datetime.date.today()}_\n\n{txt.strip()}\n")
    open(INBOX, "w").close()
    return f"analyst: notebooks updated - {res.get('summary', '')}"


BANNED = ["dive in", "dive into", "delve", "unlock", "elevate", "game-changer", "game changer", "journey", "tapestry",
          "buckle up", "in today's video", "without further ado", "let's get started", "crucial", "master the art",
          "level up your", "welcome back", "hey guys", "embark", "testament to", "navigate the", "realm",
          "it's important to note", "in conclusion", "whether you're a", "ever wondered"]


def ai_phrases(text):
    t = text.lower()
    return [b for b in BANNED if b in t]
