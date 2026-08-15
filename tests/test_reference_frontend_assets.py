import unittest
from pathlib import Path


REFERENCE_ROOT = Path(__file__).resolve().parents[1] / 'site_frontend'


class ReferenceFrontendAssetTests(unittest.TestCase):
    def test_has_public_templates_and_behavior_assets(self):
        expected_files = (
            '__init__.py',
            'apps.py',
            'templates/site_frontend/base.html',
            'templates/site_frontend/projects/list.html',
            'templates/site_frontend/projects/detail.html',
            'templates/site_frontend/projects/_filters.html',
            'static/site_frontend/css/site.css',
            'static/site_frontend/js/site.js',
            'static/site_frontend/js/project-list.js',
            'static/site_frontend/js/project-detail.js',
        )

        for relative_path in expected_files:
            self.assertTrue(
                (REFERENCE_ROOT / relative_path).is_file(),
                relative_path,
            )

    def test_gallery_assets_include_keyboard_touch_and_mobile_layout_behavior(self):
        detail_script = (
            REFERENCE_ROOT / 'static/site_frontend/js/project-detail.js'
        ).read_text()
        stylesheet = (
            REFERENCE_ROOT / 'static/site_frontend/css/site.css'
        ).read_text()

        for behavior in ('ArrowLeft', 'ArrowRight', 'touchstart', 'touchend'):
            self.assertIn(behavior, detail_script)
        self.assertIn('min-width:32px', stylesheet)
        self.assertIn('padding:2px 6px', stylesheet)
        self.assertIn('font-size:18px', stylesheet)
        self.assertIn('max-height:calc(100vh - 240px)', stylesheet)

    def test_keeps_shared_technology_icon_paths_local(self):
        expected_icons = (
            'static/site_frontend/img/icons/stack/python.svg',
            'static/site_frontend/img/icons/stack/django.svg',
            'static/site_frontend/img/icons/stack/flutter.svg',
            'static/site_frontend/img/icons/stack/postgresql.svg',
            'static/site_frontend/img/icons/stack/docker.svg',
            'static/site_frontend/img/icons/html5.svg',
            'static/site_frontend/img/icons/css3.svg',
            'static/site_frontend/img/icons/javascript.svg',
            'static/site_frontend/img/icons/htmx.svg',
            'static/site_frontend/img/icons/htmx-dark.svg',
            'static/site_frontend/img/icons/sun.svg',
            'static/site_frontend/img/icons/moon.svg',
        )

        for relative_path in expected_icons:
            self.assertTrue(
                (REFERENCE_ROOT / relative_path).is_file(),
                relative_path,
            )
        self.assertFalse((REFERENCE_ROOT / 'static/core').exists())

    def test_stylesheet_uses_relative_namespaced_asset_urls(self):
        stylesheet = (
            REFERENCE_ROOT / 'static/site_frontend/css/site.css'
        ).read_text()

        self.assertNotIn("url('/static/", stylesheet)
        self.assertIn("url('../fonts/", stylesheet)
        self.assertIn("url('../img/icons/", stylesheet)

    def test_enhancement_controls_start_hidden(self):
        base_template = (
            REFERENCE_ROOT / 'templates/site_frontend/base.html'
        ).read_text()
        filters_template = (
            REFERENCE_ROOT / 'templates/site_frontend/projects/_filters.html'
        ).read_text()
        site_script = (
            REFERENCE_ROOT / 'static/site_frontend/js/site.js'
        ).read_text()
        filters_script = (
            REFERENCE_ROOT / 'static/site_frontend/js/project-list.js'
        ).read_text()

        self.assertIn(
            'class="theme-toggle"\n                  type="button"\n                  hidden',
            base_template,
        )
        self.assertEqual(
            filters_template.count('type="button"\n            hidden'),
            1,
        )
        self.assertEqual(
            filters_template.count('type="button"\n                  hidden'),
            2,
        )
        self.assertIn('toggle.hidden = false', site_script)
        self.assertIn('toggle.hidden = false', filters_script)
        self.assertIn('dropdownToggle.hidden = false', filters_script)
