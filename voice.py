"""Narration voice for all reels.

Engine order (automatic, never blocks a reel):
  1. Gemini TTS (very natural, takes acting directions) when GEMINI_API_KEY is set.
     Story narration is recorded in ONE take so the intonation flows like a real narrator,
     then split into scenes at the natural pauses.
  2. Chatterbox (open source) if VOICE_ENGINE=chatterbox and its venv exists.
  3. Kokoro (local) as last resort.
"""
import base64, json, os, re, subprocess, tempfile, time
import numpy as np
import requests
import soundfile as sf
import make_reel as R

SR = 24000
HERE = os.path.dirname(os.path.abspath(__file__))
KOKORO_VOICE = os.environ.get("HYPE_VOICE", "am_fenrir")
CB_PY = os.environ.get("CHATTERBOX_PY", os.path.join(HERE, ".venv-cb", "bin", "python"))
REF_LINE = ("Think you can calculate faster than everyone else? Let's find out. "
            "This one is tricky, so take a breath and look at the whole board.")

GEMINI_VOICE = os.environ.get("GEMINI_VOICE", "Fenrir")
API = "https://generativelanguage.googleapis.com/v1beta"
TTS_PREFERRED = ["gemini-3.8-flash-tts", "gemini-3.8-flash-tts-preview", "gemini-3.1-flash-tts-preview",
                 "gemini-3.1-flash-tts", "gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts"]
NARRATOR = ("You are a charismatic YouTube storyteller narrating a short, funny animated film about a little chess "
            "knight. Sound like a real human talking to a friend: warm, playful, relaxed breathing, natural pitch "
            "movement, small smiles in the voice, never robotic, never a flat announcer, never over the top.")
ENGINE_USED = None


# ------------------------------------------------------------------ helpers
def _trim(a):
    nz = np.nonzero(np.abs(a) > 0.01)[0]
    return a[max(0, nz[0] - 240): nz[-1] + 1600] if len(nz) else a


def polish(a, light=False):
    """Gentle cleanup. Gemini audio only gets a high-pass + level; local TTS gets a bit more 'mic' colour."""
    a = a.astype(np.float32)
    if len(a) < 10:
        return a
    k = int(SR / 80)
    a = a - np.convolve(a, np.ones(k) / k, "same")                                    # high-pass ~80 Hz
    if not light:
        hi = a - np.convolve(a, np.ones(6) / 6, "same")
        a = a + 0.25 * hi
        a = a / (np.max(np.abs(a)) + 1e-6)
        a = np.sign(a) * (1 - np.exp(-1.6 * np.abs(a))) / (1 - np.exp(-1.6))
    tail = np.zeros(int(SR * 0.1), np.float32)
    out = np.concatenate([a, tail])
    return (out / (np.max(np.abs(out)) + 1e-6) * 0.9).astype(np.float32)


def _resample(a, sr):
    if sr == SR:
        return a.astype(np.float32)
    n = int(len(a) * SR / sr)
    return np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)


def _words(t):
    return max(1, len(re.findall(r"[A-Za-z0-9']+", t)))


# ------------------------------------------------------------------ Gemini TTS
_models = None


def _tts_models(key):
    global _models
    if _models is not None:
        return _models
    found = []
    try:
        r = requests.get(f"{API}/models", params={"key": key, "pageSize": 200}, timeout=30)
        for m in r.json().get("models", []):
            n = m["name"].split("/")[-1]
            if "tts" in n and "generateContent" in m.get("supportedGenerationMethods", []):
                found.append(n)
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Gemini unreachable: {e}")
    except Exception as e:
        print("voice: could not list models:", e, flush=True)
    env = os.environ.get("GEMINI_TTS_MODEL")
    order = ([env] if env else []) + [m for m in TTS_PREFERRED if not found or m in found]

    def rank(n):  # newest flash (not lite) first
        v = re.findall(r"(\d+(?:\.\d+)?)", n)
        return (-float(v[0]) if v else 0, "lite" in n, "pro" in n, "preview" in n)
    order += sorted([m for m in found if m not in order], key=rank)
    _models = list(dict.fromkeys(order))
    return _models


