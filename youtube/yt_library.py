"""Legendary games library for the 'legendary' format.

Only real, well-documented games. Every PGN is checked move by move with python-chess (validate()), and the
narration is never allowed to invent moves: the code replays the PGN and the writer only comments on it.
`keys` are the moments where the video stops and asks the viewer to calculate ("move number + SAN").
Add more games by appending to GAMES (the validator runs on every video, so a typo can never be published).
"""
import io
import chess, chess.pgn

GAMES = [
    {"id": "opera-1858", "white": "Paul Morphy", "black": "Duke Karl of Brunswick and Count Isouard",
     "event": "Paris Opera House", "year": 1858, "nickname": "The Opera Game",
     "pgn": "1.e4 e5 2.Nf3 d6 3.d4 Bg4 4.dxe5 Bxf3 5.Qxf3 dxe5 6.Bc4 Nf6 7.Qb3 Qe7 8.Nc3 c6 9.Bg5 b5 "
            "10.Nxb5 cxb5 11.Bxb5+ Nbd7 12.O-O-O Rd8 13.Rxd7 Rxd7 14.Rd1 Qe6 15.Bxd7+ Nxd7 16.Qb8+ Nxb8 17.Rd8#",
     "keys": ["10.Nxb5", "13.Rxd7", "16.Qb8+"]},
    {"id": "immortal-1851", "white": "Adolf Anderssen", "black": "Lionel Kieseritzky",
     "event": "London (casual game)", "year": 1851, "nickname": "The Immortal Game",
     "pgn": "1.e4 e5 2.f4 exf4 3.Bc4 Qh4+ 4.Kf1 b5 5.Bxb5 Nf6 6.Nf3 Qh6 7.d3 Nh5 8.Nh4 Qg5 9.Nf5 c6 10.g4 Nf6 "
            "11.Rg1 cxb5 12.h4 Qg6 13.h5 Qg5 14.Qf3 Ng8 15.Bxf4 Qf6 16.Nc3 Bc5 17.Nd5 Qxb2 18.Bd6 Bxg1 "
            "19.e5 Qxa1+ 20.Ke2 Na6 21.Nxg7+ Kd8 22.Qf6+ Nxf6 23.Be7#",
     "keys": ["18.Bd6", "21.Nxg7+", "22.Qf6+"]},
    {"id": "evergreen-1852", "white": "Adolf Anderssen", "black": "Jean Dufresne",
     "event": "Berlin (casual game)", "year": 1852, "nickname": "The Evergreen Game",
     "pgn": "1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5 4.b4 Bxb4 5.c3 Ba5 6.d4 exd4 7.O-O d3 8.Qb3 Qf6 9.e5 Qg6 10.Re1 Nge7 "
            "11.Ba3 b5 12.Qxb5 Rb8 13.Qa4 Bb6 14.Nbd2 Bb7 15.Ne4 Qf5 16.Bxd3 Qh5 17.Nf6+ gxf6 18.exf6 Rg8 "
            "19.Rad1 Qxf3 20.Rxe7+ Nxe7 21.Qxd7+ Kxd7 22.Bf5+ Ke8 23.Bd7+ Kf8 24.Bxe7#",
     "keys": ["19.Rad1", "21.Qxd7+", "22.Bf5+"]},
    {"id": "century-1956", "hero": "black", "white": "Donald Byrne", "black": "Bobby Fischer",
     "event": "Rosenwald Memorial, New York", "year": 1956, "nickname": "The Game of the Century",
     "pgn": "1.Nf3 Nf6 2.c4 g6 3.Nc3 Bg7 4.d4 O-O 5.Bf4 d5 6.Qb3 dxc4 7.Qxc4 c6 8.e4 Nbd7 9.Rd1 Nb6 10.Qc5 Bg4 "
            "11.Bg5 Na4 12.Qa3 Nxc3 13.bxc3 Nxe4 14.Bxe7 Qb6 15.Bc4 Nxc3 16.Bc5 Rfe8+ 17.Kf1 Be6 18.Bxb6 Bxc4+ "
            "19.Kg1 Ne2+ 20.Kf1 Nxd4+ 21.Kg1 Ne2+ 22.Kf1 Nc3+ 23.Kg1 axb6 24.Qb4 Ra4 25.Qxb6 Nxd1 26.h3 Rxa2 "
            "27.Kh2 Nxf2 28.Re1 Rxe1 29.Qd8+ Bf8 30.Nxe1 Bd5 31.Nf3 Ne4 32.Qb8 b5 33.h4 h5 34.Ne5 Kg7 35.Kg1 Bc5+ "
            "36.Kf1 Ng3+ 37.Ke1 Bb4+ 38.Kd1 Bb3+ 39.Kc1 Ne2+ 40.Kb1 Nc3+ 41.Kc1 Rc2#",
     "keys": ["11...Na4", "13...Nxe4", "17...Be6", "41...Rc2#"]},
    {"id": "reti-tartakower-1910", "white": "Richard Reti", "black": "Savielly Tartakower",
     "event": "Vienna", "year": 1910, "nickname": "Reti's queen sacrifice",
     "pgn": "1.e4 c6 2.d4 d5 3.Nc3 dxe4 4.Nxe4 Nf6 5.Qd3 e5 6.dxe5 Qa5+ 7.Bd2 Qxe5 8.O-O-O Nxe4 9.Qd8+ Kxd8 "
            "10.Bg5+ Kc7 11.Bd8#",
     "keys": ["9.Qd8+", "10.Bg5+"]},
    {"id": "kasparov-topalov-1999", "white": "Garry Kasparov", "black": "Veselin Topalov",
     "event": "Wijk aan Zee", "year": 1999, "nickname": "Kasparov's Immortal",
     "pgn": "1.e4 d6 2.d4 Nf6 3.Nc3 g6 4.Be3 Bg7 5.Qd2 c6 6.f3 b5 7.Nge2 Nbd7 8.Bh6 Bxh6 9.Qxh6 Bb7 10.a3 e5 "
            "11.O-O-O Qe7 12.Kb1 a6 13.Nc1 O-O-O 14.Nb3 exd4 15.Rxd4 c5 16.Rd1 Nb6 17.g3 Kb8 18.Na5 Ba8 "
            "19.Bh3 d5 20.Qf4+ Ka7 21.Rhe1 d4 22.Nd5 Nbxd5 23.exd5 Qd6 24.Rxd4 cxd4 25.Re7+ Kb6 26.Qxd4+ Kxa5 "
            "27.b4+ Ka4 28.Qc3 Qxd5 29.Ra7 Bb7 30.Rxb7 Qc4 31.Qxf6 Kxa3 32.Qxa6+ Kxb4 33.c3+ Kxc3 34.Qa1+ Kd2 "
            "35.Qb2+ Kd1 36.Bf1 Rd2 37.Rd7 Rxd7 38.Bxc4 bxc4 39.Qxh8 Rd3 40.Qa8 c3 41.Qa4+ Ke1 42.f4 f5 "
            "43.Kc1 Rd2 44.Qa7",
     "keys": ["24.Rxd4", "25.Re7+", "27.b4+"]},
    {"id": "levitsky-marshall-1912", "hero": "black", "white": "Stepan Levitsky", "black": "Frank Marshall",
     "event": "Breslau", "year": 1912, "nickname": "The 'gold coins' game",
     "pgn": "1.d4 e6 2.e4 d5 3.Nc3 c5 4.Nf3 Nc6 5.exd5 exd5 6.Be2 Nf6 7.O-O Be7 8.Bg5 O-O 9.dxc5 Be6 10.Nd4 Bxc5 "
            "11.Nxe6 fxe6 12.Bg4 Qd6 13.Bh3 Rae8 14.Qd2 Bb4 15.Bxf6 Rxf6 16.Rad1 Qc5 17.Qe2 Bxc3 18.bxc3 Qxc3 "
            "19.Rxd5 Nd4 20.Qh5 Ref8 21.Re5 Rh6 22.Qg5 Rxh3 23.Rc5 Qg3",
     "keys": ["19...Nd4", "22...Rxh3", "23...Qg3"]},
    {"id": "rotlewi-rubinstein-1907", "hero": "black", "white": "Georg Rotlewi", "black": "Akiba Rubinstein",
     "event": "Lodz", "year": 1907, "nickname": "Rubinstein's Immortal",
     "pgn": "1.d4 d5 2.Nf3 e6 3.e3 c5 4.c4 Nc6 5.Nc3 Nf6 6.dxc5 Bxc5 7.a3 a6 8.b4 Bd6 9.Bb2 O-O 10.Qd2 Qe7 "
            "11.Bd3 dxc4 12.Bxc4 b5 13.Bd3 Rd8 14.Qe2 Bb7 15.O-O Ne5 16.Nxe5 Bxe5 17.f4 Bc7 18.e4 Rac8 19.e5 Bb6+ "
            "20.Kh1 Ng4 21.Be4 Qh4 22.g3 Rxc3 23.gxh4 Rd2 24.Qxd2 Bxe4+ 25.Qg2 Rh3",
     "keys": ["20...Ng4", "22...Rxc3", "23...Rd2"]},
]


