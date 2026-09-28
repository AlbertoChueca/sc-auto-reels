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
    "Great calculation! {move} is right 🔥",
]
PUBLIC_OTHER = [
    "Thanks for playing! 🔥 The solution is in the video. More puzzles daily, link in bio",
    "Nice try! Watch till the end for the answer ♟️",
    "Love it! 🔥 Train your calculation for free, link in bio",
    "Thanks for the comment! ♟️ New puzzles every day",
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
    me = whoami(TOKEN); uid = me["user_id"]; myname = me["username"]
    handled = load(HANDLED, {"comments": [], "dm": {}})
    done = set(handled["comments"])
    solutions = {}
    if os.path.exists("log.jsonl"):
        for line in open("log.jsonl"):
            e = json.loads(line)
            if e.get("media_id") and e.get("sans"):
                solutions[e["media_id"]] = e["sans"][0]

    now = datetime.datetime.now(datetime.timezone.utc)
    week_ago = now - datetime.timedelta(days=7)
    media = _check(requests.get(f"{GRAPH}/{uid}/media", params={
        "fields": "id,timestamp,media_product_type", "limit": 30, "access_token": TOKEN}))["data"]
    sent_pub = sent_dm = 0
    for m in media:
        ts = datetime.datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00"))
        if ts < week_ago:          # private replies only allowed within 7 days
            continue
        comments = _check(requests.get(f"{GRAPH}/{m['id']}/comments", params={
            "fields": "id,text,username,timestamp", "limit": 50, "access_token": TOKEN})).get("data", [])
        for c in comments:
            if c["id"] in done or c.get("username") == myname:
                continue
            user = c.get("username", "")
            move = solutions.get(m["id"])
            ok = got_it(c.get("text", ""), move)
            pub = random.choice(PUBLIC_CORRECT if ok else PUBLIC_OTHER).format(move=move)
            last_dm = handled["dm"].get(user)
            can_dm = not last_dm or (now - datetime.datetime.fromisoformat(last_dm)).days >= 7
            dm = (DM_CORRECT if ok else DM_OTHER).format(move=move)
            print(f"@{user}: {c.get('text','')[:80]!r} -> correct={ok} dm={can_dm}")
            if not DRY:
                try:
                    _check(requests.post(f"{GRAPH}/{c['id']}/replies", data={"message": pub, "access_token": TOKEN}))
                    sent_pub += 1
                except Exception as e:
                    print("  public reply failed:", e)
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
    if not DRY:
        json.dump(handled, open(HANDLED, "w"), indent=0)
    print(f"Public replies: {sent_pub}, DMs: {sent_dm}")


if __name__ == "__main__":
    main()
