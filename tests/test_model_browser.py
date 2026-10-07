import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.llm.browser import browse_models


class ModelBrowserTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.model = self.root / 'Qwen model.gguf'
        self.model.touch()
        (self.root / 'notes.txt').touch()
        (self.root / '.hidden').mkdir()
        (self.root / 'MLX').mkdir()

    def test_lists_folders_then_models_with_absolute_paths(self):
        data = browse_models(str(self.root))
        self.assertEqual([entry['name'] for entry in data['entries']], ['MLX', self.model.name])
        self.assertEqual(data['entries'][1]['path'], str(self.model))
        self.assertFalse(data['can_select_directory'])

    def test_open_file_starts_in_parent(self):
        self.assertEqual(browse_models(str(self.model))['path'], str(self.root))

    def test_mlx_folder_is_selectable_only_with_config_and_weights(self):
        folder = self.root / 'MLX'
        (folder / 'config.json').write_text('{}')
        self.assertFalse(browse_models(str(folder))['can_select_directory'])
        (folder / 'model.safetensors').touch()
        self.assertTrue(browse_models(str(folder))['can_select_directory'])

    def test_select_folder_resolves_single_gguf(self):
        data = browse_models(str(self.root))
        self.assertEqual(data['selection_path'], str(self.model))
        (self.root / 'second.gguf').touch()
        self.assertIsNone(browse_models(str(self.root))['selection_path'])

    def test_child_model_can_be_selected_without_entering_folder(self):
        folder = self.root / 'MLX'
        (folder / 'config.json').write_text('{}')
        (folder / 'model.safetensors').touch()
        data = browse_models(str(self.root))
        self.assertEqual(data['entries'][0]['selection_path'], str(folder))

    def test_breadcrumbs_include_root_and_current_folder(self):
        data = browse_models(str(self.root))
        self.assertEqual(data['breadcrumbs'][0]['path'], self.root.anchor)
        self.assertEqual(data['breadcrumbs'][-1]['path'], str(self.root))

    def test_pagination(self):
        page = browse_models(str(self.root), limit=1)
        self.assertEqual(len(page['entries']), 1)
        self.assertEqual(page['next_offset'], 1)
        last = browse_models(str(self.root), offset=1, limit=1)
        self.assertEqual(last['entries'][0]['name'], self.model.name)
        self.assertIsNone(last['next_offset'])

    def test_invalid_paths_and_permissions(self):
        for path in [str(self.root / 'missing'), 'bad\x00path']:
            with self.assertRaises(ValueError):
                browse_models(path)
        with patch('app.llm.browser.Path.iterdir', side_effect=PermissionError), self.assertRaises(PermissionError):
            browse_models(str(self.root))

    def test_default_uses_configured_model_parent(self):
        with patch.dict(os.environ, {'LOCAL_MODEL_PATH': str(self.model)}):
            self.assertEqual(browse_models()['path'], str(self.root))


if __name__ == '__main__':
    unittest.main()
