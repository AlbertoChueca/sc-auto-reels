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
        TOKEN_INFO["granular"] = {g.get("scope"): g.get("target_ids") for g in d.get("granular_scopes", [])}
        return d.get("scopes"), d.get("type")
    except Exception:
        return None, None


TOKEN_INFO = {}


def diagnose(token):
    """Explain WHY media insights fail: which accounts the permission was granted for + an account-level test."""
    from publish_ig import whoami
    me = whoami(token); uid = me["user_id"]; out = [f"IG account id {uid} (@{me.get('username')})"]
    targets = TOKEN_INFO.get("granular", {}).get("instagram_manage_insights")
    if targets is not None:
        out.append("insights permission granted for: " + (", ".join(targets) or "no accounts")
                   + (" -> OK, includes this account" if uid in targets else " -> MISSING this Instagram account"))
    r = requests.get(f"{GRAPH}/{uid}/insights", params={"metric": "reach", "period": "day", "access_token": token}, timeout=30)
    out.append("account-level insights test: " + ("OK" if r.status_code == 200 else
               f"code {r.json().get('error', {}).get('code')}: {r.json().get('error', {}).get('message', '')[:100]}"))
    return " | ".join(out)


def account_media(token, limit=200):
    """Posts straight from the account: [{id, permalink, timestamp, media_product_type}] (ids Instagram really uses)."""
    from publish_ig import whoami
    uid = whoami(token)["user_id"]
    out, url = [], f"{GRAPH}/{uid}/media"
    params = {"fields": "id,permalink,timestamp,media_product_type", "limit": 50, "access_token": token}
    while url and len(out) < limit:
        r = requests.get(url, params=params, timeout=30); j = r.json()
        if r.status_code != 200:
            LAST_ERROR[0] = f"media list code {j.get('error', {}).get('code')}: {j.get('error', {}).get('message', '')[:120]}"
            break
        out += j.get("data", [])
        url, params = j.get("paging", {}).get("next"), None
    return out


def _norm_link(u):
    return (u or "").split("?")[0].rstrip("/").replace("/reels/", "/reel/").replace("/p/", "/reel/").lower()


def update(days=120):
    """Stats are read for the posts that really exist on the account (the source of truth), then matched to our
    log (by link, else by publication time) to know which experiment produced each one."""
    token = os.environ.get("IG_TOKEN")
    if not token:
        return "insights: nothing to do"
    logs = []
    if os.path.exists(os.path.join(HERE, "log.jsonl")):
        for line in open(os.path.join(HERE, "log.jsonl")):
            try:
                e = json.loads(line)
                if e.get("media_id") or e.get("permalink"):
                    logs.append(e)
            except Exception:
                pass
    by_link = {_norm_link(e.get("permalink")): e for e in logs if e.get("permalink")}
    by_id = {e.get("media_id"): e for e in logs if e.get("media_id")}
    perf = json.load(open(PERF)) if os.path.exists(PERF) else {}
    posts = account_media(token)
    now = datetime.datetime.now(datetime.timezone.utc)
    full = public = matched = 0
    skip = {"bad date": 0, "too new": 0, "too old": 0}; dates = []; types = {}
    for p in posts:
        types[p.get("media_product_type")] = types.get(p.get("media_product_type"), 0) + 1
        try:
            ts = datetime.datetime.fromisoformat(p["timestamp"].replace("+0000", "+00:00"))
        except Exception:
            skip["bad date"] += 1; continue
        dates.append(ts.date().isoformat())
        age = (now - ts).total_seconds() / 86400
        if age < 0.5:
            skip["too new"] += 1; continue
        if age > days:
            skip["too old"] += 1; continue
        e = by_id.get(p["id"]) or by_link.get(_norm_link(p.get("permalink")))
        if e is None:                                   # match by publication time (same day, closest log entry)
            same = [x for x in logs if x.get("date") == ts.date().isoformat()]
            e = same[0] if len(same) == 1 else None
        if e is not None:
            matched += 1
        try:
            m = _metrics(p["id"], token); full += 1
        except PermissionError:
            r = requests.get(f"{GRAPH}/{p['id']}", params={"fields": "like_count,comments_count", "access_token": token}, timeout=30)
            m = r.json() if r.status_code == 200 else {}
            m.pop("id", None); public += 1
        except Exception as err:
            print("insights error", p["id"], str(err)[:150], flush=True); continue
        base = {k: (e or {}).get(k) for k in ("slot", "story", "hook", "level", "mode", "engine", "review_score", "arms")}
        perf[p["id"]] = {**base, "date": ts.date().isoformat(), "permalink": p.get("permalink"),
                         "type": p.get("media_product_type"), **m}
    if full:   # once real stats work, drop old likes-only rows (old ids / different scale) to avoid double counting
        perf = {k: v for k, v in perf.items() if v.get("views") is not None or v.get("reach") is not None}
    json.dump(perf, open(PERF, "w"), indent=0)
    msg = (f"insights: {full} posts with full stats, {public} likes/comments only "
           f"({len(posts)} posts found on the account, {matched} matched to our experiments)")
    if not (full or public) and posts:
        msg += (f" || posts dated {min(dates) if dates else '?'} to {max(dates) if dates else '?'}, types {types}, "
                f"skipped {skip}, our log has {len(logs)} reels from {min((e.get('date') or '?') for e in logs) if logs else '-'}"
                f" to {max((e.get('date') or '?') for e in logs) if logs else '-'}")
    if public and not full:
        scopes, ttype = token_scopes(token)
        msg += f" - token {ttype} - Instagram said: {LAST_ERROR[0]}"
        try:
            msg += " || DIAGNOSIS: " + diagnose(token)
        except Exception as err:
            msg += f" || diagnosis failed: {str(err)[:100]}"
    return msg


if __name__ == "__main__":
    print(update())


def recent_comments(days=14, per_post=50):
    """Anonymous comment texts of recent posts (usernames are never stored). Needs instagram_manage_comments."""
    token = os.environ.get("IG_TOKEN")
    if not token:
        return []
    from publish_ig import whoami
    me = whoami(token).get("username")
    perf = json.load(open(PERF)) if os.path.exists(PERF) else {}
    now = datetime.datetime.now(datetime.timezone.utc); out = []
    for p in account_media(token, limit=60):
        try:
            ts = datetime.datetime.fromisoformat(p["timestamp"].replace("+0000", "+00:00"))
        except Exception:
            continue
        if (now - ts).days > days:
            continue
        r = requests.get(f"{GRAPH}/{p['id']}/comments", params={"fields": "text,username,like_count", "limit": per_post,
                                                                "access_token": token}, timeout=30)
        if r.status_code != 200:
            continue
        for c in r.json().get("data", []):
            if c.get("username") == me or not c.get("text"):
                continue
            out.append({"text": c["text"], "likes": c.get("like_count", 0), "story": (perf.get(p["id"]) or {}).get("story")})
    return out
