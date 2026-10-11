"""Run ONCE on your own computer to get YT_REFRESH_TOKEN for the GitHub secrets.

    python yt_auth.py CLIENT_ID CLIENT_SECRET

It opens Google's consent page in your browser; log in with the account that owns the StreakChess channel
(choose the channel/brand account if asked). The refresh token is printed at the end.
Needs only the Python standard library + requests.
"""
import http.server, sys, urllib.parse, webbrowser
import requests

SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube " \
         "https://www.googleapis.com/auth/yt-analytics.readonly"
PORT = 8765
code = {}


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code["c"] = (q.get("code") or [None])[0]
        self.send_response(200); self.end_headers()
        self.wfile.write("Listo. Ya puedes cerrar esta ventana.".encode())

    def log_message(self, *a):
        pass


def main(cid, secret):
    redirect = f"http://127.0.0.1:{PORT}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent"})
    srv = http.server.HTTPServer(("127.0.0.1", PORT), H)
    print("Abriendo el navegador... si no se abre, copia este enlace:\n", url)
    webbrowser.open(url)
    while not code.get("c"):
        srv.handle_request()
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code["c"], "client_id": cid, "client_secret": secret, "redirect_uri": redirect, "grant_type": "authorization_code"})
    j = r.json()
    if "refresh_token" not in j:
        sys.exit(f"Error: {j}")
    print("\nYT_REFRESH_TOKEN =", j["refresh_token"])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
