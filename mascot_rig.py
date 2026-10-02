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
JAW_Y = 461                                           # mouth line on the muzzle
JAW_X0, JAW_X1 = 548, 690
HINGE = (552, 461)


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
        jaw_mask = (yy > JAW_Y) & (yy < 540) & (xx > JAW_X0) & (xx < JAW_X1) & (body[..., 3] > 0)
        self.jaw = np.where(jaw_mask[..., None], body, 0).astype(np.uint8)
        self.body = np.where(jaw_mask[..., None], 0, body).astype(np.uint8)
        self.yy = yy
        self.xx = xx

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
    def render(self, t, mouth=0.0, mood="neutral", look=(0.4, 0.1), blink=None, bounce=0.0, tilt=0.0, squash=0.0):
        """mouth 0..1 (jaw opening), bounce: vertical offset px, tilt degrees, squash -1..1."""
        W, H = self.size
        if blink is None:  # natural blinking every ~3.2s
            ph = (t % 3.2) / 3.2
            blink = max(0.0, 1 - abs(ph - 0.97) / 0.03) if ph > 0.94 else 0.0
        canvas = Image.new("RGBA", (W, H + 60), (0, 0, 0, 0))
        canvas.alpha_composite(self._flame(t), (0, 0))
        canvas.alpha_composite(Image.fromarray(self.body, "RGBA"), (0, 0))
        canvas.alpha_composite(Image.fromarray(self.jaw, "RGBA"), (0, 0))
        mo = max(0.0, min(1.0, mouth))
        if mo > 0.08:  # open mouth drawn on the muzzle
            md = ImageDraw.Draw(canvas)
            h = 8 + 30 * mo
            x0, x1, ytop = 574, 646, 448
            pts = [(x0, ytop + 2), (x1, ytop + 10)]
            for k in range(13):
                ang = math.pi * k / 12
                pts.append(((x0 + x1) / 2 + (x1 - x0) / 2 * math.cos(ang), ytop + 8 + h * math.sin(ang)))
            md.polygon(pts, fill=(110, 22, 38, 255))
            tw = (x1 - x0) * 0.32
            md.ellipse([(x0 + x1) / 2 - tw, ytop + 6 + h * 0.55, (x0 + x1) / 2 + tw, ytop + 10 + h * 1.0], fill=(245, 120, 140, 255))
            md.line(pts + [pts[0]], fill=OUT, width=7, joint="curve")
        d = ImageDraw.Draw(canvas)
        self._eyes(d, blink, look, mood)
        # squash & stretch around the base
        sx, sy = 1 + 0.06 * squash, 1 - 0.06 * squash
        if squash or tilt:
            nw, nh = int(canvas.width * sx), int(canvas.height * sy)
            canvas = canvas.resize((nw, nh), Image.BICUBIC)
            if tilt:
                canvas = canvas.rotate(tilt, Image.BICUBIC, expand=False, center=(nw / 2, nh * 0.9))
        out = Image.new("RGBA", (W + 80, H + 120), (0, 0, 0, 0))
        out.alpha_composite(canvas, (int((out.width - canvas.width) / 2),
                                     int(out.height - canvas.height - 10 - bounce)))
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
