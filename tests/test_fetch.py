import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from mbl.fetch import USER_AGENT, fetch_all
from mbl.sources import Source


class _Handler(BaseHTTPRequestHandler):
    hits: dict = {}
    agents: list = []

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        cls = type(self)
        cls.hits[self.path] = cls.hits.get(self.path, 0) + 1
        cls.agents.append(self.headers.get("User-Agent"))
        if self.path == "/ok":
            body, code = b"1.1.1.1\n", 200
        elif self.path == "/html":
            body, code = b"<html><body>hello</body></html>", 200
        elif self.path == "/flaky":
            body, code = (b"2.2.2.2\n", 200) if cls.hits[self.path] > 1 else (b"", 500)
        else:
            body, code = b"nope", 404
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class FetchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Handler.hits = {}
        _Handler.agents = []

    def fetch(self, path):
        src = Source("s", self.base + path, "plain", "attack")
        return fetch_all([src], timeout=2, retries=2, backoff=0)[0]

    def test_fetch_ok(self):
        r = self.fetch("/ok")
        self.assertIsNone(r.error)
        self.assertEqual([str(n) for n in r.networks], ["1.1.1.1/32"])

    def test_http_error(self):
        r = self.fetch("/missing")
        self.assertIsNotNone(r.error)
        self.assertEqual(r.networks, [])
        self.assertEqual(_Handler.hits["/missing"], 1)  # 404 is not retried

    def test_zero_valid_entries_is_failure(self):
        r = self.fetch("/html")
        self.assertIn("no valid entries", r.error)
        self.assertEqual(r.networks, [])

    def test_retries_then_succeeds(self):
        r = self.fetch("/flaky")
        self.assertIsNone(r.error)
        self.assertEqual(len(r.networks), 1)
        self.assertEqual(_Handler.hits["/flaky"], 2)

    def test_sends_user_agent(self):
        self.fetch("/ok")
        self.assertEqual(_Handler.agents, [USER_AGENT])

    def test_order_preserved_and_unreachable(self):
        srcs = [Source("a", self.base + "/ok", "plain", "attack"),
                Source("b", "http://127.0.0.1:1/x", "plain", "c2")]
        res = fetch_all(srcs, timeout=2, retries=1, backoff=0)
        self.assertEqual([r.source.name for r in res], ["a", "b"])
        self.assertIsNone(res[0].error)
        self.assertIsNotNone(res[1].error)


if __name__ == "__main__":
    unittest.main()
