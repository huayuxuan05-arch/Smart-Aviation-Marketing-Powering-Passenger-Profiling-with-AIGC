"""模板部署必须不接触本地推理；模型仅显式启用。"""
import os
import unittest
from unittest.mock import patch
import content_generation as content
import local_generation as local


class ContentModeTests(unittest.TestCase):
    def test_upstream_entry_points_cannot_start_model_in_template_mode(self):
        with patch.dict(os.environ, {'AEROLENS_GENERATION_MODE': 'template'}), \
             patch.object(local, 'health', side_effect=AssertionError('model probe')), \
             patch.object(local, 'rpc', side_effect=AssertionError('model request')), \
             patch.object(local.subprocess, 'Popen', side_effect=AssertionError('process')):
            self.assertEqual(local.generate('三亚', '国庆', '景区探索')['generation_mode'], 'template')
            with self.assertRaisesRegex(ValueError, '未接入大模型'):
                local.ensure()
            with self.assertRaisesRegex(ValueError, '未接入大模型'):
                local.explain_trip({})

    def test_default_template_never_calls_model_or_starts_process(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(local, 'ensure', side_effect=AssertionError('model start')), \
             patch.object(local, 'health', side_effect=AssertionError('model probe')), \
             patch.object(local, 'rpc', side_effect=AssertionError('model request')), \
             patch.object(local.subprocess, 'Popen', side_effect=AssertionError('process')):
            self.assertFalse(content.configuration()['model_enabled'])
            result = content.generate('三亚', '国庆', '景区探索')
            self.assertEqual(result['generation_mode'], 'template')
            self.assertIsNone(result['model_alias'])
            self.assertEqual(result['usage'], {})
            self.assertIn('三亚', result['text'])
            self.assertEqual(result['risk_flags'], [])
            svg = local.poster({**result, 'holiday_name': '国庆', 'theme': '景区探索'},
                               {'usual_departure_city': '上海', 'destination': '三亚',
                                'travel_date': '2024-10-01', 'date_basis': '营销假期情景假设'})
            self.assertIn('模板主题与配色', svg)
            self.assertNotIn('AI主题与配色', svg)

    def test_explicit_model_mode_delegates_without_silent_fallback(self):
        with patch.dict(os.environ, {'AEROLENS_GENERATION_MODE': 'local-model'}), \
             patch.object(local, 'generate', return_value={'engine': 'model'}) as generate:
            result = content.generate('成都', '国庆', '攻略准备')
            self.assertEqual(result['generation_mode'], 'local-model')
            generate.assert_called_once_with('成都', '国庆', '攻略准备', '轻松亲切', 1)
        with patch.dict(os.environ, {'AEROLENS_GENERATION_MODE': 'local-model'}), \
             patch.object(local, 'generate', side_effect=ValueError('unavailable')):
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                content.generate('成都', '国庆', '攻略准备')

    def test_unknown_mode_is_rejected(self):
        with patch.dict(os.environ, {'AEROLENS_GENERATION_MODE': 'unknown'}):
            with self.assertRaises(ValueError):
                content.configuration()


if __name__ == '__main__':
    unittest.main()
