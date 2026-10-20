"""Procedurally animated StreakChess knight (Duolingo-style talking mascot).

Built from the flat 'happy' artwork: the original eyes are replaced with rigged eyes
(blink, look direction, expressions), the muzzle gets a jaw that opens with the voice,
and the flame mane waves. Body supports squash/stretch, bob and tilt.
"""
import math, os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "assets", "mascot", "happy.png")
BODY = (56, 56, 56, 255)
OUT = (22, 22, 24, 255)

EYES = [((494, 340), 31, 24), ((567, 361), 32, 25)]   # centre, rx, ry (original art)
# Mouth rig on the snout: the lower jaw (below the mouth line) rotates open around the mouth corner.
HINGE = (578, 474)                                    # mouth corner
TIP = (641, 463)                                      # front end of the mouth line
JAW_BOTTOM = 522


def mouth_y(x):
    """y of the mouth line at x (straight line corner -> tip)."""
    return HINGE[1] + (x - HINGE[0]) * (TIP[1] - HINGE[1]) / (TIP[0] - HINGE[0])


class Mascot:
    def __init__(self):
        im = Image.open(SRC).convert("RGBA")
        a = np.array(im).astype(np.int16)
        W, H = im.size
        self.size = (W, H)
        # paint over original eyes
        d = ImageDraw.Draw(im)
        for (cx, cy), rx, ry in EYES:
            d.ellipse([cx - rx - 4, cy - ry - 4, cx + rx + 4, cy + ry + 4], fill=BODY)
        a = np.array(im).astype(np.int16)
        r, g, b, al = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
        warm = (r > g + 35) & (r > b + 60) & (al > 0)
        self.flame = np.where(warm[..., None], a, 0).astype(np.uint8)
        body = np.where(warm[..., None], 0, a).astype(np.uint8)
        yy, xx = np.mgrid[0:H, 0:W]
        self.body = body
        inner = (body[..., 3] > 200) & (body[..., 0] > 40)            # grey head, not the black outline
        self.inner = Image.fromarray((inner * 255).astype(np.uint8), "L").filter(ImageFilter.MinFilter(5))
        self.body_im = Image.fromarray(self.body, "RGBA")
        self.yy = yy
        self.xx = xx
        # natural timing: irregular blinks (some double), eye saccades, smoothed lip-sync state
        rng = np.random.RandomState(11)
        self.blinks, t = [], 1.2
        while t < 600:
            self.blinks.append(t)
            if rng.rand() < 0.2: self.blinks.append(t + 0.28)
            t += rng.uniform(2.2, 5.0)
        self.blinks = np.array(self.blinks)
        self.sacc_t = np.cumsum(rng.uniform(0.9, 2.4, 600))
        self.sacc_xy = rng.uniform(-1, 1, (600, 2)) * np.array([0.28, 0.16])
        self._mo, self._last_t = 0.0, None

    # ------------------------------------------------------------------ pieces
    def _flame(self, t):
        H, W = self.size[1], self.size[0]
        rows = np.arange(H)
        amp = 7 * np.clip(1 - rows / 520, 0, 1) ** 1.3
        dx = (amp * np.sin(rows / 26.0 - t * 7.5) + amp * 0.5 * np.sin(rows / 11.0 + t * 11)).astype(int)
        idx = np.clip(np.arange(W)[None, :] - dx[:, None], 0, W - 1)
        f = np.take_along_axis(self.flame, idx[..., None].repeat(4, 2), axis=1)
        return Image.fromarray(f, "RGBA")

    def _eyes(self, d, blink, look, mood):
        lx, ly = look
        for i, ((cx, cy), rx, ry) in enumerate(EYES):
            if mood == "star":
                self._star(d, cx, cy, rx * 1.05, fill=(255, 210, 60)); continue
            h = max(2, ry * (1 - blink))
            if mood == "happy_closed":
                d.arc([cx - rx, cy - ry * 0.6, cx + rx, cy + ry * 0.9], 200, 340, fill=OUT, width=9); continue
            d.ellipse([cx - rx, cy - h, cx + rx, cy + h], fill=(255, 255, 255, 255))
            if h > 6:
                pr = 15
                px, py = cx + lx * (rx - pr - 3), cy + ly * (h - pr - 2) * 0.8
                d.ellipse([px - pr, py - pr, px + pr, py + pr], fill=OUT)
                d.ellipse([px - 7, py - 10, px + 1, py - 2], fill=(255, 255, 255, 255))
            if blink > 0.05:  # eyelid line
                d.line([cx - rx, cy - h, cx + rx, cy - h], fill=BODY, width=3)
        # brows
        if mood in ("determined", "angry"):
            cut = 0.55 if mood == "angry" else 0.35
            for i, ((cx, cy), rx, ry) in enumerate(EYES):
                inner_low = cy - ry + 2 * ry * cut          # lid comes down toward the inner side
                outer_low = cy - ry + 2 * ry * cut * 0.25
                if i == 0:   # viewer-left eye: inner side is the right
                    p1, p2 = (cx - rx - 6, outer_low), (cx + rx + 6, inner_low)
                else:
                    p1, p2 = (cx - rx - 6, inner_low), (cx + rx + 6, outer_low)
                d.polygon([(cx - rx - 6, cy - ry - 8), (cx + rx + 6, cy - ry - 8), (p2[0], p2[1]), (p1[0], p1[1])], fill=BODY)
                d.line([p1, p2], fill=OUT, width=12)
        elif mood in ("surprised", "excited"):
            for (cx, cy), rx, ry in EYES:
                d.arc([cx - rx, cy - ry - 34, cx + rx, cy - ry + 4], 200, 340, fill=OUT, width=10)
        elif mood == "thinking":
            (cx, cy), rx, ry = EYES[0]
            d.line([cx - rx, cy - ry - 8, cx + rx, cy - ry - 20], fill=OUT, width=10)
            (cx, cy), rx, ry = EYES[1]
            d.line([cx - rx, cy - ry - 16, cx + rx, cy - ry - 10], fill=OUT, width=10)

    @staticmethod
    def _star(d, cx, cy, r, fill):
        pts = []
        for k in range(10):
            ang = -math.pi / 2 + k * math.pi / 5
            rr = r if k % 2 == 0 else r * 0.45
            pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
        d.polygon(pts, fill=fill, outline=OUT)

    # ------------------------------------------------------------------ frame
    def _blink(self, t):
        k = np.searchsorted(self.blinks, t)
        d = min(abs(t - self.blinks[max(0, k - 1)]), abs(self.blinks[min(k, len(self.blinks) - 1)] - t))
        return max(0.0, 1 - d / 0.075)                # ~150 ms lid close/open

    def _saccade(self, t):
        k = int(np.searchsorted(self.sacc_t, t))
        a = self.sacc_xy[max(0, k - 1)]; b = self.sacc_xy[min(k, len(self.sacc_xy) - 1)]
        t0 = self.sacc_t[k - 1] if k else 0.0
        e = min(1.0, (t - t0) / 0.12)                 # quick eye jump, then hold
        return a * (1 - e) + b * e if k else b * e

    def _smooth_mouth(self, t, mouth):
        """Natural lip-sync: fast attack, softer release (no jitter)."""
        if self._last_t is None or t < self._last_t or t - self._last_t > 0.5:
            self._mo = mouth
        else:
            k = 0.65 if mouth > self._mo else 0.35
            self._mo += (mouth - self._mo) * k
        self._last_t = t
        return max(0.0, min(1.0, self._mo))

    def _mouth(self, canvas, mo, mood):
        """Cartoon mouth inside the snout: a smile line when closed, a rounded opening (with tongue) that grows
        with the voice. Always clipped to the inside of the head so it can never stick out of the outline."""
        W, H = self.size
        L = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(L)
        x0, x1 = HINGE[0] - 8, TIP[0] - 8
        top = lambda x: mouth_y(x) - 6
        if mo < 0.06:
            if mood in ("angry", "determined"):
                d.line([(x0 + 8, top(x0 + 8)), (x1 - 4, top(x1 - 4))], fill=OUT, width=6)
            else:
                lift = 10 if mood in ("happy", "excited", "star", "happy_closed") else 5
                pts = [(x0 - 4, top(x0) - lift), (x0 + 4, top(x0) - 1)] + \
                      [(x, top(x) + 2 + 3 * math.sin(math.pi * (x - x0) / (x1 - x0))) for x in range(x0 + 10, x1, 6)]
                d.line(pts, fill=OUT, width=6, joint="curve")
        else:
            h = 6 + 22 * mo
            wide = 1.0 if mood in ("excited", "surprised", "star") else 0.9
            xa, xb = x0 + (1 - wide) * 20, x1
            pts = [(x, top(x)) for x in np.linspace(xa, xb, 12)]
            pts += [((xa + xb) / 2 + (xb - xa) / 2 * math.cos(a), top((xa + xb) / 2) + h * math.sin(a))
                    for a in np.linspace(0, math.pi, 14)]
            d.polygon(pts, fill=(92, 20, 38, 255))
            tx, ty = (xa + xb) / 2 + 2, top((xa + xb) / 2) + h * 0.78
            d.ellipse([tx - (xb - xa) * 0.3, ty - h * 0.32, tx + (xb - xa) * 0.3, ty + h * 0.3], fill=(214, 96, 116, 255))
            d.line(pts + [pts[0]], fill=OUT, width=6, joint="curve")
        a = L.getchannel("A")
        L.putalpha(Image.fromarray(np.minimum(np.array(a), np.array(self.inner))))
        canvas.alpha_composite(L, (0, 0))

    def render(self, t, mouth=0.0, mood="neutral", look=(0.4, 0.1), blink=None, bounce=0.0, tilt=0.0, squash=0.0):
        """mouth 0..1 (jaw opening), bounce: vertical offset px, tilt degrees (kept tiny: the face stays upright),
        squash -1..1. Adds natural life on top: irregular blinks, eye saccades, breathing and a talking head-bob."""
        W, H = self.size
        mo = self._smooth_mouth(t, float(mouth))
        if blink is None:
            blink = self._blink(t)
        sx_, sy_ = self._saccade(t)
        look = (max(-1, min(1, look[0] + sx_)), max(-1, min(1, look[1] + sy_)))
        canvas = Image.new("RGBA", (W, H + 60), (0, 0, 0, 0))
        canvas.alpha_composite(self._flame(t), (0, 0))
        canvas.alpha_composite(self.body_im, (0, 0))
        self._mouth(canvas, mo, mood)
        d = ImageDraw.Draw(canvas)
        self._eyes(d, blink, look, mood)
        breath = 0.011 * math.sin(2 * math.pi * t / 3.4)              # slow breathing
        talk = 0.018 * mo                                               # tiny lift while speaking
        sx, sy = 1 + 0.06 * squash - breath * 0.4, 1 - 0.06 * squash + breath + talk
        tilt = max(-1.2, min(1.2, tilt))                                # no more tilted face
        nw, nh = int(canvas.width * sx), int(canvas.height * sy)
        canvas = canvas.resize((nw, nh), Image.BICUBIC)
        if abs(tilt) > 0.05:
            canvas = canvas.rotate(tilt, Image.BICUBIC, expand=False, center=(nw / 2, nh * 0.95))
        sway = 3 * math.sin(t * 0.8)                                     # gentle idle sway
        out = Image.new("RGBA", (W + 80, H + 120), (0, 0, 0, 0))
        out.alpha_composite(canvas, (int((out.width - canvas.width) / 2 + sway),
                                     int(out.height - canvas.height - 10 - bounce - 5 * mo)))
        return out


if __name__ == "__main__":
    m = Mascot()
    frames = [m.render(0.2, 0, "neutral"), m.render(0.5, 0.8, "excited", (0.2, -0.2)),
              m.render(1.0, 0.3, "thinking", (-0.6, -0.5)), m.render(1.5, 1.0, "star"),
              m.render(2.0, 0, "determined", (0.8, 0.5)), m.render(3.1, 0, "neutral")]
    sheet = Image.new("RGBA", (6 * 430, 470), (238, 233, 255, 255))
    for i, f in enumerate(frames):
        sheet.alpha_composite(f.resize((430, int(430 * f.height / f.width))), (i * 430, 0))
    sheet.convert("RGB").save(os.environ.get("OUTP", "/tmp/rig.png"))
