"""Answer new comments on recent reels: a short public reply + a private DM with the StreakChess link.

Runs every hour from GitHub Actions. Uses only the official Instagram API on our own posts.
- Checks the correct first move (from log.jsonl) and congratulates people who got it.
- One DM per person per week at most (no spam), public replies are varied.
- Remembers handled comments in handled_comments.json.
Env: IG_TOKEN. Optional: BOT_DRY_RUN=true (print only).
"""
import datetime, json, os, random, re, requests
from publish_ig import GRAPH, _check, whoami

TOKEN = os.environ["IG_TOKEN"]
DRY = os.environ.get("BOT_DRY_RUN") == "true"
# BOT_SEND_DMS: "true" = DM everyone who comments (max 1/week each), "correct" (default) = DM only people who got
# the answer right (they earned it, and it is the warmest lead), "false" = public replies only.
SEND_DMS = os.environ.get("BOT_SEND_DMS", "correct").lower()
HANDLED = "handled_comments.json"
LINK = "https://streakchess.com/?utm_source=instagram&utm_medium=dm&utm_campaign=reel_comment"

PUBLIC_CORRECT = [
    "Correct! {move} is the move 🎯 Train daily for free, link in bio 🔥",
    "Spot on! {move} 💥 More puzzles like this every day, link in bio",
    "Yes! {move} wins 👏 Keep your streak going on StreakChess, link in bio",
    "Great calculation! {move} is right 🔥 Test yourself daily, link in bio",
    "Boom! {move} 🎯 You'd crush our daily streak, link in bio",
    "Sharp eyes! {move} is the one 👀 Free daily training, link in bio",
    "Nailed it! {move} ♟️ Ready for a harder one? Link in bio",
    "That's it! {move} 🔥 Build your calculation streak for free, link in bio",
    "Excellent! {move} is correct 💪 More puzzles at the link in bio",
    "Well calculated! {move} 🎯 Join the daily challenge, link in bio",
]
PUBLIC_OTHER = [
    "Thanks for playing! 🔥 The answer drops in the comments tomorrow. More puzzles daily, link in bio",
    "Nice try! The answer is coming tomorrow ♟️ Train daily for free, link in bio",
    "Love it! 🔥 Train your calculation for free, link in bio",
    "Thanks for the comment! ♟️ New puzzles every day, link in bio",
    "Great to see you here! 👀 Sharpen your calculation daily, link in bio",
    "Keep calculating! 💪 Free daily puzzles at the link in bio",
    "Appreciate it! ♟️ Want a new challenge every day? Link in bio",
    "Thanks! 🔥 Start your puzzle streak for free, link in bio",
    "Good one! 🎯 Level up your tactics daily, link in bio",
    "Thanks for joining the challenge! ♟️ More at the link in bio",
]
ANSWER_POSTS = [
    "✅ ANSWER: {sol}{why}\nDid you get it? Reply with your time ⏱️ New puzzle every day 🔥",
    "✅ The solution is {sol}{why}\nWho found it in under 10 seconds? 👀 Tomorrow's puzzle is coming!",
    "✅ Answer: {sol}{why}\nGot it right? Keep your streak going on StreakChess, link in bio 🔥",
]
PUBLIC_CORRECT_HIDDEN = [   # answer not revealed yet: confirm without spoiling it for others
    "You got it! 🎯 Don't spoil it for the others, answer drops here tomorrow 😉",
    "Correct! 🔥 Keep it secret, we reveal it tomorrow!",
    "That's right! 👏 Sharp calculation. Answer post goes up tomorrow.",
]
PUBLIC_OTHER_HIDDEN = [
    "Good try! 🤔 Check every capture and check again... answer drops here tomorrow!",
    "Interesting idea! Look for the most forcing move 👀 Answer tomorrow!",
    "Thanks for playing! ♟️ Answer coming tomorrow, keep calculating!",
    "Locked in 🔒 We reveal the answer here tomorrow. Which line did you calculate?",
    "Noted! 📝 Answer drops tomorrow. Did you check the opponent's best reply?",
    "Bold choice 👀 Come back tomorrow for the reveal!",
    "Thanks! The reveal is tomorrow. Tag a friend who'd pick something else 😉",
]
# Before the reveal NOBODY gets confirmed in public (a "correct!" under a comment gives the answer away and kills the
# guessing): correct answers get the same neutral replies, and the confirmation goes by private message.
PUBLIC_ANY_HIDDEN = PUBLIC_OTHER_HIDDEN
PUBLIC_SCIENCE = [   # explainer reels (no puzzle to answer)
    "Thanks! 🧠 The study is linked in the caption. Daily calculation training, link in bio",
    "Glad it landed! Tag the friend who needs this 👇 Train free, link in bio",
    "Science says: train the pattern daily 🔥 Free puzzles every day, link in bio",
    "Appreciate it ♟️ Source in the caption. Want a daily dose? Link in bio",
    "Good question! The full reference is in the caption 📚 Daily training at the link in bio",
]
PUBLIC_TOUR = [      # app walkthroughs: keep the conversation going and say where to try it
    "Love that answer 🔥 You can try what you just saw for free: streakchess.com (link in bio)",
    "Thanks for playing along! ♟️ The app is free to start: streakchess.com. Tell us what you think",
    "Good one 👀 Everything in the video is in the app today, free to start: link in bio",
    "Noted! 📝 Want to see it yourself? streakchess.com, free to start. Which feature should we show next?",
    "Appreciate it 🙌 Start your own streak today, it's free: streakchess.com (link in bio)",
]
PUBLIC_WHAT = [      # someone asks what this is / where to get it (any reel)
    "StreakChess is a chess training app: daily puzzles at your level and a streak to keep 🔥 Free to start at streakchess.com (link in bio)",
    "It's StreakChess, a daily chess puzzle app ♟️ It runs in your browser on phone or computer, free to start: streakchess.com",
    "This is StreakChess: short daily puzzles matched to your rating, with feedback on every move. Free to start, link in bio 🔥",
]
ASKS_WHAT = re.compile("|".join([
    r"\bwhat(?:'s| is)? (?:this|that|the|it)\b.{0,30}\b(?:app|game|site|website|platform)\b",
    r"^\W*what(?:'s| is) (?:this|streak ?chess)\W*$",
    r"\b(?:which|what) app\b", r"\bapp name\b", r"\bname of (?:the|this) (?:app|game)\b",
    r"\bwhere (?:can|do) i (?:play|get|find|try|download|train)\b",
    r"\bhow (?:can|do) i (?:play|get|join|sign|start|download|try)\b",
    r"\bis (?:it|this) free\b", r"^\W*(?:link|website|app)\W*$",
    r"\b(?:android|ios|iphone|app store|play store|download)\b"]), re.I)