def _parse(g):
    return chess.pgn.read_game(io.StringIO(f'[Result "*"]\n\n{g["pgn"]} *'))


def plies(g):
    """[(label, san, board_before, move)] for the whole game. label like '10.Nxb5' or '11...Na4'.
    Raises ValueError when the PGN contains an illegal or unknown move."""
    game = _parse(g)
    if game is None or game.errors:
        raise ValueError(f"{g['id']}: PGN errors {getattr(game, 'errors', None)}")
    b = game.board(); out = []
    for mv in game.mainline_moves():
        san = b.san(mv)
        num = b.fullmove_number
        label = f"{num}.{san}" if b.turn == chess.WHITE else f"{num}...{san}"
        out.append((label, san, b.copy(), mv))
        b.push(mv)
    if len(out) < 10:
        raise ValueError(f"{g['id']}: too few moves parsed ({len(out)})")
    return out


def validate(g):
    p = plies(g)
    labels = [x[0] for x in p]
    missing = [k for k in g["keys"] if k not in labels]
    if missing:
        raise ValueError(f"{g['id']}: key moments not found {missing}")
    return p


def available(used):
    out = []
    for g in GAMES:
        if g["id"] in used:
            continue
        try:
            validate(g); out.append(g)
        except ValueError as e:
            print("library: skipping", e, flush=True)
    return out


if __name__ == "__main__":
    for g in GAMES:
        p = validate(g)
        print(f"OK {g['id']}: {len(p)} plies, last {p[-1][0]}, keys {g['keys']}")
