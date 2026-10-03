"""Narration voice for all reels.

Engine order (automatic, never blocks a reel):
  1. Chatterbox (open-source, more human/expressive) if VOICE_ENGINE=chatterbox and its venv exists.
     It speaks with the timbre of a Kokoro reference clip, so the voice stays consistent day to day.
  2. Kokoro (current local voice) as fallback.
Every clip then gets a 'studio' polish: high-pass, presence boost, gentle compression, short room tail.
"""
import json, os, subprocess, tempfile
import numpy as np
import soundfile as sf
import make_reel as R

SR = 24000
HERE = os.path.dirname(os.path.abspath(__file__))
KOKORO_VOICE = os.environ.get("HYPE_VOICE", "am_fenrir")
CB_PY = os.environ.get("CHATTERBOX_PY", os.path.join(HERE, ".venv-cb", "bin", "python"))
REF_LINE = ("Think you can calculate faster than everyone else? Let's find out. "
            "This one is tricky, so take a breath and look at the whole board.")


def _trim(a):
    nz = np.nonzero(np.abs(a) > 0.01)[0]
    return a[max(0, nz[0] - 240): nz[-1] + 1600] if len(nz) else a


def polish(a):
    """Light 'radio voice' chain: HP 90 Hz, presence lift, soft compression, tiny room."""
    a = a.astype(np.float32)
    if len(a) < 10:
        return a
    a = a - np.convolve(a, np.ones(int(SR / 90)) / int(SR / 90), "same")          # high-pass ~90 Hz
    hi = a - np.convolve(a, np.ones(6) / 6, "same")                                 # presence ~3-5 kHz
    a = a + 0.35 * hi
    peak = np.max(np.abs(a)) + 1e-6; a = a / peak
    a = np.sign(a) * (1 - np.exp(-2.2 * np.abs(a))) / (1 - np.exp(-2.2))            # soft compression
    tail = np.zeros(int(SR * 0.12), np.float32)
    from scipy.signal import fftconvolve
    room = fftconvolve(np.concatenate([a, tail]), np.exp(-np.arange(int(SR * 0.12)) / (SR * 0.025)) * 0.0009)[: len(a) + len(tail)]
    out = np.concatenate([a, tail]) + room
    return (out / (np.max(np.abs(out)) + 1e-6) * 0.9).astype(np.float32)


def _kokoro(text, speed=1.08):
    return _trim(R.tts(text, voice=KOKORO_VOICE, speed=speed))


def _resample(a, sr):
    if sr == SR:
        return a.astype(np.float32)
    n = int(len(a) * SR / sr)
    return np.interp(np.linspace(0, len(a) - 1, n), np.arange(len(a)), a).astype(np.float32)


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


def say_many(texts, speed=1.08):
    """Returns a list of float32 arrays at 24 kHz, one per text."""
    texts = [t.replace("3%", "three percent") for t in texts]
    clips = None
    if os.environ.get("VOICE_ENGINE", "").lower() == "chatterbox" and os.path.exists(CB_PY):
        try:
            clips = _chatterbox_batch(texts)
            print(f"voice: chatterbox ({len(texts)} lines)", flush=True)
        except Exception as e:
            print("voice: chatterbox failed, using kokoro:", str(e)[-300:], flush=True)
    if clips is None:
        clips = [_kokoro(t, speed) for t in texts]
        print(f"voice: kokoro ({len(texts)} lines)", flush=True)
    return [polish(c) for c in clips]
