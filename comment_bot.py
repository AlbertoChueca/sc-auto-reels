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
SEND_DMS = os.environ.get("BOT_SEND_DMS") == "true"   # off: public replies only
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
    "✅ ANSWER: {sol}\nDid you get it? Reply with your time ⏱️ New puzzle every day 🔥",
    "✅ The solution is {sol}\nWho found it in under 10 seconds? 👀 Tomorrow's puzzle is coming!",
    "✅ Answer: {sol}\nGot it right? Keep your streak going on StreakChess, link in bio 🔥",
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
]
PUBLIC_STREAK = [
    "Let's go! 🔥 Start your free streak at streakchess.com (link in bio) and tell us your day count tomorrow!",
    "Love it! 🔥 Your streak starts today: streakchess.com, link in bio. Free to play!",
]
DM_CORRECT = ("Great job finding {move}! 🎯 Want a daily streak of puzzles like this? "
              "StreakChess is free to play, and the first 500 accounts get a Founder offer for Premium: " + LINK)
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


def load(path, default):
    return json.load(open(path)) if os.path.exists(path) else default


def main():
    try:
        me = whoami(TOKEN)
    except Exception as e:
        report(0, 0, [f"token/account check failed: {str(e)[:300]}"]); raise SystemExit(1)
    uid = me["user_id"]; myname = me["username"]
    handled = load(HANDLED, {"comments": [], "dm": {}})
    done = set(handled["comments"])
    solutions, hidden = {}, {}
    if os.path.exists("log.jsonl"):
        for line in open("log.jsonl"):
            e = json.loads(line)
            if e.get("media_id") and e.get("sans"):
                solutions[e["media_id"]] = e["sans"][0]
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
            msg = random.choice(ANSWER_POSTS).format(sol=" ".join(hidden[m["id"]]))
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
            hide = m["id"] in hidden and m["id"] not in answered      # never spoil before the answer is posted
            if re.search(r"\bstreak\b", c.get("text", ""), re.I):
                pub = random.choice(PUBLIC_STREAK)
            elif ok:
                pub = random.choice(PUBLIC_CORRECT_HIDDEN if hide else PUBLIC_CORRECT).format(move=move)
            else:
                pub = random.choice(PUBLIC_OTHER_HIDDEN if hide else PUBLIC_OTHER)
            last_dm = handled["dm"].get(user)
            can_dm = not last_dm or (now - datetime.datetime.fromisoformat(last_dm)).days >= 7
            dm = (DM_CORRECT if ok else DM_OTHER).format(move=move)
            print(f"@{user}: {c.get('text','')[:80]!r} -> correct={ok} dm={can_dm}")
            if not DRY:
                try:
                    _check(requests.post(f"{GRAPH}/{c['id']}/replies", data={"message": pub, "access_token": TOKEN}))
                    sent_pub += 1
                except Exception as e:
                    print("  public reply failed:", e); errors.append(f"reply: {str(e)[:200]}")
                if can_dm and SEND_DMS:
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
