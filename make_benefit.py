"""Benefit reel: Vektor explains ONE real benefit of training with StreakChess (no app screenshots needed).

Visuals are illustrated scenes (Gemini images with the real mascot as reference) that show the idea as a metaphor:
Vektor training his "calculation muscle", keeping his streak flame alive, levelling up... They never pretend to be
app screens. The script may only claim the true facts in assets/app/facts.md (edit that file freely): no invented
statistics, ratings, testimonials or results.

python make_benefit.py <seed> out.mp4            (needs GEMINI_API_KEY)
BENEFIT_MOCK=1 python make_benefit.py 1 out.mp4   (offline test)
"""
import json, math, os, random, re, subprocess, sys
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw
import make_reel as R
import make_hype as HY
import make_story as MS

HERE = os.path.dirname(os.path.abspath(__file__))
FACTS = os.path.join(HERE, "assets", "app", "facts.md")
LOG = os.path.join(HERE, "benefit_log.json")
W, H, FPS, SR = HY.W, HY.H, HY.FPS, HY.SR

DEFAULT_FACTS = [
    "StreakChess is a chess calculation training app, like Duolingo but for chess.",
    "You solve short chess puzzles every day and keep a daily streak.",
    "Puzzles come in levels from beginner to advanced.",
    "It trains calculation: seeing moves ahead before you play them.",
    "It is free to play.",
    "The first 500 accounts get a Founder offer for Premium.",
    "It is made by a chess academy coach.",
]

SCRIPT_PROMPT = """You write a 20-30 second vertical reel where Vektor (the StreakChess mascot) explains ONE clear,
honest benefit of training with StreakChess to young chess players (8-12) and their parents.
{character}

TRUE FACTS you may use (do not claim anything else about the app):
{facts}

{brief}
Recent benefit reels (do NOT repeat their angle): {recent}

Rules:
- Pick ONE angle (e.g. why calculating before moving matters in real games, how a daily streak builds the habit,
  how levels grow with you, why a few minutes a day beats one long session, how puzzles train pattern spotting).
- NEVER invent numbers, ratings, rating gains, user counts, testimonials, studies or guarantees. General chess advice
  is fine when phrased as advice ("players who check every capture blunder less").
- Exactly 4 scenes. Total narration 40-60 words, spoken style, short sentences, numbers as words, no chess notation.
- image_prompt: ONE vertical 9:16 illustrated frame showing the idea as a fun visual metaphor with "the knight mascot
  from the reference images, standing upright" (e.g. lifting a glowing brain dumbbell, guarding a streak flame,
  climbing level stairs made of chessboards). NEVER draw phones, app screens, user interfaces, text, letters,
  numbers or logos.
- label: 2-4 word on-screen label for the scene (e.g. "See it first", "Small daily wins").
- screen_hook: big on-screen text for the first 2 seconds (max 6 words, curiosity, no emoji).
- caption_hook: Instagram first line (max 10 words, max one emoji).
Return JSON: {{"angle": str, "screen_hook": str, "caption_hook": str,
"scenes": [{{"narration": str, "label": str, "image_prompt": str}}]}}"""


def facts():
    if os.path.exists(FACTS):
        f = [l.strip("-* \n") for l in open(FACTS) if l.strip("-* \n") and not l.lstrip().startswith("#")]
        if f:
            return f
    return DEFAULT_FACTS


def write_script(seed):
    import reviewer
    try:
        import agents
        brief = agents._brief("growth")
    except Exception:
        brief = ""
    log = json.load(open(LOG)) if os.path.exists(LOG) else []
    res = reviewer._ask([{"text": SCRIPT_PROMPT.format(
        character=MS.CHARACTER, facts="\n".join(f"- {f}" for f in facts()), brief=brief,
        recent="; ".join(e.get("angle", "") for e in log[-8:]) or "none")}], 0.9)
    sc = [s for s in res.get("scenes", []) if s.get("narration") and s.get("image_prompt")]
    if len(sc) < 3:
        raise RuntimeError("benefit script incomplete")
    bad = re.compile(r"\b(\d{2,}|percent|%|rating|elo|guarantee|studies show|proven|scientifically)\b", re.I)
    if any(bad.search(s["narration"]) for s in sc):
        raise RuntimeError("benefit script made a numeric/unsupported claim")
    res["scenes"] = sc[:4]
    return res