PUBLIC_STREAK = [
    "Let's go! 🔥 Start your free streak at streakchess.com (link in bio) and tell us your day count tomorrow!",
    "Love it! 🔥 Your streak starts today: streakchess.com, link in bio. Free to play!",
]
DM_CORRECT = ("Shh... {move} is correct 🎯 We keep it secret in the comments until tomorrow. "
              "Want a daily streak of puzzles like this? StreakChess is free to play, and the first 500 accounts get a "
              "Founder offer for Premium: " + LINK)
DM_OTHER = ("Thanks for playing! ♟️ Train your calculation every day with StreakChess, like Duolingo but for chess. "
            "Free to play, and the first 500 accounts get a Founder offer for Premium: " + LINK)


def norm(s):
    return re.sub(r"[x+#!?\s=.]", "", s).lower()


def got_it(text, first_move):
    """True when the comment contains the first solution move (SAN, ignoring x/+/#)."""
    if not first_move:
        return False
    target = norm(first_move)
    tokens = re.findall(r"[KQRBNkqrbn]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?", text)
    return any(norm(t) == target for t in tokens) and len(target) >= 2


def ab_pick(text):
    """'A'-'D' when the comment answers a lettered reel ("A", "c!", "option B", "I think D"), else None."""
    t = text.strip()
    m = re.search(r"\b(?:option|move|answer|choice|candidate)\s*([A-D])\b", t, re.I) or re.fullmatch(r"\W*([A-Da-d])\W*", t) \
        or (len(t.split()) <= 4 and re.search(r"(?<![\w'])([A-D])(?![\w'])(?!\s+\w{3,})", t))
    return m.group(1).upper() if m else None


