import csv
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, HTTPServer

from mbl import parsers
from mbl.fetch import USER_AGENT, fetch_all
from mbl.sources import Source


SECRET = "s3cr3t-key-value"


class _Handler(BaseHTTPRequestHandler):
    hits: dict = {}
    agents: list = []
    posts: list = []

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
        self._reply(code, body)

    def do_POST(self):
        cls = type(self)
        cls.hits[self.path] = cls.hits.get(self.path, 0) + 1
        length = int(self.headers.get("Content-Length", 0))
        cls.posts.append((self.path, self.headers.get("Auth-Key"),
                          self.headers.get("Content-Type"), self.rfile.read(length)))
        if self.headers.get("Auth-Key") == SECRET:
            body, code = b'{"query_status": "ok", "data": [{"ioc": "3.3.3.3:443", "ioc_type": "ip:port"}]}', 200
        else:
            body, code = b'{"error": "Unauthorized"}', 401
        self._reply(code, body)

    def _reply(self, code, body):
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
        _Handler.posts = []

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

    def api_source(self):
        return Source("tf", self.base + "/api", "threatfox_json", "c2", auth_env="MBL_TEST_KEY",
                      post_body='{"query": "get_iocs", "days": 2}')

    def test_auth_key_sent_in_header_with_post_body(self):
        with mock.patch.dict("os.environ", {"MBL_TEST_KEY": SECRET}):
            r = fetch_all([self.api_source()], timeout=2, retries=0, backoff=0)[0]
        self.assertIsNone(r.error)
        self.assertEqual([str(n) for n in r.networks], ["3.3.3.3/32"])
        self.assertEqual(_Handler.posts, [("/api", SECRET, "application/json",
                                           b'{"query": "get_iocs", "days": 2}')])

    def test_missing_auth_env_skips_source_without_request(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            r = fetch_all([self.api_source()], timeout=2, retries=0, backoff=0)[0]
        self.assertEqual(r.networks, [])
        self.assertIn("MBL_TEST_KEY", r.error)
        self.assertIn("not set", r.error)
        self.assertEqual(_Handler.hits, {})

    def test_empty_auth_env_counts_as_missing(self):
        with mock.patch.dict("os.environ", {"MBL_TEST_KEY": "  "}):
            r = fetch_all([self.api_source()], timeout=2, retries=0, backoff=0)[0]
        self.assertIn("not set", r.error)
        self.assertEqual(_Handler.hits, {})

    def test_rejected_key_never_appears_in_error(self):
        with mock.patch.dict("os.environ", {"MBL_TEST_KEY": "wrong-" + SECRET}):
            r = fetch_all([self.api_source()], timeout=2, retries=2, backoff=0)[0]
        self.assertIn("401", r.error)
        self.assertNotIn(SECRET, r.error)
        self.assertEqual(_Handler.hits["/api"], 1)  # 401 is not retried

    def test_parser_exception_marks_source_failed(self):
        srcs = [Source("bad", self.base + "/ok", "threatfox_csv", "c2"),
                Source("good", self.base + "/ok", "plain", "attack")]
        real_parse = parsers.parse

        def fake_parse(fmt, text):
            if fmt == "threatfox_csv":
                raise csv.Error("field larger than field limit")
            return real_parse(fmt, text)

        with mock.patch("mbl.fetch.parse", side_effect=fake_parse):
            res = fetch_all(srcs, timeout=2, retries=0, backoff=0)
        self.assertEqual([r.source.name for r in res], ["bad", "good"])
        self.assertEqual(res[0].networks, [])
        self.assertEqual(res[0].error, "Error: field larger than field limit")
        self.assertIsNone(res[1].error)
        self.assertEqual(len(res[1].networks), 1)

if __name__ == "__main__":
    unittest.main()
