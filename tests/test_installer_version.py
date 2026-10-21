import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "routeros" / "install.rsc"


def _update_body(text):
    """Source block of the stored mbl-update script (from `source={` to the
    matching closing brace)."""
    start = text.index("/system script add name=mbl-update")
    open_at = text.index("source={", start) + len("source=")
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_at + 1:i]
    raise AssertionError("mbl-update source block is not closed")


class InstallerVersionTest(unittest.TestCase):
    def test_installer_version_matches_VERSION(self):
        version = (ROOT / "VERSION").read_text().strip()
        found = re.findall(r'^:local mblScriptVersion "([^"]*)"$',
                           INSTALLER.read_text(), re.MULTILINE)
        self.assertEqual(found, [version])

    def test_installer_has_version_placeholder(self):
        body = _update_body(INSTALLER.read_text())
        self.assertEqual(body.count("@MBL_VERSION@"), 1)

    def test_installer_injects_version_placeholder(self):
        self.assertIn(':set ph "@MBL_VERSION@"', INSTALLER.read_text())

    def test_installer_has_variant_placeholder(self):
        body = _update_body(INSTALLER.read_text())
        self.assertEqual(body.count("@MBL_VARIANT@"), 1)
        self.assertIn(':local variant "@MBL_VARIANT@"', body)

    def test_installer_injects_variant_placeholder(self):
        self.assertIn(':set ph "@MBL_VARIANT@"', INSTALLER.read_text())


if __name__ == "__main__":
    unittest.main()
