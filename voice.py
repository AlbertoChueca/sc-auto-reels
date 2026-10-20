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
NARRATOR = ("You are the fun, charismatic narrator of a kids' animated show (ages 8-12) about Vektor, a little chess knight. "
            "Sound like a real human talking to kids you like: warm, playful, curious, relaxed breathing, natural pitch "
            "movement, smiles in the voice. Never robotic, never a flat announcer, never babyish or over the top.")
ENGINE_USED = None
LOCK = None          # engine chosen for the current reel: every line of one reel uses the same voice


class VoiceError(RuntimeError):
    """The engine locked for this reel failed; the caller must redo the whole reel with another engine."""


def reset(force=None):
    """Call at the start of every reel. force: None (best available), 'local' (no Gemini) or 'kokoro'."""
    global LOCK
    LOCK = force
    _CLIPS.clear()
    ALIGN_STATS.update(asr=0, fallback=0)


# ------------------------------------------------------------------ speech recognition (captions + checks)
_asr_model, _asr_cache = None, {}


import threading
_asr_lock = threading.Lock()


def _asr(a):
    with _asr_lock:
        return _asr_inner(a)


def _asr_inner(a):
    """[(word, start_s, end_s)] heard in a 24 kHz clip, or None if speech recognition is unavailable."""
    global _asr_model
    k = (len(a), round(float(np.sum(np.abs(a[::97]))), 3))
    if k in _asr_cache:
        return _asr_cache[k]
    if _asr_model is False:
        return None
    try:
        if _asr_model is None:
            from faster_whisper import WhisperModel
            _asr_model = WhisperModel(os.environ.get("ASR_MODEL", "base.en"), device="cpu", compute_type="int8")
        a16 = np.interp(np.linspace(0, len(a) - 1, int(len(a) * 16000 / SR)), np.arange(len(a)), a).astype(np.float32)
        segs, _ = _asr_model.transcribe(a16, language="en", beam_size=1, word_timestamps=True, vad_filter=False)
        out = [(w.word.strip(), float(w.start), float(w.end)) for sg in segs for w in (sg.words or []) if w.word.strip()]
    except Exception as e:
        print("voice: speech recognition unavailable:", str(e)[:150], flush=True)
        _asr_model = False
        return None
    _asr_cache[k] = out
    return out


