"""Collect real Instagram results for published reels -> performance.json (used by the reviewer to learn).

Needs the Page token to include the permission instagram_manage_insights. If it doesn't, this step just says so
and everything else keeps working.
"""
import datetime, json, os, requests

HERE = os.path.dirname(os.path.abspath(__file__))
PERF = os.path.join(HERE, "performance.json")
GRAPH = f"https://graph.facebook.com/{os.environ.get('IG_API_VERSION', 'v23.0')}"
METRICS = ["views", "reach", "likes", "comments", "shares", "saved", "total_interactions", "ig_reels_avg_watch_time"]


def _metrics(media_id, token):
    r = requests.get(f"{GRAPH}/{media_id}/insights", params={"metric": ",".join(METRICS), "access_token": token}, timeout=30)
    if r.status_code == 200:
        return {d["name"]: (d.get("values") or [{}])[0].get("value") for d in r.json().get("data", [])}
    err = r.text
    if "permission" in err.lower() or "#10" in err or "#200" in err:
        raise PermissionError(err[:300])
    out = {}                                              # a metric name not supported -> ask one by one
    for m in METRICS:
        r = requests.get(f"{GRAPH}/{media_id}/insights", params={"metric": m, "access_token": token}, timeout=30)
        if r.status_code == 200:
            for d in r.json().get("data", []):
                out[d["name"]] = (d.get("values") or [{}])[0].get("value")
    return out


def update(days=45):
    token = os.environ.get("IG_TOKEN")
    if not token or not os.path.exists(os.path.join(HERE, "log.jsonl")):
        return "insights: nothing to do"
    perf = json.load(open(PERF)) if os.path.exists(PERF) else {}
    today = datetime.date.today(); n = 0
    for line in open(os.path.join(HERE, "log.jsonl")):
        try:
            e = json.loads(line)
        except Exception:
            continue
        mid = e.get("media_id")
        if not mid:
            continue
        age = (today - datetime.date.fromisoformat(e["date"])).days
        if age < 1 or age > days:
            continue
        try:
            m = _metrics(mid, token)
        except PermissionError as err:
            return ("insights: the IG token lacks 'instagram_manage_insights' permission; the reviewer will work "
                    "without real results until it is added. " + str(err)[:120])
        except Exception as err:
            print("insights error", mid, str(err)[:150], flush=True); continue
        perf[mid] = {**{k: e.get(k) for k in ("date", "slot", "story", "hook", "level", "mode", "engine",
                                              "review_score", "permalink")}, **m}
        n += 1
    json.dump(perf, open(PERF, "w"), indent=0)
    return f"insights: updated {n} reels"


if __name__ == "__main__":
    print(update())
