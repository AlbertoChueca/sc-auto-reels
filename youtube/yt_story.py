"""Instagram Story that announces a new YouTube video (1080x1920, ~15 s).

Layout: 'NEW VIDEO' header + series tag, the first seconds of the video (cold open, with sound and captions) in the
middle, the title, and a big 'link in bio' call to action with the channel name.
Note: Instagram's API cannot add a clickable link sticker to a Story, so the Story points to the link in bio.
"""
import os, subprocess, sys
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import yt_render as RN                                     # noqa: E402

SW, SH = 1080, 1920
VY = 580                                                   # top of the 16:9 video window
VH = (SW - 120) * 9 // 16


def card(plan, channel, thumb):
    im = RN.background().resize((SW, SH)); d = ImageDraw.Draw(im)
    # header
    RN.chip(d, 60, 120, "NEW VIDEO", 44, bg=RN.ORANGE, fg=(255, 255, 255), bold=RN.F_BLACK)
    d.text((60, 220), plan.get("series_tag", ""), font=RN.fnt(RN.F_BOLD, 34), fill=RN.MUTED)
    RN.text_fit(d, "Can you solve it before the timer?", RN.F_DISP, 58, (60, 280, SW - 60, 520), max_lines=3)
    # video window frame
    d.rounded_rectangle([40, VY - 20, SW - 40, VY + VH + 20], 28, fill=(8, 9, 12))
    # title + thumbnail strip
    y = VY + VH + 70
    y = RN.text_fit(d, plan["title"], RN.F_BLACK, 66, (60, y, SW - 60, y + 260), max_lines=3) + 40
    # call to action: the channel address is the main element (Stories can't carry a clickable link via the API)
    cy = SH - 520
    d.rounded_rectangle([50, cy, SW - 50, cy + 330], 40, fill=RN.ORANGE)
    RN.text_fit(d, "WATCH THE FULL VIDEO ON YOUTUBE", RN.F_BLACK, 44, (90, cy + 34, SW - 90, cy + 92), fill=(255, 255, 255),
                align="center", max_lines=1)
    url = f"youtube.com/{channel}" if channel else "Search StreakChess on YouTube"
    d.rounded_rectangle([90, cy + 120, SW - 90, cy + 250], 26, fill=(255, 255, 255))
    size = 66
    while size > 30 and RN.fnt(RN.F_BLACK, size).getlength(url) > SW - 250:
        size -= 2
    f = RN.fnt(RN.F_BLACK, size)
    d.text((SW / 2 - f.getlength(url) / 2, cy + 185 - size * 0.62), url, font=f, fill=(20, 20, 24))
    RN.text_fit(d, "Link in bio", RN.F_BOLD, 34, (90, cy + 268, SW - 90, cy + 312), fill=(255, 255, 255), align="center",
                max_lines=1)
    lg = RN.logo(300); im.alpha_composite(lg, (SW // 2 - lg.width // 2, SH - 140))
    # punch a transparent hole for the video
    hole = Image.new("L", im.size, 255); ImageDraw.Draw(hole).rectangle([60, VY, SW - 60, VY + VH], fill=0)
    im.putalpha(hole)
    return im


def make(plan, video, out_dir, channel=None, seconds=15):
    png = os.path.join(out_dir, "story_overlay.png")
    card(plan, channel, None).save(png)
    out = os.path.join(out_dir, "story.mp4")
    w = SW - 120
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-loop", "1", "-i", png, "-filter_complex",
                    f"color=c=0x101217:s={SW}x{SH}:d={seconds}[bg];"
                    f"[0:v]trim=0:{seconds},setpts=PTS-STARTPTS,scale={w}:-2[v];"
                    f"[bg][v]overlay=60:{VY}[b];[b][1:v]overlay=0:0:shortest=1,fade=t=out:st={seconds - 0.6}:d=0.6,format=yuv420p[o]",
                    "-map", "[o]", "-map", "0:a?", "-t", str(seconds), "-af", f"afade=t=out:st={seconds - 0.8}:d=0.8",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-r", "30", "-c:a", "aac", "-b:a", "128k",
                    "-ar", "48000", "-ac", "2", "-movflags", "+faststart", out], check=True)
    return out