def _norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen " \
        "seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _num_words(n):
    if n < 20: return _ONES[n]
    if n < 100: return _TENS[n // 10] + ("" if n % 10 == 0 else _ONES[n % 10])
    if n < 1000: return _ONES[n // 100] + "hundred" + ("" if n % 100 == 0 else _num_words(n % 100))
    if n < 10000: return _ONES[n // 1000] + "thousand" + ("" if n % 1000 == 0 else _num_words(n % 1000))
    return str(n)


def _spoken(text):
    """Letters-only spoken form, so 'H6' == 'H six', '300' == 'three hundred', 'Rook takes h6' == 'Rook takes H six'."""
    t = text.lower().replace("%", " percent").replace("&", " and ")
    t = re.sub(r"\d+", lambda m: " " + _num_words(int(m.group())) + " ", t)
    return re.sub(r"[^a-z]", "", t)


def _similarity(a, text):
    """0..1 how well the audio says the text (None when we cannot check). Compared letter by letter on the
    spoken form, so notation, numbers and punctuation written differently by the recogniser do not count."""
    heard = _asr(a)
    if heard is None:
        return None
    import difflib
    x, y = _spoken(text), _spoken(" ".join(w for w, _, _ in heard))
    if not x or not y:
        return 0.0
    return difflib.SequenceMatcher(None, x, y, autojunk=False).ratio()


ALIGN_STATS = {"asr": 0, "fallback": 0}
_ALIASES = {"victor": "Vektor", "vector": "Vektor", "vecktor": "Vektor", "zugswang": "Zugzwang", "zoogzwang": "Zugzwang",
            "streak": "Streak", "streakchess": "StreakChess", "streakches": "StreakChess"}


def align(a, text):
    """Subtitles = the SCRIPT's words (never a misheard word like 'Lincoln bio'), timed by speech recognition.
    Matched words take the time the voice said them; script words in a mismatched stretch are spread over the
    time of that stretch; skipped words are interpolated between their neighbours. Without speech recognition we
    fall back to timing proportional to characters."""
    import difflib
    ws = text.split()
    heard = _asr(a)
    if heard and ws:
        ALIGN_STATS["asr"] += 1
        hn = [_norm(w) for w, _, _ in heard]
        sn = [_norm(w) for w in ws]
        tt = [None] * len(ws)
        sm = difflib.SequenceMatcher(None, sn, hn, autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                for k in range(i2 - i1):
                    tt[i1 + k] = heard[j1 + k][1]
            elif op == "replace":
                t0, t1 = heard[j1][1], heard[j2 - 1][2]
                n = i2 - i1
                for k in range(n):
                    tt[i1 + k] = t0 + (t1 - t0) * k / max(1, n)
        dur = len(a) / SR
        for k in range(len(ws)):                              # words the voice skipped: interpolate
            if tt[k] is None:
                prev = next((tt[q] for q in range(k - 1, -1, -1) if tt[q] is not None), 0.0)
                nxt = next((tt[q] for q in range(k + 1, len(ws)) if tt[q] is not None), dur)
                tt[k] = prev + (nxt - prev) * 0.5
        out = []
        for k, w in enumerate(ws):
            alias = _ALIASES.get(_norm(w))
            if alias and alias.lower() in text.lower():
                w = re.sub(r"[A-Za-z]+", alias, w, count=1)
            out.append((tt[k], w))
        for k in range(1, len(out)):                         # keep order
            if out[k][0] < out[k - 1][0] + 0.04:
                out[k] = (out[k - 1][0] + 0.04, out[k][1])
        return out
    ALIGN_STATS["fallback"] += 1
    L = sum(len(w) + 1 for w in ws); acc = 0; out = []        # fallback: proportional to characters
    for w in ws:
        out.append(((len(a) / SR) * acc / L * 0.95, w)); acc += len(w) + 1
    return out


# ------------------------------------------------------------------ helpers
def _trim(a):
    if len(a) == 0:
        return a
    thr = max(0.01, 0.04 * float(np.max(np.abs(a))))
    nz = np.nonzero(np.abs(a) > thr)[0]
    return a[max(0, nz[0] - 240): nz[-1] + 1600] if len(nz) else a


def _tighten(a, max_gap=0.32):
    """Shorten long internal silences (dramatic pauses, breaths) so short lines stay short."""
    hop = int(SR * 0.01)
    if len(a) < hop * 10:
        return a
    env = np.sqrt(np.convolve(a ** 2, np.ones(hop * 3) / (hop * 3), "same"))[::hop]
    quiet = env < max(0.01, 0.05 * np.percentile(env, 95))
    keep = np.ones(len(a), bool); i = 0; mg = int(max_gap * 100)
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]: j += 1
            if j - i > mg:
                keep[(i + mg // 2) * hop:(j - mg // 2) * hop] = False
            i = j
        else:
            i += 1
    return a[keep]


def degate(a):
    """Remove breaths, hiss and noise between words and at the edges of every clip.
    Frames (20 ms) are 'voiced' when they are loud and tonal. Any run of non-voiced frames longer than 120 ms
    (breath, hiss, room noise) is faded down to near silence; short ones (s, f, sh, t inside words) are kept.
    Leading/trailing non-voiced audio is cut off completely."""
    a = a.astype(np.float32)
    fr = int(SR * 0.02)
    n = len(a) // fr
    if n < 5:
        return a
    X = np.abs(np.fft.rfft(a[: n * fr].reshape(n, fr) * np.hanning(fr), axis=1)) + 1e-9
    rms = np.sqrt(np.mean(a[: n * fr].reshape(n, fr) ** 2, axis=1))
    flat = np.exp(np.mean(np.log(X[:, 3:]), axis=1)) / np.mean(X[:, 3:], axis=1)
    p90 = np.percentile(rms, 90) + 1e-9
    quiet = rms < 0.12 * p90
    hiss = flat > 0.75                                   # white-noise-like (speech sounds stay below ~0.72)
    breathy = (flat > 0.55) & (rms < 0.35 * p90)         # breaths: noisy and softer than speech
    g = np.ones(n, np.float32)

    def gate(mask, min_run):
        i = 0
        while i < n:
            if mask[i]:
                j = i
                while j < n and mask[j]: j += 1
                if j - i >= min_run or i == 0 or j == n:
                    g[i:j] = 0.02
                i = j
            else:
                i += 1
    gate(quiet | hiss, 4)                                # silence/hiss runs >= 80 ms
    gate(breathy, 8)                                     # breaths >= 160 ms
    keep = g > 0.5
    if not keep.any():
        return a
    first, last = int(np.argmax(keep)), n - 1 - int(np.argmax(keep[::-1]))
    gs = np.repeat(g, fr)
    gs = np.concatenate([gs, np.full(len(a) - len(gs), gs[-1])])
    ramp = int(SR * 0.012)                          # smooth 12 ms gain changes (no clicks)
    gs = np.convolve(gs, np.ones(ramp) / ramp, "same")
    out = (a * gs)[max(0, first * fr - int(SR * 0.03)): min(len(a), (last + 1) * fr + int(SR * 0.08))]
    fade = min(int(SR * 0.015), len(out) // 4)
    if fade > 1:
        out[:fade] *= np.linspace(0, 1, fade); out[-fade:] *= np.linspace(1, 0, fade)
    return out.astype(np.float32)


def polish(a, light=False):
    """Cleanup: breath/hiss gate, then a high-pass + level (local TTS gets a bit more 'mic' colour)."""
    a = degate(a.astype(np.float32))
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


def _ratio(audio, text):
    return (len(audio) / SR) / (_words(text) / 2.7 + 0.6)


def _sane(audio, text, factor=2.6):
    """Reject takes where the model read the stage directions aloud or cut the line."""
    r = _ratio(audio, text)
    return 0.3 < r < factor


def _clean_edges(a, text):
    """Cut any extra words the model spoke before/after the line (e.g. a stray "Say..." or an acting note),
    using the word timings from speech recognition."""
    heard = _asr(a)
    ws = [_spoken(w) for w in text.split()]
    ws = [w for w in ws if w]
    if not heard or not ws:
        return a
    hw = [_spoken(w) for w, _, _ in heard]
    start = end = None
    k = min(2, len(ws))                                    # where the line really starts: its first words, anywhere
    for j in range(len(hw) - k + 1):                       # (acting notes read aloud can be 10+ words long)
        if hw[j:j + k] == ws[:k]:
            start = j; break
    if start is None:
        for j in range(min(4, len(hw))):
            if hw[j] and (hw[j] == ws[0] or (len(ws) > 1 and hw[j] == ws[1] and j > 0)):
                start = j if hw[j] == ws[0] else j - 1; break
    for j in range(len(hw) - 1, k - 2, -1):                # where it ends: its last words (drops repeats after)
        if hw[j - k + 1:j + 1] == ws[-k:]:
            end = j; break
    if end is None:
        for j in range(len(hw) - 1, max(-1, len(hw) - 5), -1):
            if hw[j] and hw[j] == ws[-1]:
                end = j; break
    t0 = heard[start][1] - 0.08 if start else 0.0
    t1 = heard[end][2] + 0.25 if end is not None and end < len(hw) - 1 else None
    if start or t1:
        print(f"voice: trimmed extra words around {text[:40]!r}", flush=True)
        _asr_cache.clear()
        b = a[int(max(0, t0) * SR): int(t1 * SR) if t1 else len(a)]
        return b if len(b) > SR * 0.3 else a
    return a


LEAK_WORDS = {"director", "directors", "notes", "storyteller", "transcript", "delivery", "narrator", "paragraph",
              "pace", "tone", "warm"}


def _leaked(a, text):
    """True when the take contains prompt words that are not in the line (the model read its instructions)."""
    heard = _asr(a)
    if not heard:
        return False
    mine = {_spoken(w) for w in text.split()}
    extra = [w for w in (_spoken(x) for x, _, _ in heard) if w in LEAK_WORDS and w not in mine]
    if len(extra) >= 2 or ("director" in extra or "directors" in extra or "transcript" in extra):
        print(f"voice: take read the instructions aloud ({' '.join(extra)}), rejected", flush=True)
        return True
    return False


def _gemini_line(text, style, key, pace):
    """Up to 3 takes with different prompt shapes. A take is accepted when it says the right words with a
    natural length; otherwise the best acceptable one is kept. Fails only if every take is clearly wrong."""
    notes = f"### DIRECTOR'S NOTES\n{NARRATOR}\nDelivery: {style or 'natural and engaging'}, {pace}.\n" \
            f"Read ONLY the transcript, word for word. Never read these notes.\n### TRANSCRIPT\n"
    prompts = [notes + text,
               f"### DIRECTOR'S NOTES\nWarm, friendly storyteller, {style or 'natural'}.\n### TRANSCRIPT\n{text}",
               text]
    takes = []
    for pr in prompts:
        try:
            a = _clean_edges(_tighten(_trim(_gemini_call(pr, key))), text)
        except Exception as e:
            if "unreachable" in str(e) or "no Gemini TTS" in str(e):
                raise
            print("voice: take error:", str(e)[:150], flush=True); continue
        if _leaked(a, text):
            continue
        sim = _similarity(a, text)
        if (sim is None or sim >= 0.7) and _sane(a, text):
            return a
        print(f"voice: retake {text!r} ({len(a) / SR:.1f}s, match {sim if sim is None else round(sim, 2)})", flush=True)
        if 0.3 < _ratio(a, text) < 3.5 and (sim is None or sim >= 0.6):
            takes.append(((sim or 0.7), -abs(np.log(_ratio(a, text))), a))
    if takes:
        return max(takes, key=lambda x: (x[0], x[1]))[2]
    raise RuntimeError(f"bad take for: {text!r}")


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
    parts = [_clean_edges(_tighten(_trim(a[edges[k]:edges[k + 1]])), texts[k]) for k in range(n)]
    for p, t in zip(parts, texts):
        sim = _similarity(p, t)
        if not _sane(p, t, 3.2) or (sim is not None and sim < 0.7) or _leaked(p, t):
            raise RuntimeError("split pieces do not match the text")
    return parts


def _gemini_many(texts, styles, key, one_take, pace):
    if one_take and len(texts) > 1:
        try:
            notes = "\n".join(f"- Paragraph {i + 1}: {s or 'natural'}" for i, s in enumerate(styles))
            script = "\n\n".join(texts)
            prompt = (f"{NARRATOR}\nPerform the TRANSCRIPT below in one continuous take, at {pace}, with a clear "
                      f"breath pause between paragraphs. Read only the transcript, word for word.\n"
                      f"DIRECTOR'S NOTES:\n{notes}\n\nTRANSCRIPT:\n{script}")
            take = _trim(_gemini_call(prompt, key))
            print(f"voice: one take {len(take) / SR:.1f}s for {sum(_words(t) for t in texts)} words", flush=True)
            if len(take) / SR > 2.2 * sum(_words(t) / 2.7 + 0.6 for t in texts) + 2:
                raise RuntimeError("one take far too long (model added extra speech)")
            return _split_takes(take, texts)
        except Exception as e:
            if "unreachable" in str(e) or "no Gemini TTS" in str(e):
                raise
            print("voice: one-take narration failed, recording line by line:", str(e)[:200], flush=True)
    from concurrent.futures import ThreadPoolExecutor        # 3 lines recorded at the same time
    with ThreadPoolExecutor(3) as ex:
        return list(ex.map(lambda ts: _gemini_line(ts[0], ts[1], key, pace), zip(texts, styles)))


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
    one_take: record all lines as one continuous performance (used for the story narration).
    All calls inside one reel use the same engine (see reset/LOCK); if that engine fails later in the
    reel, VoiceError is raised so the caller can redo the reel with a single consistent voice."""
    global ENGINE_USED, LOCK
    texts = [t.replace("3%", "three percent") for t in texts]
    ck = (tuple(texts), tuple(styles or ()), one_take, LOCK)
    if ck in _CLIPS:
        return [c.copy() for c in _CLIPS[ck]]
    out = _say_many(texts, speed, styles, one_take)
    _CLIPS[(tuple(texts), tuple(styles or ()), one_take, LOCK)] = [c.copy() for c in out]
    return out


_CLIPS = {}


def _say_many(texts, speed, styles, one_take):
    global ENGINE_USED, LOCK
    styles = list(styles or [None] * len(texts))
    pace = "a lively, brisk pace" if speed >= 1.1 else "a relaxed but energetic pace"
    key = os.environ.get("GEMINI_API_KEY")
    engine = os.environ.get("VOICE_ENGINE", "gemini").lower()
    allow_gemini = (key and engine in ("gemini", "auto", "chatterbox") and os.environ.get("VOICE_NO_GEMINI") != "1"
                    and LOCK in (None, "gemini"))
    allow_cb = os.path.exists(CB_PY) and engine != "kokoro" and LOCK in (None, "local", "chatterbox")
    if allow_gemini:
        try:
            clips = _gemini_many(texts, styles, key, one_take, pace)
            ENGINE_USED = LOCK = "gemini"
            print(f"voice: gemini {GEMINI_VOICE} ({len(texts)} lines, one_take={one_take})", flush=True)
            return [polish(c, light=True) for c in clips]
        except Exception as e:
            if LOCK == "gemini":
                raise VoiceError(f"gemini failed mid-reel: {str(e)[-200:]}")
            print("voice: gemini failed, trying local voices:", str(e)[-300:], flush=True)
    if allow_cb:
        try:
            clips = _chatterbox_batch(texts); ENGINE_USED = LOCK = "chatterbox"
            print(f"voice: chatterbox ({len(texts)} lines)", flush=True)
            return [polish(c) for c in clips]
        except Exception as e:
            if LOCK == "chatterbox":
                raise VoiceError(f"chatterbox failed mid-reel: {str(e)[-200:]}")
            print("voice: chatterbox failed, using kokoro:", str(e)[-300:], flush=True)
    if LOCK not in (None, "local", "kokoro"):
        raise VoiceError(f"{LOCK} not available")
    clips = [_kokoro(t, speed) for t in texts]; ENGINE_USED = LOCK = "kokoro"
    print(f"voice: kokoro ({len(texts)} lines)", flush=True)
    return [polish(c) for c in clips]


def next_engine():
    """Engine to force after a VoiceError."""
    return {"gemini": "local", "chatterbox": "kokoro"}.get(LOCK, "kokoro")
