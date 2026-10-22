"""Probe: what Origin / Sec-Fetch-Site does a browser send on a same-origin form POST
when the page says Referrer-Policy: no-referrer vs same-origin?
Run: uv run python origin_probe.py <policy> ; drives headless Chrome itself.
Throwaway; binds an ephemeral 127.0.0.1 port, closes at exit."""
import http.server, subprocess, sys, threading, urllib.parse

policy = sys.argv[1]
seen = {}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = (b'<form id=f method=post action="/post"><input name=t value=x></form>'
                b'<script>document.getElementById("f").submit()</script>')
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Referrer-Policy", policy)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        self.rfile.read(n)
        seen["origin"] = self.headers.get("Origin")
        seen["sfs"] = self.headers.get("Sec-Fetch-Site")
        seen["referer"] = self.headers.get("Referer")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html>posted</html>")


srv = http.server.HTTPServer(("127.0.0.1", 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
subprocess.run(
    ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--headless=new",
     "--disable-gpu", "--no-first-run", "--user-data-dir=/tmp/p5-origin-probe-profile",
     "--virtual-time-budget=4000", "--dump-dom", f"http://127.0.0.1:{port}/"],
    capture_output=True, timeout=60,
)
print(policy, "->", seen, "port", port)
srv.shutdown()
