"""Every 2 hours: post the pending Instagram Story of any video that you have made public in YouTube Studio.

Stories are rendered at upload time and kept in youtube/stories/<video_id>.mp4 until posted (then deleted).
Pending stories older than 7 days are dropped (the news is stale).
"""
import datetime, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE)
LOG = os.path.join(HERE, "yt_log.jsonl")
STORIES = os.path.join(HERE, "stories")


def main():
    try:
        entries = [json.loads(l) for l in open(LOG) if l.strip()]
    except FileNotFoundError:
        return print("no videos yet")
    pending = [e for e in entries if e.get("story") == "pending" and e.get("video_id")]
    if not pending:
        return print("no pending stories")
    import yt_api as API, publish_ig as IG
    today = datetime.date.today(); changed = False
    for e in pending:
        f = os.path.join(STORIES, f"{e['video_id']}.mp4")
        age = (today - datetime.date.fromisoformat(e["date"])).days
        if not os.path.exists(f) or age > 7:
            e["story"] = "expired"; changed = True
            if os.path.exists(f):
                os.remove(f)
            print(f"{e['video_id']}: story expired"); continue
        status = ((API.video(e["video_id"]) or {}).get("status") or {}).get("privacyStatus")
        print(f"{e['video_id']}: {status}")
        if status == "public":
            IG.publish_story(f)
            e["story"] = "posted"; e["story_posted"] = datetime.datetime.utcnow().isoformat(timespec="minutes")
            os.remove(f); changed = True
    if changed:
        with open(LOG, "w") as fh:
            fh.write("".join(json.dumps(x) + "\n" for x in entries))


if __name__ == "__main__":
    main()
