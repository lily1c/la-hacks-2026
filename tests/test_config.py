import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from firesight.config import load_dotenv


class DotenvTests(unittest.TestCase):
    def test_loads_values_without_overriding_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            env.write_text("# comment\nGEMINI_API_KEY='from-file'\nexport OTHER=two\nKEEP=file\n\nbad line\n")
            with patch.dict(os.environ, {"KEEP": "real"}, clear=False):
                os.environ.pop("GEMINI_API_KEY", None)
                os.environ.pop("OTHER", None)
                self.assertEqual(load_dotenv(env), env)
                self.assertEqual(os.environ["GEMINI_API_KEY"], "from-file")
                self.assertEqual(os.environ["OTHER"], "two")
                self.assertEqual(os.environ["KEEP"], "real")
                os.environ.pop("GEMINI_API_KEY"); os.environ.pop("OTHER")

    def test_missing_file_is_fine(self):
        self.assertIsNone(load_dotenv(Path("/nonexistent/.env")))


if __name__ == "__main__":
    unittest.main()
