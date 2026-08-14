import json
from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.projects.image_services import process_image
from apps.projects.models import Project, ProjectGalleryImage, ProjectImage
from apps.projects.rendering import build_project_presentation, render_feature_markdown


def image_upload(name='project.png', image_format='PNG', size=(1600, 900)):
    output = BytesIO()
    Image.new('RGB', size, 'white').save(output, format=image_format)
    return SimpleUploadedFile(name, output.getvalue(), content_type=f'image/{image_format.lower()}')


class ProjectRenderingTests(TestCase):
    def project(self, **kwargs):
        values = {
            'category': Project.Category.APPS,
            'title': 'Rendering project',
            'slug': 'rendering-project',
            'summary': 'A rendering summary.',
        }
        values.update(kwargs)
        return Project.objects.create(**values)

    def test_feature_markdown_allows_safe_constructs_and_external_link_attributes(self):
        rendered = render_feature_markdown(
            '# Heading\n\n- **Safe**\n\n'
            '[external](https://example.com) [internal](/projects/) [mail](mailto:user@example.com)\n\n'
            '<script>alert(1)</script>\n\n'
            '[unsafe](javascript:alert(1))\n\n'
            '[network](//evil.example)\n\n'
            '<span onclick="alert(2)">event</span>'
        )

        self.assertIn('<h2>Heading</h2>', rendered)
        self.assertIn('<strong>Safe</strong>', rendered)
        self.assertIn('target="_blank"', rendered)
        self.assertIn('rel="noopener noreferrer"', rendered)
        self.assertNotIn('<script', rendered)
        self.assertNotIn('<span onclick=', rendered)
        self.assertNotIn('href="javascript:', rendered)
        self.assertNotIn('href="//evil.example"', rendered)
        self.assertNotIn('target="_blank"', rendered.split('href="/projects/"', 1)[-1].split('</a>', 1)[0])

    def test_feature_markdown_normalizes_legacy_heading_levels(self):
        rendered = render_feature_markdown(
            '# Legacy title\n\n#### Skipped level\n\n## Section\n\n#### Nested section'
        )

        self.assertIn('<h2>Legacy title</h2>', rendered)
        self.assertIn('<h3>Skipped level</h3>', rendered)
        self.assertIn('<h2>Section</h2>', rendered)
        self.assertIn('<h3>Nested section</h3>', rendered)
        self.assertNotIn('<h1>', rendered)

    def test_presentation_renders_body_as_sanitized_markdown(self):
        project = self.project(
            body="Use `data/tweets.js` and **keep it safe**.\n\n<script>alert(1)</script>",
        )

        presentation = build_project_presentation(project)

        self.assertIn('<code>data/tweets.js</code>', presentation['body_html'])
        self.assertIn('<strong>keep it safe</strong>', presentation['body_html'])
        self.assertNotIn('<script', presentation['body_html'])

    def test_presentation_orders_registry_technologies_and_flags_unavailable_media(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            project = self.project(technology_stack=['docker', 'python'])
            image = ProjectImage.objects.create(
                project=project,
                name='Cover',
                original=image_upload(),
                alt_text='Project cover',
            )
            process_image(image)
            image.refresh_from_db()
            project.cover_image = image
            project.save(update_fields=['cover_image'])
            gallery_item = ProjectGalleryImage.objects.create(
                project=project,
                image=image,
                position=4,
            )

            presentation = build_project_presentation(project, canonical_url='https://example.com/projects/rendering-project/')

            self.assertEqual(
                [technology['label'] for technology in presentation['technologies']],
                ['Python', 'Docker'],
            )
            self.assertEqual(presentation['available_gallery'][0]['position'], gallery_item.position)
            self.assertEqual(presentation['cover']['width'], 1600)
            self.assertIn('480w', presentation['cover']['srcset'])
            self.assertTrue(presentation['cover']['social_url'].startswith('http://example.com/'))

            image.rendition_960.storage.delete(image.rendition_960.name)
            unavailable = build_project_presentation(project)

            self.assertIsNone(unavailable['cover'])
            self.assertTrue(unavailable['cover_unavailable'])
            self.assertEqual(unavailable['available_gallery'], [])
            self.assertEqual(unavailable['unavailable_gallery'][0]['position'], gallery_item.position)
            self.assertNotIn('src="', str(unavailable['unavailable_gallery']))

    def test_responsive_image_descriptors_use_actual_unique_widths(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            project = self.project()
            image = ProjectImage.objects.create(
                project=project,
                name='Small cover',
                original=image_upload(size=(800, 450)),
                alt_text='Small project cover',
            )
            process_image(image)
            image.refresh_from_db()
            project.cover_image = image
            project.save(update_fields=['cover_image'])

            presentation = build_project_presentation(project)
            srcset = presentation['cover']['srcset']

            self.assertIn('480w', srcset)
            self.assertIn('800w', srcset)
            self.assertNotIn('960w', srcset)
            self.assertNotIn('1600w', srcset)
            self.assertEqual(srcset.count(','), 1)

    def test_json_ld_escapes_hostile_editorial_characters(self):
        project = self.project(
            title='<Project & title>',
            summary='</script><script>alert(1)</script> & summary',
        )

        presentation = build_project_presentation(
            project,
            canonical_url='https://example.com/projects/rendering-project/',
        )
        serialized = str(presentation['structured_data_json'])
        payload = json.loads(serialized)

        self.assertNotIn('<script>', serialized)
        self.assertEqual(payload['@graph'][0]['name'], '<Project & title>')
        self.assertEqual(payload['@graph'][0]['description'], '</script><script>alert(1)</script> & summary')
