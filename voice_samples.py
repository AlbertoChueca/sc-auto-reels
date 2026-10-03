"""Records the same short narration with several Gemini voices so you can pick your favourite.
Output: out/voices/<Voice>.mp3  (set the winner in Settings > Secrets and variables > Actions > Variables > GEMINI_VOICE)"""
import os, subprocess, soundfile as sf
import voice

VOICES = ["Fenrir", "Puck", "Charon", "Algenib", "Sadachbia", "Achird", "Orus", "Umbriel"]
TEXTS = ["Day three hundred of Vektor's training.", "Then the alarm didn't ring.",
         "Eleven fifty-nine. One puzzle left.", "Can you help Vektor find the move?"]
STYLES = ["proud, cozy", "sudden panic", "hushed, tense", "slow, dramatic reveal"]
os.makedirs("out/voices", exist_ok=True)
for v in VOICES:
    voice.GEMINI_VOICE = v
    try:
        clips = voice.say_many(TEXTS, styles=STYLES, one_take=True)
        if voice.ENGINE_USED != "gemini":
            raise RuntimeError("Gemini TTS not available")
        import numpy as np
        a = np.concatenate([np.concatenate([c, np.zeros(int(voice.SR * .25), np.float32)]) for c in clips])
        sf.write("out/voices/tmp.wav", a, voice.SR)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", "out/voices/tmp.wav", "-b:a", "128k",
                        f"out/voices/{v}.mp3"], check=True)
        print("ok", v, flush=True)
    except Exception as e:
        print("FAILED", v, e, flush=True)
if os.path.exists("out/voices/tmp.wav"): os.remove("out/voices/tmp.wav")