def mock_script():
    lines = ["Strong players see the move before they play it.", "That skill is called calculation, and it grows with practice.",
             "A few puzzles every day keep your streak alive.", "Free to play. Ready to start your streak?"]
    return {"angle": "mock", "screen_hook": "The secret of strong players", "caption_hook": "Train your calculation daily ♟️",
            "scenes": [{"narration": l, "label": ["See it first", "Train calculation", "Keep the streak", "Start today"][i],
                        "image_prompt": ["thinking", "levelup", "happy", "celebrate"][i]} for i, l in enumerate(lines)]}


def build(seed, out, mode="level"):
    mock = os.environ.get("BENEFIT_MOCK") == "1"
    script = mock_script() if mock else write_script(seed)
    scenes = script["scenes"]
    print("Benefit reel:", script.get("angle"), flush=True)

    # illustrations (parallel); the reviewer redraws any off-model / text-filled image once
    def one(i):
        for _ in range(2):
            try:
                return MS.mock_image(scenes[i]["image_prompt"], i) if mock else MS.gen_image(scenes[i]["image_prompt"], MS.REFS)
            except Exception as e:
                print(f"benefit image {i + 1} failed: {str(e)[:150]}", flush=True)
        return None
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as ex:
        imgs = list(ex.map(one, range(len(scenes))))
    if not any(imgs):
        raise RuntimeError("no benefit images")
    imgs = [im if im is not None else next(x for x in imgs if x is not None) for im in imgs]
    if not mock:
        try:
            import reviewer
            redo = reviewer.check_images(imgs, scenes, os.path.join(HERE, "assets", "mascot", "happy.png"))
            for i, p in redo.items():
                try: imgs[i] = MS.gen_image(p, MS.REFS)
                except Exception: pass
        except Exception:
            pass

    import voice
    voice.reset()
    A = voice.say_many([s["narration"] for s in scenes], speed=1.08,
                       styles=["warm, confident coach"] * len(scenes), one_take=True)
    durs = [max(len(a) / SR + 0.45, 2.4) for a in A]
    starts = np.cumsum([0.0] + durs[:-1]); story_end = float(sum(durs))
    CTA = 4.2; total = story_end + CTA
    n = int(SR * (total + 0.5)); vo = np.zeros(n, np.float32); fx = np.zeros(n, np.float32)

    def put(buf, a, at, g=1.0):
        i = int(at * SR)
        if i >= n: return
        j = min(n, i + len(a)); buf[i:j] += a[: j - i] * g
    for i, a in enumerate(A):
        put(vo, a, starts[i] + 0.15)
        if i: put(fx, R.shimmer([659.3, 784.0, 880.0][i % 3]), starts[i] - 0.05, 0.6)
    put(fx, R.ding(), story_end, 0.5)
    tb = np.arange(n) / SR
    pad = sum(np.sin(2 * np.pi * f * tb) for f in (130.8, 196.0, 261.6)) * 0.025 * np.clip(tb / 1.5, 0, 1)
    mix = HY.dehiss(np.tanh((vo * 1.15 + fx + pad.astype(np.float32)) * 1.1) * 0.92)
    wav = out.replace(".mp4", "_b.wav"); sf.write(wav, mix, SR)

    words = []
    for i, s in enumerate(scenes):
        for ts, w in voice.align(A[i], s["narration"]):
            words.append((i, starts[i] + 0.15 + ts, w))

    bigs = [MS.cover(MS.grade(MS.cover(im, 1.0)), 1.18) for im in imgs]
    cams = ["push_in", "pan_left", "pull_out", "push_in"]
    badge = R.pill("WHY STREAKCHESS?", 34, (20, 16, 28), fg=HY.YEL, padx=30, pady=12)
    badge_y = HY.SAFE_TOP + badge.height // 2
    hook_img = HY.fit_phrase(script.get("screen_hook", "").split() or ["StreakChess"], 92, 900, 2)
    hook_y = badge_y + badge.height // 2 + 30 + (hook_img.height + 70) // 2
    HOOK_T = 2.3
    lg = Image.open(os.path.join(HERE, "assets", "logo_h.png")).convert("RGBA"); lg = lg.crop(lg.getbbox())
    lg = lg.resize((560, int(lg.height * 560 / lg.width)), Image.LANCZOS)
    from mascot_rig import Mascot
    mas = Mascot()
    end_bg = HY.vignette(); phones_cache = {}

    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-i", wav, "-shortest"] + HY.enc_args(out), stdin=subprocess.PIPE)
    for fi in range(int(total * FPS)):
        t = fi / FPS
        if t < story_end:
            i = int(np.searchsorted(starts, t, side="right") - 1); lt = t - starts[i]
            fr = MS.frame_for(bigs[i], cams[i % 4], min(1, lt / durs[i]), t).convert("RGBA")
            fr.alpha_composite(HY.vignette())
            hook_on = i == 0 and t < HOOK_T + 0.3
            if hook_on:                                  # hook only (badge above it, measured layout)
                a_ = HY.eob(t / 0.25) * (1 if t < HOOK_T else max(0, 1 - (t - HOOK_T) / 0.3))
                R.paste_center(fr, badge, W / 2, badge_y, a_)
                R.paste_center(fr, HY.band_img(hook_img.height + 70), W / 2, hook_y, a_)
                R.paste_center(fr, hook_img, W / 2, hook_y, a_)
            else:                                        # scene label at the top
                lab = R.pill(scenes[i].get("label", "").upper()[:28], 42, HY.YEL, fg=HY.INK, padx=36, pady=14)
                R.paste_center(fr, lab, W / 2, HY.SAFE_TOP + 40, HY.eob(min(1, lt / 0.3)))
            cur = [(ts, w) for si, ts, w in words if si == i and ts <= t and ts >= HOOK_T]
            if cur and t >= HOOK_T:                      # subtitles (never together with the hook)
                idx = len(cur) - 1; st_ = (idx // 3) * 3
                ph = HY.phrase_img([w for _, w in cur[st_:idx + 1]], t - cur[-1][0], 86)
                R.paste_center(fr, HY.band_img(ph.height + 80), W / 2, 1270)
                R.paste_center(fr, ph, W / 2, 1270)
        else:                                            # end card
            lt = t - story_end
            if "end" not in phones_cache:              # colour mood of the last scene only, no shapes behind
                b = bigs[-1].resize((6, 10), Image.BILINEAR).resize((W, H), Image.BICUBIC).convert("RGBA")
                phones_cache["end"] = Image.blend(b, Image.new("RGBA", (W, H), (12, 9, 22, 255)), 0.8)
            fr = phones_cache["end"].copy()
            fr.alpha_composite(end_bg)
            R.paste_center(fr, lg, W / 2, 420, HY.eob(lt / 0.35))
            mi = mas.render(t, mouth=0, mood="excited", look=(0, 0), bounce=12 * abs(math.sin(lt * 5)))
            mi = mi.resize((int(mi.width * 0.55), int(mi.height * 0.55)), Image.BILINEAR)
            fr.alpha_composite(mi, (int(W / 2 - mi.width / 2), int(1060 - mi.height)))
            R.paste_center(fr, R.pill("FREE TO PLAY", 44, (88, 204, 2), fg=HY.WHITE, padx=40, pady=16), W / 2, 1130, HY.eob((lt - 0.5) / 0.3))
            R.paste_center(fr, R.pill("FOUNDER OFFER - FIRST 500 ACCOUNTS", 34, HY.INK, fg=HY.YEL, padx=32, pady=12), W / 2, 1220, HY.eob((lt - 0.9) / 0.3))
            R.paste_center(fr, R.pill("streakchess.com", 62, HY.WHITE, fg=HY.ORA, padx=48, pady=16), W / 2, 1330, HY.eob((lt - 1.3) / 0.3))
            R.paste_center(fr, HY.word_img("LINK IN BIO", 48, HY.WHITE, 7), W / 2, 1440, HY.eob((lt - 1.8) / 0.3))
        proc.stdin.write(HY.grain(fr, fi))
    proc.stdin.close(); proc.wait(); os.remove(wav)

    rng = random.Random(seed)
    cap = (f"{script.get('caption_hook', 'Train your calculation every day ♟️')}\n"
           "Strong players see the move before they play it. StreakChess trains that habit with a few puzzles a day.\n\n"
           "Comment \"STREAK\" if you're starting today!\n\n"
           "Parents: StreakChess is free to play, with a founder offer for the first 500 accounts. Link in bio.\n\n"
           + " ".join(R.hashtags(rng)))
    open(out.replace(".mp4", ".txt"), "w").write(cap)
    if not mock:
        log = json.load(open(LOG)) if os.path.exists(LOG) else []
        log.append({"angle": script.get("angle")})
        json.dump(log[-100:], open(LOG, "w"), indent=0)
    return dict(mode="benefit", puzzle=None, level=None, story=f"Benefit: {script.get('angle')}",
                hook=script.get("caption_hook"), sans=[], duration=round(total, 1))


if __name__ == "__main__":
    print(json.dumps(build(int(sys.argv[1]), sys.argv[2]), indent=1))
