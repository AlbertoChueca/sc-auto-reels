"""Gemini text calls (JSON) for the long videos. Reuses the model discovery/fallback of the reels."""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def ask_json(prompt, temperature=0.8):
    import make_story as MS
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}}
    names = MS.TEXT_MODELS + [m for m in MS._available() if "flash" in m and not any(
        x in m for x in ("image", "tts", "live", "audio", "lite"))]
    last = None
    for model in dict.fromkeys(names):
        try:
            j = MS._post(model, body)
            txt = j["candidates"][0]["content"]["parts"][0]["text"]
            print("text model:", model, flush=True)
            return json.loads(re.sub(r"^```(json)?|```$", "", txt.strip()))
        except Exception as e:
            last = e
            if " 404" not in str(e) and " 400" not in str(e) and not isinstance(e, (json.JSONDecodeError, KeyError)):
                break
    raise last
