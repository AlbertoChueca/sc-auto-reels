"""Gemini text calls (JSON) for the long videos. Reuses the model discovery/fallback of the reels.

ask_json(prompt)      -> parsed JSON (responseMimeType json)
ask_grounded(prompt)  -> parsed JSON from a Google-Search-grounded answer (fresh news), plus the source URLs
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _models():
    import make_story as MS
    return list(dict.fromkeys(MS.TEXT_MODELS + [m for m in MS._available() if "flash" in m and not any(
        x in m for x in ("image", "tts", "live", "audio", "lite"))]))


def _json(txt):
    txt = txt.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", txt, re.S)
    if m:
        txt = m.group(1)
    i = min([k for k in (txt.find("{"), txt.find("[")) if k >= 0] or [0])
    return json.loads(txt[i:])


def ask_json(prompt, temperature=0.8):
    import make_story as MS
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}}
    last = None
    for model in _models():
        for attempt in range(2):
            try:
                j = MS._post(model, body)
                out = _json(j["candidates"][0]["content"]["parts"][0]["text"])
                print("text model:", model, flush=True)
                return out
            except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
                last = e                                  # malformed answer: ask the same model again
            except RuntimeError as e:
                last = e
                if " 404" in str(e) or " 400" in str(e):
                    break                                 # model not available: next model
                raise
    raise last


def ask_grounded(prompt, temperature=0.4):
    """Answer with Google Search grounding. Returns (json, [source urls])."""
    import make_story as MS
    body = {"contents": [{"parts": [{"text": prompt + "\n\nAnswer ONLY with the JSON, inside ```json fences."}]}],
            "tools": [{"google_search": {}}], "generationConfig": {"temperature": temperature}}
    last = None
    for model in _models():
        try:
            j = MS._post(model, body)
            c = j["candidates"][0]
            txt = "".join(p.get("text", "") for p in c["content"]["parts"])
            srcs = [ch.get("web", {}).get("uri") for ch in (c.get("groundingMetadata") or {}).get("groundingChunks", [])]
            print("grounded model:", model, flush=True)
            return _json(txt), [s for s in srcs if s]
        except Exception as e:
            last = e
            if " 404" not in str(e) and " 400" not in str(e) and not isinstance(e, (json.JSONDecodeError, KeyError)):
                break
    raise last
