"""The install files name exact, tested package versions, and this environment has them."""

import json
import re
import sys
import unittest
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAC_FILE, WINDOWS_FILE = ROOT / "environment.yml", ROOT / "environment-windows.yml"


def read_pins(path):
    """({conda package: version}, {pip package: version}) from an environment file."""
    conda, pip = {}, {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line.startswith("- ") or line.endswith(":"):
            continue
        spec = line[2:].strip()
        if "==" in spec:
            name, ver = spec.split("==", 1)
            pip[name.strip().lower()] = ver.strip()
        elif "=" in spec:
            name, ver = spec.split("=", 1)
            conda[name.strip().lower()] = ver.strip()
        elif re.fullmatch(r"[A-Za-z0-9_.-]+", spec) and spec != "conda-forge":
            conda[spec.lower()] = None          # unpinned: the test below reports it
    return conda, pip


class EnvironmentFileTests(unittest.TestCase):
    def test_every_package_has_an_exact_version(self):
        for path in (MAC_FILE, WINDOWS_FILE):
            conda, pip = read_pins(path)
            unpinned = [n for n, v in {**conda, **pip}.items() if not v]
            self.assertEqual(unpinned, [], f"{path.name} has packages without a version")

    def test_mac_and_windows_files_agree(self):
        mac, _ = read_pins(MAC_FILE)
        win, _ = read_pins(WINDOWS_FILE)
        shared = sorted(set(mac) & set(win))
        self.assertIn("python", shared)
        self.assertEqual({n: mac[n] for n in shared}, {n: win[n] for n in shared})

    def test_this_environment_has_the_pinned_versions(self):
        meta = Path(sys.prefix) / "conda-meta"
        if not meta.is_dir():
            self.skipTest("not running in a conda environment")
        installed = {}
        for f in meta.glob("*.json"):
            info = json.loads(f.read_text(encoding="utf-8"))
            installed[info["name"].lower()] = info["version"]
        conda, pip = read_pins(WINDOWS_FILE if sys.platform == "win32" else MAC_FILE)
        wrong = {n: (v, installed.get(n)) for n, v in conda.items() if installed.get(n) != v}
        for name, ver in pip.items():
            try:
                have = metadata.version(name)
            except metadata.PackageNotFoundError:
                have = None
            if have != ver:
                wrong[name] = (ver, have)
        self.assertEqual(wrong, {}, "package: (pinned, installed) -- run Install_BoomBox to update")


if __name__ == "__main__":
    unittest.main()
