import re
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _source_options(text: str) -> list[str]:
    """Options of the dropdown with `id: source`, read without a YAML parser."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if re.match(r"\s*id:\s*source\s*$", ln))
    options: list[str] = []
    in_options = False
    for ln in lines[start + 1 :]:
        if re.match(r"\s*options:\s*$", ln):
            in_options = True
            continue
        if in_options:
            m = re.match(r"\s*-\s*(\S+)\s*$", ln)
            if not m:
                break
            options.append(m.group(1))
    return options


class IssueTemplatesTest(unittest.TestCase):
    def test_false_positive_form_lists_every_source(self):
        text = (ROOT / ".github/ISSUE_TEMPLATE/false_positive.yml").read_text(encoding="utf-8")
        options = _source_options(text)
        data = tomllib.loads((ROOT / "sources.toml").read_text(encoding="utf-8"))
        enabled = [s["name"] for s in data["source"] if s.get("enabled", True)]
        self.assertTrue(enabled)
        self.assertIn("unknown", options)
        missing = [n for n in enabled if n not in options]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
