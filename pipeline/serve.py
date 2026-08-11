"""Dev server for the visualizer with caching disabled, so data updates
(regraded prompts, new flags) always show after a plain refresh.

Usage: python pipeline/serve.py [port]   (default 8471)
"""
import http.server
import os
import sys

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8471


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Expires", "0")
        super().end_headers()


http.server.ThreadingHTTPServer(("", PORT), NoCacheHandler).serve_forever()
