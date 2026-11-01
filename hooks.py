"""Hook freshness: the first line of every caption (and the spoken/on-screen hook) must not repeat the opening of
recent reels. Real results showed 60 reels in a row starting "Can you help Vektor ..." - the audience sees the same
line every day and stops reading. This module gives the agents the recent hooks to avoid, checks their output and
has strong, concrete fallbacks so a reel never goes out with a stale hook.
"""
import json, os, random, re

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "log.jsonl")
RECENT_N = 12


def _norm(t):
    return re.sub(r"[^a-z0-9 ]", "", (t or "").lower()).split()


def recent(n=RECENT_N):
    """The first caption lines of the last n reels (from log.jsonl)."""
    out = []
    try:
        for line in open(LOG):
            try:
                h = (json.loads(line).get("hook") or "").strip()
            except Exception:
                continue
            if h:
                out.append(h)
    except Exception:
        pass
    return out[-n:]


def opening(t, k=3):
    return " ".join(_norm(t)[:k])


def is_fresh(hook, prev=None):
    """True when the hook does not share its first 3 words with a recent one and does not reuse a tired template."""
    prev = recent() if prev is None else prev
    h = _norm(hook)
    if len(h) < 2:
        return False
    op = opening(hook)
    if any(op == opening(p) for p in prev):
        return False
    tired = [p for p in prev if "can you help vektor" in " ".join(_norm(p))]
    if "can you help vektor" in " ".join(h) and len(tired) >= 1:
        return False
    if any(" ".join(_norm(p)) == " ".join(h) for p in prev):
        return False
    return True


RULES = """HOOK RULES (the first line is the whole game):
- NEVER open with the same 3 words as any recent hook listed below. Never use "Can you help Vektor" again.
- Name the CONCRETE chess idea or piece (a pinned knight, a loose rook, a back rank with no escape), not an
  abstract "secret move/tactic". Specific beats vague: our best reels named the tactic in the hook.
- Pick a DIFFERENT formula each time: a bold claim ("This knight is not a defender"), a contrarian line
  ("Stop counting material here"), a direct address ("Your opponent is bluffing"), a challenge with a number
  ("4 candidates. 1 wins. 15 seconds."), a question about the position ("Why can't the rook take?"),
  a POV ("POV: your opponent just hung a piece"), a mistake callout ("Most club players grab the queen here").
- 4-11 words, plain English, no hashtags, max one emoji, no fake statistics, no clickbait lies.
RECENT HOOKS (do not reuse their openings):
{recent}"""


def rules():
    r = recent()
    return RULES.format(recent="\n".join(f"- {h}" for h in r) or "- (none yet)")


# Concrete fallbacks, built from the lesson and the puzzle facts. Several formulas so they never look alike.
TEMPLATES = [
    "{tip_cap}. Prove it in {secs} seconds ♟️",
    "This is why strong players {idea_verb}",
    "{letters}? One of these wins on the spot",
    "Your opponent's {piece} is lying to you 👀",
    "Stop {bad_habit}. Do this instead",
    "Most club players miss this {motif}",
    "{side} to move. Only one candidate wins",
    "POV: {motif_pov}",
    "Find the {motif} before the timer hits zero ⏱️",
    "{secs} seconds, four candidates, one winner",
    "The {motif} every {level_name} player must know",
    "Why does {letter_correct_hint} win here? Calculate it",
]

MOTIF = {   # tip key -> (motif noun, POV line, bad habit, idea verb)
    "pin": ("pin", "your opponent's defender can't move", "trusting a pinned defender", "never count a pinned piece"),
    "xray": ("x-ray", "there's a hidden line through the pieces", "looking only at what's in front", "look through the pieces"),
    "fork": ("fork", "two pieces, one attacker, no defence", "attacking one target at a time", "hunt two targets at once"),
    "sac": ("sacrifice", "giving up material is the fastest win", "refusing to give up material", "calculate every sacrifice"),
    "deflect": ("deflection", "the key defender is about to be dragged away", "attacking the defended piece", "remove the key defender"),
    "overload": ("overloaded defender", "one piece is doing two jobs", "trusting a piece with two jobs", "overload the defender"),
    "loose": ("loose piece", "a piece is hanging and nobody noticed", "ignoring undefended pieces", "hunt loose pieces"),
    "count": ("attacker count", "the square is attacked more than defended", "capturing without counting", "count before they capture"),
    "king": ("weak king", "the king has no escape square", "ignoring the enemy king", "look at the king first"),
    "threat": ("hidden threat", "your opponent just set a trap", "moving before reading their threat", "ask what the opponent wants"),
    "cct": ("forcing move", "every check and capture is on the table", "calculating quiet moves first", "check checks, captures, threats"),
    "forcing": ("forcing line", "one forcing move decides the game", "calculating slowly", "calculate the forcing moves first"),
    "blunder": ("blunder check", "your move is about to lose a piece", "pressing the piece too early", "run the blunder check"),
    "candidates": ("candidate move", "four candidates, only one wins", "calculating the first move you see", "list candidates first"),
    "end": ("final position", "the win is three moves away", "stopping the calculation too early", "see the final position"),
    "visual": ("visualisation", "the pieces move in your head first", "touching the pieces to calculate", "move the pieces in their head"),
    "slow": ("sharp position", "one careful minute wins the game", "rushing in sharp positions", "slow down when it's sharp"),
    "backrank": ("back rank weakness", "the back rank is wide open", "forgetting the back rank", "check the back rank"),
    "discovered": ("discovered attack", "moving one piece unleashes another", "looking at one piece at a time", "unleash discovered attacks"),
    "trapped": ("trapped piece", "the piece has nowhere to go", "ignoring a piece with no squares", "trap pieces with no squares"),
    "removal": ("remove-the-defender tactic", "one defender holds everything together", "attacking the protected piece", "remove the defender first"),
}


def fallback(tip_key, tip_name, level_name="club", side="White", letters="A, B, C or D", secs=10, piece="knight",
             correct=None, seed=None):
    rng = random.Random(seed)
    motif, pov, bad, verb = MOTIF.get(tip_key, ("tactic", "there is a win hidden in plain sight", "guessing", "calculate"))
    prev = recent()
    pool = list(TEMPLATES); rng.shuffle(pool)
    for t in pool:
        h = t.format(tip_cap=tip_name[:1].upper() + tip_name[1:], secs=secs, letters=letters, piece=piece,
                     bad_habit=bad, motif=motif, side=side, motif_pov=pov, level_name=level_name.lower(),
                     idea_verb=verb, letter_correct_hint=(f"move {correct}" if correct else "the winner"))
        if is_fresh(h, prev):
            return h
    return f"{motif.capitalize()} alert: {side} to move, {letters}?"


def ensure(hook, tip_key="", tip_name="", **kw):
    """Return hook if it is fresh, else a fresh fallback."""
    if hook and is_fresh(hook):
        return hook.strip()
    fb = fallback(tip_key, tip_name or "today's lesson", **kw)
    print(f"hook: replaced stale/invalid hook {hook!r} -> {fb!r}", flush=True)
    return fb


if __name__ == "__main__":
    print(rules())
    print(fallback("pin", "A pinned piece is not a defender", correct="B"))
