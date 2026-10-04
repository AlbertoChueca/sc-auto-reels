"""Collect real Instagram results for published reels -> performance.json (used by the reviewer to learn).

Needs the Page token to include the permission instagram_manage_insights. If it doesn't, this step just says so
and everything else keeps working.
"""
import datetime, json, os, requests

HERE = os.path.dirname(os.path.abspath(__file__))
PERF = os.path.join(HERE, "performance.json")
GRAPH = f"https://graph.facebook.com/{os.environ.get('IG_API_VERSION', 'v23.0')}"
LAST_ERROR = [""]
METRICS = ["views", "reach", "likes", "comments", "shares", "saved", "total_interactions", "ig_reels_avg_watch_time"]


def _metrics(media_id, token):
    r = requests.get(f"{GRAPH}/{media_id}/insights", params={"metric": ",".join(METRICS), "access_token": token}, timeout=30)
    if r.status_code == 200:
        return {d["name"]: (d.get("values") or [{}])[0].get("value") for d in r.json().get("data", [])}
    try:
        e = r.json().get("error", {})
    except Exception:
        e = {}
    LAST_ERROR[0] = f"code {e.get('code')}: {str(e.get('message') or r.text)[:160]}"
    if e.get("code") in (10, 200) or (e.get("code") == 190):      # real permission / token problem
        raise PermissionError(LAST_ERROR[0])
    out = {}                                              # e.g. (#100) a metric not available -> ask one by one
    for m in METRICS:
        r = requests.get(f"{GRAPH}/{media_id}/insights", params={"metric": m, "access_token": token}, timeout=30)
        if r.status_code == 200:
            for d in r.json().get("data", []):
                out[d["name"]] = (d.get("values") or [{}])[0].get("value")
    if not out:
        raise PermissionError(LAST_ERROR[0])
    return out


def token_scopes(token):
    """Permissions really included in the token (asks Meta's debug_token about itself)."""
    try:
        r = requests.get(f"{GRAPH}/debug_token", params={"input_token": token, "access_token": token}, timeout=30)
        d = r.json().get("data", {})
        return d.get("scopes"), d.get("type")
    except Exception:
        return None, None


def update(days=45):
    token = os.environ.get("IG_TOKEN")
    if not token or not os.path.exists(os.path.join(HERE, "log.jsonl")):
        return "insights: nothing to do"
    perf = json.load(open(PERF)) if os.path.exists(PERF) else {}
    today = datetime.date.today(); full = public = 0; fails = 0
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
        m = None
        try:
            if fails < 3:                                 # every reel is tried; stop trying after 3 refusals in a row
                try:
                    m = _metrics(mid, token); full += 1; fails = 0
                except PermissionError:
                    fails += 1
            if m is None:                                 # fallback: public like/comment counts (basic permission)
                r = requests.get(f"{GRAPH}/{mid}", params={"fields": "like_count,comments_count", "access_token": token}, timeout=30)
                m = r.json() if r.status_code == 200 else {}
                m.pop("id", None); public += 1
        except Exception as err:
            print("insights error", mid, str(err)[:150], flush=True); continue
        perf[mid] = {**{k: e.get(k) for k in ("date", "slot", "story", "hook", "level", "mode", "engine",
                                              "review_score", "permalink", "arms")}, **m}
    json.dump(perf, open(PERF, "w"), indent=0)
    msg = f"insights: {full} reels with full stats"
    if public:
        scopes, ttype = token_scopes(token)
        if scopes is None:
            perm = "could not read the token's permissions"
        elif "instagram_manage_insights" in scopes:
            perm = f"token ({ttype}) HAS instagram_manage_insights"
        else:
            perm = f"token ({ttype}) does NOT have instagram_manage_insights (has: {', '.join(scopes)})"
        msg += f", {public} with likes/comments only - {perm} - Instagram said: {LAST_ERROR[0]}"
    return msg


if __name__ == "__main__":
    print(update())
