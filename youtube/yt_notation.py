"""Chess notation in the scripts.

Script lines are written for the SCREEN with standard algebraic notation ("After 10.Nxb5! the pin on d7 decides").
The voice gets a spoken version ("After knight takes b5, the pin on d7 decides"), and the caption keeps the notation.
`tokens(text)` gives, for every on-screen word, the spoken words it becomes, so word timings from speech recognition
can be mapped back onto the notation shown in the subtitles.
"""
import re
import chess

PIECE = {"K": "king", "Q": "queen", "R": "rook", "B": "bishop", "N": "knight"}
SAN_CORE = r"(?:O-O-O|O-O|[KQRBN][a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?|[a-h]x[a-h][1-8](?:=[QRBN])?|[a-h][1-8](?:=[QRBN])?)[+#]?"
TOKEN = re.compile(rf"^(?P<pre>[\"'(¡¿]*)(?P<num>\d{{1,3}}\.(?:\.\.)?)?(?P<san>{SAN_CORE})(?P<ann>[!?]{{0,2}})(?P<post>[\"'),.;:!?]*)$")
SAN_FIND = re.compile(rf"(?<![\w-])(?:\d{{1,3}}\.(?:\.\.)?)?({SAN_CORE})(?:[!?]{{0,2}})(?![\w-])")


def is_move_like(core):
    """True for real piece/capture/castle/promotion SAN; plain squares (e4, f7) are ambiguous and return False."""
    return not re.fullmatch(r"[a-h][1-8][+#]?", core)


def spoken_san(core):
    mate, check = core.endswith("#"), core.endswith("+")
    s = core.rstrip("+#")
    if s.startswith("O-O-O"):
        out = "castles long"
    elif s.startswith("O-O"):
        out = "castles"
    else:
        promo = None
        if "=" in s:
            s, promo = s.split("=")
        dest = s[-2:]
        if s[0] in PIECE:
            mid = s[1:-2].replace("x", "")
            out = PIECE[s[0]] + (f" from {mid}" if mid else "") + (" takes " if "x" in s else " ") + dest
        elif "x" in s:
            out = f"{s[0]} takes {dest}"
        else:
            out = dest
        if promo:
            out += f", promoting to a {PIECE[promo]}"
    if mate:
        out += ", checkmate"
    elif check:
        out += ", check"
    return out


def tokens(text):
    """[(display_word, [spoken words])] for a screen line."""
    out = []
    for w in text.split():
        m = TOKEN.match(w)
        if m and (is_move_like(m.group("san")) or m.group("num")):
            sp = spoken_san(m.group("san"))
            post = m.group("post")
            sp = (m.group("pre") + sp + (post if post and post[0] in ",.;:!?" else ",")).split()
            out.append((w, sp))
        else:
            out.append((w, [w]))
    return out


def spoken(text):
    t = " ".join(s for _, sp in tokens(text) for s in sp)
    t = re.sub(r",\s*,", ",", t).replace(" ,", ",")
    return re.sub(r",$", ".", t)


def sans_in(text):
    """SAN moves mentioned in a line (move-like tokens only, without move numbers / annotations)."""
    return [m.group(1) for m in SAN_FIND.finditer(text) if is_move_like(m.group(1)) or re.search(r"\d\.", m.group(0))]


def squares_in(text):
    return sorted(set(re.findall(r"(?<![\w-])([a-h][1-8])(?![\w-])", text)))


def norm(san):
    return san.rstrip("+#!?")


def resolve(fen, san):
    """chess.Move for SAN in this position or None."""
    try:
        return chess.Board(fen).parse_san(norm(san))
    except Exception:
        return None


if __name__ == "__main__":
    for t in ["After 10.Nxb5! cxb5 11.Bxb5+ the pin on d7 decides.", "The f7 square is weak, so Qxf7# ends it.",
              "Black castles with O-O and then 17...Be6!! wins.", "e8=Q+ and it is over."]:
        print(t, "|", spoken(t), "|", sans_in(t), squares_in(t))