def _gemini_call(prompt, key):
    last = None
    for model in _tts_models(key):
        for attempt in range(4):
            try:
                r = requests.post(f"{API}/models/{model}:generateContent", headers={"x-goog-api-key": key},
                                  timeout=180, json={
                                      "contents": [{"parts": [{"text": prompt}]}],
                                      "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                                          "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": GEMINI_VOICE}}}}})
                if r.status_code in (429, 500, 502, 503, 504):
                    last = RuntimeError(f"{model} {r.status_code}"); time.sleep(8 * (attempt + 1)); continue
                if r.status_code != 200:
                    last = RuntimeError(f"{model} {r.status_code}: {r.text[:200]}"); break
                for p in r.json()["candidates"][0]["content"]["parts"]:
                    d = p.get("inlineData") or p.get("inline_data")
                    if d:
                        mime = d.get("mimeType") or d.get("mime_type") or ""
                        rate = int((re.findall(r"rate=(\d+)", mime) or [24000])[0])
                        pcm = np.frombuffer(base64.b64decode(d["data"]), dtype="<i2").astype(np.float32) / 32768
                        return _resample(pcm, rate)
                last = RuntimeError(f"{model}: no audio in response"); break
            except requests.exceptions.ConnectionError as e:
                raise RuntimeError(f"Gemini unreachable: {e}")
            except Exception as e:
                last = e; time.sleep(4)
    raise last or RuntimeError("no Gemini TTS model available")


def _sane(audio, text, factor=2.6):
    """Reject takes where the model read the stage directions aloud or cut the line."""
    exp = _words(text) / 2.7
    d = len(audio) / SR
    return 0.35 * exp < d < factor * exp + 1.5


def _gemini_line(text, style, key, pace):
    prompt = (f"{NARRATOR}\nDelivery for this line: {style or 'natural and engaging'}, {pace}.\n"
              f"Say only the following line:\n{text}")
    a = _trim(_gemini_call(prompt, key))
    if not _sane(a, text):
        a = _trim(_gemini_call(f"Say {style or 'naturally'}: {text}", key))
        if not _sane(a, text, 3.5):
            raise RuntimeError(f"bad take for: {text!r}")
    return a


def _split_takes(a, texts):
    """Split one continuous take into len(texts) pieces at the longest natural pauses."""
    n = len(texts)
    if n == 1:
        return [a]
    hop = int(SR * 0.01)
    env = np.sqrt(np.convolve(a ** 2, np.ones(hop * 3) / (hop * 3), "same"))[::hop]
    thr = max(0.012, 0.06 * np.percentile(env, 95))
    silent = env < thr
    runs, i = [], 0
    while i < len(silent):
        if silent[i]:
            j = i
            while j < len(silent) and silent[j]: j += 1
            if j - i >= 12 and i > 20 and j < len(silent) - 20:     # >=120 ms, not at the edges
                runs.append((j - i, (i + j) // 2))
            i = j
        else:
            i += 1
    # expected cut points from word counts, choose the longest pause near each one
    w = np.array([_words(t) for t in texts], float)
    exp_cuts = np.cumsum(w)[:-1] / w.sum() * len(env)
    cuts, used = [], set()
    for ec in exp_cuts:
        cands = [(ln, c) for ln, c in runs if c not in used and abs(c - ec) < 0.22 * len(env)]
        if not cands:
            raise RuntimeError("no pause found to split the take")
        ln, c = max(cands, key=lambda x: x[0] - 0.02 * abs(x[1] - ec))
        cuts.append(c); used.add(c)
    if cuts != sorted(cuts):
        raise RuntimeError("pauses out of order")
    edges = [0] + [c * hop for c in cuts] + [len(a)]
    parts = [_trim(a[edges[k]:edges[k + 1]]) for k in range(n)]
    for p, t in zip(parts, texts):
        if not _sane(p, t, 3.0):
            raise RuntimeError("split pieces do not match the text")
    return parts


def _gemini_many(texts, styles, key, one_take, pace):
    if one_take and len(texts) > 1:
        try:
            script = "\n\n".join(f"({s or 'natural'}) {t}" if s else t for t, s in zip(texts, styles))
            prompt = (f"{NARRATOR}\nRead this short story in one continuous performance, at {pace}. "
                      f"Leave a clear breath pause between paragraphs. Words in parentheses are acting directions: "
                      f"follow them but never read them aloud.\n\n{script}")
            take = _trim(_gemini_call(prompt, key))
            return _split_takes(take, texts)
        except Exception as e:
            if "unreachable" in str(e) or "no Gemini TTS" in str(e):
                raise
            print("voice: one-take narration failed, recording line by line:", str(e)[:200], flush=True)
    out = []
    for t, s in zip(texts, styles):
        out.append(_gemini_line(t, s, key, pace))
        time.sleep(1.5)
    return out


# ------------------------------------------------------------------ local engines
def _kokoro(text, speed=1.08):
    return _trim(R.tts(text, voice=KOKORO_VOICE, speed=speed))


CB_SCRIPT = r'''
import json, sys, torch, torchaudio
from chatterbox.tts import ChatterboxTTS
job = json.load(open(sys.argv[1]))
m = ChatterboxTTS.from_pretrained(device="cpu")
for i, t in enumerate(job["texts"]):
    w = m.generate(t, audio_prompt_path=job["ref"], exaggeration=job["exag"], cfg_weight=job["cfg"])
    torchaudio.save(f"{job['dir']}/{i}.wav", w, m.sr)
print("ok")
'''


def _chatterbox_batch(texts):
    d = tempfile.mkdtemp()
    ref = os.path.join(d, "ref.wav")
    sf.write(ref, _kokoro(REF_LINE, 1.0), SR)
    job = os.path.join(d, "job.json"); scr = os.path.join(d, "cb.py")
    json.dump({"texts": texts, "ref": ref, "dir": d, "exag": float(os.environ.get("VOICE_EXAG", "0.65")),
               "cfg": float(os.environ.get("VOICE_CFG", "0.45"))}, open(job, "w"))
    open(scr, "w").write(CB_SCRIPT)
    r = subprocess.run([CB_PY, scr, job], capture_output=True, text=True, timeout=1500)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])
    outs = []
    for i in range(len(texts)):
        a, sr = sf.read(os.path.join(d, f"{i}.wav"), dtype="float32")
        if a.ndim > 1: a = a.mean(1)
        outs.append(_trim(_resample(a, sr)))
    return outs


# ------------------------------------------------------------------ public
def say_many(texts, speed=1.08, styles=None, one_take=False):
    """Returns a list of float32 arrays at 24 kHz, one per text.
    styles: optional acting direction per line ("hushed, suspenseful"...).
    one_take: record all lines as one continuous performance (used for the story narration)."""
    global ENGINE_USED
    texts = [t.replace("3%", "three percent") for t in texts]
    styles = list(styles or [None] * len(texts))
    pace = "a lively, brisk pace" if speed >= 1.1 else "a relaxed but energetic pace"
    key = os.environ.get("GEMINI_API_KEY")
    engine = os.environ.get("VOICE_ENGINE", "gemini").lower()
    if key and engine in ("gemini", "auto", "chatterbox") and os.environ.get("VOICE_NO_GEMINI") != "1":
        try:
            clips = _gemini_many(texts, styles, key, one_take, pace)
            ENGINE_USED = "gemini"
            print(f"voice: gemini {GEMINI_VOICE} ({len(texts)} lines, one_take={one_take})", flush=True)
            return [polish(c, light=True) for c in clips]
        except Exception as e:
            print("voice: gemini failed, trying local voices:", str(e)[-300:], flush=True)
    clips = None
    if os.path.exists(CB_PY) and engine != "kokoro":
        try:
            clips = _chatterbox_batch(texts); ENGINE_USED = "chatterbox"
            print(f"voice: chatterbox ({len(texts)} lines)", flush=True)
        except Exception as e:
            print("voice: chatterbox failed, using kokoro:", str(e)[-300:], flush=True)
    if clips is None:
        clips = [_kokoro(t, speed) for t in texts]; ENGINE_USED = "kokoro"
        print(f"voice: kokoro ({len(texts)} lines)", flush=True)
    return [polish(c) for c in clips]
