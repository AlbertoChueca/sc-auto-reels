"""One place that says what StreakChess IS, so every reel, caption and comment says the same clear thing.

The old captions said "turns calculation practice into a daily game" - a stranger still did not know it was an app.
Every line here describes something that is really in the app (see assets/app/tours.json); nothing here is a result
claim, a testimonial or a price.
"""
import random

SERIES = {            # the three shows of the channel (named the same way everywhere)
    "puzzle": "Daily Calculation",
    "science": "Chess Science",
    "tour": "Inside StreakChess",
}
WHAT = "StreakChess is a chess training app: daily puzzles at your level, a streak to keep, and feedback on every move."
CTA = "Free to start → streakchess.com (link in bio)"
TAGLINE = "THE DAILY CHESS TRAINING APP"

# The bridge from a puzzle reel to the product: what the viewer gets if they liked THIS reel.
BRIDGES = [
    "Liked this one? The app builds you a set of 12 puzzles every day, aimed at your weakest theme.",
    "In the app every puzzle is matched to your rating, and you see the idea you missed when you get one wrong.",
    "The app rates you in three paces: 30 seconds, 3 minutes and 10 minutes. Which one is your weak one?",
    "Solve 3 puzzles a day in the app and your streak stays alive. That is the whole habit.",
    "Every puzzle you miss in the app is saved, so you can replay it until the pattern sticks.",
    "Want to race? In the app you can send 5 puzzles to a friend and see who solves them better.",
    "There is a Weekly Quest in the app: 9 puzzles, one attempt each, and a Boss Fight at the end.",
    "Got 3 minutes? Puzzle Blitz in the app: rising difficulty, three strikes and you are out.",
]
# Our own first comment under each reel (after the question): a concrete reason to open the app today.
FIRST_COMMENTS = [
    "Today's set is waiting in the app: 12 puzzles at your level. Free to start: streakchess.com ♟️",
    "Want puzzles matched to YOUR rating? That's what the app does. Free to start: streakchess.com 🔥",
    "3 puzzles a day keep your streak alive. Start yours free: streakchess.com (link in bio)",
    "Missed it? In the app Vektor shows you the idea you missed. Free to start: streakchess.com",
    "Think you'd beat a friend at this? Send them a 5-puzzle duel in the app: streakchess.com ⚔️",
]


def product_block(seed=None, bridge=True):
    """The caption block every reel ends with (before the hashtags)."""
    rng = random.Random(seed)
    lines = ["📱 " + WHAT]
    if bridge:
        lines.append(rng.choice(BRIDGES))
    lines.append(CTA)
    return "\n".join(lines)


def first_comment(question, seed=None):
    return f"{question} {random.Random(seed).choice(FIRST_COMMENTS)}"


def explainer_hook(kind, topic, alts=(), seed=None):
    """Fresh first lines for reels with no puzzle (science, app tour): never 'comment A, B, C or D'."""
    rng = random.Random(seed)
    pool = list(alts)
    if kind == "tour":
        pool += [f"Inside StreakChess: {topic.lower()}", f"{topic}, shown in the real app 📱", f"App tour: {topic.lower()}",
                 f"What the app actually does: {topic.lower()}"]
    else:
        pool += [f"Chess science: {topic.lower()} 🧠", f"What the research says about {topic.lower()}", f"The study behind this: {topic.lower()}"]
    rng.shuffle(pool)
    return pool
