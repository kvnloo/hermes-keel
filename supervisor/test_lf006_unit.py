import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parent
TEMPLATE = ROOT / "hermes-keel-lf006-supervisor.service.in"


class LF006UnitTests(unittest.TestCase):
    def render(self, directory: Path) -> Path:
        text = TEMPLATE.read_text()
        replacements = {
            "@PYTHON@": "/usr/bin/python3",
            "@SOURCE@": str(ROOT / "gateway_restart_supervisor.py"),
            "@DB@": str(directory / "kanban.db"),
            "@BOARD@": "test-board",
            "@BOARD_DIR@": str(directory),
        }
        for key, value in replacements.items():
            text = text.replace(key, value)
        output = directory / "hermes-keel-lf006-supervisor.service"
        output.write_text(text)
        return output

    def test_runtime_directory_is_manager_owned_and_hardened(self):
        text = TEMPLATE.read_text()
        self.assertIn("RuntimeDirectory=hermes-keel", text)
        self.assertIn("RuntimeDirectoryMode=0700", text)
        self.assertNotIn("ReadWritePaths=%t/hermes-keel", text)
        self.assertIn("--socket=%t/hermes-keel/lf006.sock", text)

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze unavailable")
    def test_disposable_render_passes_systemd_verification(self):
        with tempfile.TemporaryDirectory() as raw:
            unit = self.render(Path(raw))
            result = subprocess.run(
                ["systemd-analyze", "verify", str(unit)],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "SYSTEMD_UNIT_PATH": str(Path(raw))},
            )
            # A container may not ship the user-manager dependency graph; in
            # that case verify reports only the absent synthetic target while
            # still parsing the rendered unit successfully.
            if result.returncode:
                self.assertEqual(
                    result.stderr.strip(),
                    "hermes-keel-lf006-supervisor.service: Failed to create hermes-keel-lf006-supervisor.service/start: Unit sysinit.target not found.",
                )


if __name__ == "__main__":
    unittest.main()