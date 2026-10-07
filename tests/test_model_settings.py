import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.llm.settings import save_model_settings


class ModelSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.env = self.root / '.env'
        self.model = self.root / "model #1's.gguf"
        self.model.touch()
        self.patch = patch.dict(os.environ, {}, clear=False)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_save_preserves_other_settings_and_replaces_existing(self):
        self.env.write_text('OTHER=value\nexport LOCAL_MODEL_PATH = old\nLOCAL_MODEL_TYPE=qwen')
        save_model_settings(str(self.model), 'gemma', self.env)
        content = self.env.read_text()
        self.assertIn('OTHER=value', content)
        self.assertEqual(content.count('LOCAL_MODEL_PATH='), 1)
        self.assertIn("LOCAL_MODEL_TYPE='gemma'", content)
        self.assertEqual(os.environ['LOCAL_MODEL_PATH'], str(self.model))

    def test_invalid_path_or_type_does_not_modify_settings(self):
        self.env.write_text('OTHER=value\n')
        before = dict(os.environ)
        for path, kind in [(str(self.root / 'missing'), 'qwen'), (str(self.model), 'bad'), ('x\nOTHER=bad', 'qwen'), (None, 'qwen'), (str(self.root), 'qwen')]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                save_model_settings(path, kind, self.env)
        self.assertEqual(self.env.read_text(), 'OTHER=value\n')
        self.assertEqual(dict(os.environ), before)

    def test_write_failure_preserves_runtime_and_file(self):
        self.env.write_text('OTHER=value\n')
        before = dict(os.environ)
        with patch('app.llm.settings.os.replace', side_effect=PermissionError), self.assertRaises(OSError):
            save_model_settings(str(self.model), 'qwen', self.env)
        self.assertEqual(dict(os.environ), before)
        self.assertEqual(self.env.read_text(), 'OTHER=value\n')
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_mlx_directory_and_home_expansion(self):
        (self.root / 'config.json').write_text('{}')
        (self.root / 'model.safetensors').touch()
        with patch('app.llm.settings.Path.expanduser', return_value=self.root):
            result = save_model_settings('~/model', 'qwen', self.env)
        self.assertEqual(result['LOCAL_MODEL_PATH'], str(self.root))


if __name__ == '__main__':
    unittest.main()