def load(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


def hide_hint(mid, hidden, answered):
    return mid in hidden and mid not in answered


def main():
    try:
        me = whoami(TOKEN)
    except Exception as e:
        report(0, 0, [f"token/account check failed: {str(e)[:300]}"]); raise SystemExit(1)
    uid = me["user_id"]; myname = me["username"]
    handled = load(HANDLED, {"comments": [], "dm": {}})
    done = set(handled["comments"])
    solutions, hidden, abs_, lessons, science, tours = {}, {}, {}, {}, set(), set()
    if os.path.exists("log.jsonl"):
        for line in open("log.jsonl"):
            e = json.loads(line)
            if e.get("media_id") and (e.get("science") or e.get("mode") == "science"):
                science.add(e["media_id"])
            if e.get("media_id") and (e.get("tour") or e.get("mode") == "tour"):
                tours.add(e["media_id"])
            if e.get("media_id") and e.get("sans"):
                solutions[e["media_id"]] = e["sans"][0]
                if (e.get("story") or "").startswith("Tip: "):
                    lessons[e["media_id"]] = e["story"][5:]
                if e.get("ab"):
                    abs_[e["media_id"]] = e["ab"]
                if e.get("reveal") is False:          # answer was held back: post it in the comments later
                    hidden[e["media_id"]] = e["sans"]
    answered = set(handled.get("answered", []))

    now = datetime.datetime.now(datetime.timezone.utc)
    week_ago = now - datetime.timedelta(days=7)
    media = _check(requests.get(f"{GRAPH}/{uid}/media", params={
        "fields": "id,timestamp,media_product_type,comments_count", "limit": 30, "access_token": TOKEN}))["data"]
    errors = []
    sent_pub = sent_dm = 0
    for m in media:
        ts = datetime.datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00"))
        if m["id"] in hidden and m["id"] not in answered and now - ts >= datetime.timedelta(hours=20):
            ab = abs_.get(m["id"])
            sol = " ".join(hidden[m["id"]])
            why = f". The lesson: {lessons[m['id']].lower()}" if m["id"] in lessons else ""
            msg = random.choice(ANSWER_POSTS).format(sol=f"{ab['correct']} ({sol})" if ab else sol, why=why)
            print(f"answer for {m['id']}: {msg}")
            if not DRY:
                try:
                    _check(requests.post(f"{GRAPH}/{m['id']}/comments", data={"message": msg, "access_token": TOKEN}))
                    answered.add(m["id"])
                except Exception as e:
                    errors.append(f"answer post: {str(e)[:200]}")
        if ts < week_ago:          # private replies only allowed within 7 days
            continue
        if not m.get("comments_count"):
            continue
        try:                       # one problematic post never stops the bot
            comments = _check(requests.get(f"{GRAPH}/{m['id']}/comments", params={
                "fields": "id,text,username,timestamp", "limit": 50, "access_token": TOKEN})).get("data", [])
        except Exception as e:
            errors.append(f"read comments of {m['id']}: {str(e)[:200]}"); continue
        for c in comments:
            if c["id"] in done or c.get("username") == myname:
                continue
            user = c.get("username", "")
            move = solutions.get(m["id"])
            ok = got_it(c.get("text", ""), move)
            ab = abs_.get(m["id"])
            if ab and not ok:                     # A-or-B reels: the right letter counts as correct
                pick = ab_pick(c.get("text", ""))
                ok = pick == ab["correct"]
                if ok:
                    move = f"{pick} ({move})" if not hide_hint(m["id"], hidden, answered) else pick
            hide = m["id"] in hidden and m["id"] not in answered      # never spoil before the answer is posted
            if ASKS_WHAT.search(c.get("text", "")) and not ab_pick(c.get("text", "")):
                pub = random.choice(PUBLIC_WHAT)                    # "what app is this?" always gets a straight answer
            elif m["id"] in tours:
                pub = random.choice(PUBLIC_TOUR); ok = False
            elif re.search(r"\bstreak\b", c.get("text", ""), re.I):
                pub = random.choice(PUBLIC_STREAK)
            elif m["id"] in science:
                pub = random.choice(PUBLIC_SCIENCE); ok = False
            elif hide:
                pub = random.choice(PUBLIC_ANY_HIDDEN)              # no spoilers before the reveal, right or wrong
            elif ok:
                pub = random.choice(PUBLIC_CORRECT).format(move=move)
            else:
                pub = random.choice(PUBLIC_OTHER)
            last_dm = handled["dm"].get(user)
            can_dm = (not last_dm or (now - datetime.datetime.fromisoformat(last_dm)).days >= 7) and \
                     (SEND_DMS == "true" or (SEND_DMS == "correct" and ok))
            dm = (DM_CORRECT if ok else DM_OTHER).format(move=move)
            print(f"@{user}: {c.get('text','')[:80]!r} -> correct={ok} dm={can_dm}")
            if not DRY:
                try:
                    _check(requests.post(f"{GRAPH}/{c['id']}/replies", data={"message": pub, "access_token": TOKEN}))
                    sent_pub += 1
                except Exception as e:
                    print("  public reply failed:", e); errors.append(f"reply: {str(e)[:200]}")
                if can_dm:
                    try:
                        _check(requests.post(f"{GRAPH}/{uid}/messages", json={
                            "recipient": {"comment_id": c["id"]}, "message": {"text": dm}},
                            headers={"Authorization": f"Bearer {TOKEN}"}))
                        handled["dm"][user] = now.isoformat(); sent_dm += 1
                    except Exception as e:
                        print("  private reply failed:", e)
            done.add(c["id"])
    handled["comments"] = sorted(done)[-5000:]
    handled["answered"] = sorted(answered)[-500:]
    if not DRY:
        json.dump(handled, open(HANDLED, "w"), indent=0)
    print(f"Public replies: {sent_pub}, DMs: {sent_dm}")
    report(sent_pub, sent_dm, errors)


def report(sent_pub, sent_dm, errors):
    """Summary on the GitHub run page + a clear hint when the token lacks the comments permissions."""
    hint = ""
    if errors:
        try:
            d = requests.get(f"{GRAPH}/debug_token", params={"input_token": TOKEN, "access_token": TOKEN}, timeout=30).json()["data"]
            need = {"instagram_manage_comments", "instagram_basic", "pages_read_engagement"}
            miss = need - set(d.get("scopes", []))
            hint = (f"Token ({d.get('type')}) is missing: {', '.join(sorted(miss))}. Regenerate the Page token including them."
                    if miss else f"Token ({d.get('type')}) has the comment permissions.")
        except Exception:
            pass
    lines = [f"## Comment bot", f"- Public replies: {sent_pub} · DMs: {sent_dm}"] + \
            [f"- Error: `{e}`" for e in errors[:5]] + ([f"- {hint}"] if hint else [])
    print("\n".join(lines))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write("\n".join(lines) + "\n")
    if errors and sent_pub == 0 and all("read comments" in e for e in errors):
        raise SystemExit("Could not read any comments - see the summary above")


if __name__ == "__main__":
    main()
