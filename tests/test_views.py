from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.templatetags.static import static
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from PIL import Image

from apps.projects.image_services import process_image
from apps.projects.models import Project, ProjectGalleryImage, ProjectImage


def image_upload():
    output = BytesIO()
    Image.new('RGB', (1600, 900), 'white').save(output, format='PNG')
    return SimpleUploadedFile('project.png', output.getvalue(), content_type='image/png')


class ProjectViewTests(TestCase):
    def create_project(
        self,
        *,
        slug='english-project',
        title='English project',
        category=Project.Category.APPS,
        summary=None,
        body='',
        technology_stack=None,
    ):
        return Project.objects.create(
            category=category,
            is_published=True,
            title=title,
            slug=slug,
            summary=summary if summary is not None else f'{title} summary',
            body=body,
            technology_stack=technology_stack or [],
        )

    def ready_image(self, project):
        image = ProjectImage.objects.create(
            project=project,
            name='Project cover',
            original=image_upload(),
            alt_text='Project cover alternative text',
        )
        process_image(image)
        image.refresh_from_db()
        return image

    def test_project_list_renders_empty_state(self):
        response = self.client.get('/projects/')

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'site_frontend/projects/list.html')
        self.assertTemplateUsed(response, 'site_frontend/base.html')
        self.assertContains(response, 'No published projects yet.')

    def test_project_list_shows_category_labels(self):
        self.create_project(category=Project.Category.OPERATIONS)

        response = self.client.get('/projects/')

        self.assertContains(response, 'project-row__category', html=False)
        self.assertContains(response, 'Operations')

    def test_project_lists_show_technology_icons_with_tooltips(self):
        project = self.create_project()
        project.technology_stack = ['docker', 'python']
        project.save(update_fields=['technology_stack'])

        response = self.client.get('/projects/')

        self.assertContains(response, 'project-row__technologies', html=False)
        self.assertContains(response, 'aria-label="Python"', html=False)
        self.assertContains(response, 'aria-label="Docker"', html=False)
        self.assertContains(response, static('core/img/icons/stack/python.svg'), html=False)
        self.assertContains(response, static('core/img/icons/stack/docker.svg'), html=False)

        category_response = self.client.get('/projects/apps/')
        self.assertContains(category_response, 'aria-label="Python"', html=False)

    def test_all_category_urls_render_category_specific_metadata(self):
        for category, label in Project.Category.choices:
            with self.subTest(category=category):
                response = self.client.get(f'/projects/{category}/')

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'<h1>{label} projects</h1>', html=True)
                self.assertContains(
                    response,
                    f'<link rel="canonical" href="http://example.com/projects/{category}/">',
                    html=True,
                )
                self.assertContains(
                    response,
                    f'<a href="/projects/">projects/</a>{category}/',
                    html=False,
                )
                self.assertContains(response, 'noindex,follow')

    def test_project_categories_remain_english_for_non_english_requests(self):
        self.create_project(category=Project.Category.FEATURES)

        response = self.client.get(
            '/projects/features/',
            HTTP_ACCEPT_LANGUAGE='fr',
        )

        self.assertContains(response, '<h1>Features projects</h1>', html=True)
        self.assertContains(response, 'project-row__category', html=False)
        self.assertContains(response, 'Features')
        self.assertNotContains(response, 'Fonctionnalités')

    def test_category_page_isolates_published_projects_and_preserves_order(self):
        second = self.create_project(slug='second-app', title='Second app')
        second.sort_order = 2
        second.save(update_fields=['sort_order'])
        first = self.create_project(slug='first-app', title='First app')
        first.sort_order = 1
        first.save(update_fields=['sort_order'])
        self.create_project(
            slug='theme-project',
            title='Theme project',
            category=Project.Category.THEMES,
        )
        draft = self.create_project(slug='draft-app', title='Draft app')
        draft.is_published = False
        draft.save(update_fields=['is_published'])

        response = self.client.get('/projects/apps/')

        self.assertEqual(list(response.context['projects']), [first, second])
        self.assertContains(response, 'First app')
        self.assertContains(response, 'Second app')
        self.assertNotContains(response, 'Theme project')
        self.assertNotContains(response, 'Draft app')
        self.assertNotContains(response, 'noindex,follow')

    def test_empty_category_page_has_specific_empty_state(self):
        response = self.client.get('/projects/themes/')

        self.assertContains(response, 'No published themes projects yet.')

    def test_project_lists_render_filter_controls_status_and_page_script(self):
        self.create_project(technology_stack=['python', 'docker'])

        for path in ('/projects/', '/projects/apps/'):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'data-project-filter-root', html=False)
                self.assertContains(response, 'Search projects')
                content = response.content.decode()
                self.assertLess(
                    content.index('data-project-filter-toggle'),
                    content.index('data-project-search-form'),
                )
                self.assertContains(response, 'maxlength="200"', html=False)
                self.assertContains(response, 'name="category"', html=False)
                self.assertContains(response, 'name="tech"', html=False)
                self.assertContains(response, 'Match all selected technologies')
                self.assertNotContains(response, 'Apply filters')
                self.assertNotContains(response, 'data-project-filter-cancel', html=False)
                self.assertContains(response, 'data-project-filter-results', html=False)
                self.assertContains(
                    response,
                    'Filtered projects loaded.'
                    if path.endswith('/apps/')
                    else 'Projects loaded.',
                )
                self.assertContains(response, 'site_frontend/js/project-list', html=False)
                self.assertEqual(response['Content-Language'], 'en')

    def test_category_path_is_selected_and_counted_as_an_active_filter(self):
        self.create_project(category=Project.Category.APPS)

        response = self.client.get('/projects/apps/')

        self.assertContains(response, 'Category: Apps')
        self.assertContains(response, 'value="apps"', html=False)
        self.assertContains(response, 'project-filters__active-count', html=False)
        self.assertContains(response, '>1<', html=False)

    def test_filter_query_state_redirects_to_one_clean_representation(self):
        self.create_project(technology_stack=['python', 'docker'])

        response = self.client.get(
            '/projects/?tech=docker&tech=python&tech=docker&q=  tools  '
            '&unknown=value',
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response['Location'],
            '/projects/?q=tools&tech=python&tech=docker',
        )

        response = self.client.get(
            '/projects/apps/?category=&q=tools&tech=python',
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response['Location'],
            '/projects/?q=tools&tech=python',
        )

        response = self.client.get('/projects/apps/?category=unsupported&q=tools')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/projects/apps/?q=tools')

    def test_clear_and_remove_links_preserve_the_remaining_filter_state(self):
        self.create_project(technology_stack=['python', 'docker'])

        response = self.client.get('/projects/apps/?q=tools&tech=python&tech=docker')

        self.assertContains(response, '>clear</a>', html=False)
        self.assertContains(response, 'href="/projects/apps/?tech=python&amp;tech=docker"', html=False)
        self.assertContains(response, 'href="/projects/apps/?q=tools"', html=False)
        self.assertContains(response, 'href="/projects/?q=tools&amp;tech=python&amp;tech=docker"', html=False)
        self.assertContains(response, 'href="/projects/"', html=False)

    def test_filtered_seo_identity_and_no_match_state_are_not_indexable(self):
        self.create_project(title='Useful project', technology_stack=['python'])

        response = self.client.get('/projects/?q=missing')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No projects match these filters')
        self.assertContains(
            response,
            'Try removing a filter or clear all filters to see more projects.',
        )
        self.assertContains(response, '<meta name="robots" content="noindex,follow">', html=True)
        self.assertEqual(response['X-Robots-Tag'], 'noindex, follow')
        self.assertContains(
            response,
            '<link rel="canonical" href="http://example.com/projects/">',
            html=True,
        )
        self.assertContains(
            response,
            '<meta property="og:url" content="http://example.com/projects/">',
            html=True,
        )
        self.assertContains(response, 'Filtered projects loaded.')

    def test_draft_projects_do_not_affect_filter_options_or_search_results(self):
        self.create_project(
            slug='published-project',
            title='Published project',
            technology_stack=['python'],
        )
        draft = self.create_project(
            slug='draft-project',
            title='Draft project',
            technology_stack=['docker'],
        )
        draft.is_published = False
        draft.save(update_fields=['is_published'])

        response = self.client.get('/projects/')

        self.assertContains(response, 'Python')
        self.assertNotContains(response, 'Docker')
        self.assertNotContains(response, 'Draft project')

        response = self.client.get('/projects/?q=Draft')

        self.assertNotContains(response, 'Draft project')
        self.assertContains(response, 'No projects match these filters')

    def test_project_detail_outputs_page_specific_social_metadata_without_hreflang(self):
        self.create_project()

        response = self.client.get('/projects/english-project/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<meta property="og:title" content="English project | example.com">', html=True)
        self.assertContains(response, '<meta name="twitter:title" content="English project | example.com">', html=True)
        self.assertNotContains(response, 'hreflang=', html=False)

    def test_project_detail_prompt_links_projects_directory_to_project_list(self):
        self.create_project()

        response = self.client.get('/projects/english-project/')

        self.assertContains(response, '<a href="/projects/">projects/</a>', html=True)
        self.assertContains(response, 'english-project.md', html=False)

    def test_project_detail_has_back_to_projects_link_at_bottom(self):
        self.create_project()

        response = self.client.get('/projects/english-project/')

        self.assertContains(
            response,
            '<a href="/projects/"><span aria-hidden="true">←</span> Back to projects</a>',
            html=True,
        )

    def test_unpublished_project_detail_is_not_publicly_visible(self):
        self.create_project(slug='draft-project', title='Draft project')
        project = Project.objects.get(slug='draft-project')
        project.is_published = False
        project.save(update_fields=['is_published'])

        response = self.client.get('/projects/draft-project/')

        self.assertEqual(response.status_code, 404)

    def test_public_detail_uses_shared_presentation_metadata_and_canonical_url(self):
        self.create_project()
        project = Project.objects.get(slug='english-project')
        project.full_feature_list = '# Features\n\n<script>alert(1)</script>'
        project.save(update_fields=['full_feature_list'])

        response = self.client.get('/projects/english-project/')

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<script>alert(1)</script>', html=False)
        self.assertContains(
            response,
            '<link rel="canonical" href="http://example.com/projects/english-project/">',
            html=True,
        )

    def test_public_detail_uses_responsive_cover_and_unavailable_media_fallback(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            project = self.create_project()
            image = self.ready_image(project)
            project.cover_image = image
            project.save(update_fields=['cover_image'])

            response = self.client.get('/projects/english-project/')

            self.assertContains(response, 'srcset=', html=False)
            self.assertContains(response, 'width="1600"', html=False)
            self.assertContains(response, 'height="900"', html=False)
            self.assertContains(response, '<meta property="og:image:width" content="1200">', html=True)

            image.rendition_960.storage.delete(image.rendition_960.name)
            response = self.client.get('/projects/english-project/')

            self.assertContains(response, 'Image unavailable.')
            self.assertNotContains(response, 'srcset=', html=False)

    def test_public_detail_renders_zero_one_and_multiple_available_gallery_states(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            project = self.create_project()
            response = self.client.get('/projects/english-project/')
            self.assertNotContains(response, 'project-gallery', html=False)
            self.assertNotContains(response, 'Open gallery')

            first = self.ready_image(project)
            ProjectGalleryImage.objects.create(project=project, image=first, position=0)
            response = self.client.get('/projects/english-project/')
            self.assertContains(response, 'project-gallery', html=False)
            self.assertContains(response, 'srcset=', html=False)
            self.assertNotContains(response, 'project-gallery__open', html=False)

            second = self.ready_image(project)
            third = self.ready_image(project)
            fourth = self.ready_image(project)
            ProjectGalleryImage.objects.create(project=project, image=second, position=1)
            ProjectGalleryImage.objects.create(project=project, image=third, position=2)
            ProjectGalleryImage.objects.create(project=project, image=fourth, position=3)
            project.gallery_caption = 'One shared gallery caption.'
            project.save(update_fields=['gallery_caption'])

            response = self.client.get('/projects/english-project/')
            self.assertContains(response, 'Open gallery')
            self.assertContains(response, '4 images')
            self.assertContains(response, 'One shared gallery caption.')
            self.assertContains(response, 'Previous image')
            self.assertContains(response, 'Next image')
            self.assertContains(response, '>Close</button>', html=False)
            self.assertContains(response, '←', html=False)
            self.assertContains(response, '→', html=False)
            self.assertEqual(response.content.decode().count('One shared gallery caption.'), 1)
            self.assertContains(response, 'data-gallery-fallback', html=False)
            self.assertNotContains(response, '<noscript>', html=False)
            self.assertContains(response, 'Open image 4 of 4')
            self.assertEqual(response.content.decode().count('loading="lazy"'), 7)

    def test_unavailable_gallery_media_has_no_broken_target(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            project = self.create_project()
            image = self.ready_image(project)
            ProjectGalleryImage.objects.create(project=project, image=image, position=0)
            image.rendition_960.storage.delete(image.rendition_960.name)

            response = self.client.get('/projects/english-project/')

            self.assertContains(response, 'Image unavailable.')
            self.assertNotContains(response, 'data-gallery-trigger', html=False)
            self.assertNotContains(response, 'project-gallery-dialog', html=False)

    def test_public_detail_renders_stack_and_conditional_sanitized_feature_dialog(self):
        project = self.create_project()
        project.technology_stack = ['docker', 'python', 'htmx']
        project.full_feature_list = '# Features\n\n- Safe feature\n- [External link](https://example.com)\n\n<script>alert(1)</script>'
        project.save(update_fields=['technology_stack', 'full_feature_list'])

        response = self.client.get('/projects/english-project/')

        self.assertContains(response, 'Project information')
        self.assertContains(response, 'Category')
        self.assertContains(response, '<a href="/projects/apps/">Apps</a>', html=True)
        self.assertContains(response, 'Built with')
        self.assertContains(response, 'Python')
        self.assertContains(response, 'Docker')
        self.assertContains(response, 'HTMX')
        dark_icon_url = static('core/img/icons/htmx-dark.svg')
        light_icon_url = static('core/img/icons/htmx.svg')
        self.assertContains(response, f'src="{dark_icon_url}"', html=False)
        self.assertContains(response, f'data-theme-dark-src="{dark_icon_url}"', html=False)
        self.assertContains(response, f'data-theme-light-src="{light_icon_url}"', html=False)
        self.assertContains(response, 'View full feature list')
        self.assertContains(response, 'Full feature list')
        self.assertContains(response, '<h2>Features</h2>', html=True)
        self.assertEqual(response.content.decode().count('<h1'), 1)
        self.assertContains(response, '<li>Safe feature</li>', html=True)
        self.assertNotContains(response, '<h1>Features</h1>', html=True)
        self.assertNotContains(response, '<script>alert(1)</script>', html=False)
        self.assertContains(response, 'site_frontend/js/project-detail', html=False)

        project.full_feature_list = ''
        project.technology_stack = []
        project.save(update_fields=['full_feature_list', 'technology_stack'])
        response = self.client.get('/projects/english-project/')
        self.assertNotContains(response, 'View full feature list')
        self.assertContains(response, 'project-information', html=False)
        self.assertNotContains(response, 'project-technologies__list', html=False)

    def test_ready_cover_supplies_social_metadata_and_creative_work_image(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            project = self.create_project()
            image = self.ready_image(project)
            project.cover_image = image
            project.save(update_fields=['cover_image'])

            response = self.client.get('/projects/english-project/')
            social_url = f'http://example.com{image.social_1200x630.url}'

            self.assertContains(response, f'<meta property="og:image" content="{social_url}">', html=True)
            self.assertContains(response, f'<meta name="twitter:image" content="{social_url}">', html=True)
            self.assertContains(response, '<meta property="og:image:type" content="image/jpeg">', html=True)
            self.assertContains(response, f'"image":"{social_url}"', html=False)


class ProjectPreviewViewTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_superuser(
            username='preview-admin',
            email='preview-admin@example.com',
            password='test-password',
        )
        device = TOTPDevice.objects.create(
            user=self.admin_user,
            name='preview-admin-device',
            confirmed=True,
        )
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

    def project(self, **kwargs):
        values = {
            'category': Project.Category.APPS,
            'title': 'Saved draft',
            'slug': 'saved-draft',
            'summary': 'Saved draft summary.',
            'is_published': False,
            'full_feature_list': '# Saved features',
        }
        values.update(kwargs)
        return Project.objects.create(**values)

    def preview_url(self, project):
        return reverse('admin:projects_project_preview', args=(project.pk,))

    def test_preview_renders_saved_state_with_private_noindex_metadata_and_no_analytics(self):
        project = self.project()
        unsaved_title = project.title
        project.title = 'Unsaved title'

        response = self.client.get(self.preview_url(project), HTTP_HOST='admin.localhost')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, unsaved_title)
        self.assertNotContains(response, 'Unsaved title')
        self.assertContains(response, '<meta name="robots" content="noindex, nofollow, noarchive">', html=True)
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow, noarchive')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertContains(
            response,
            '<link rel="canonical" href="http://example.com/projects/saved-draft/">',
            html=True,
        )
        self.assertNotContains(response, 'plausible', html=False)

    def test_preview_requires_view_or_change_permission(self):
        project = self.project()
        viewer = get_user_model().objects.create_user(
            username='preview-viewer',
            password='test-password',
            is_staff=True,
        )
        device = TOTPDevice.objects.create(
            user=viewer,
            name='preview-viewer-device',
            confirmed=True,
        )
        self.client.force_login(viewer)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

        response = self.client.get(self.preview_url(project), HTTP_HOST='admin.localhost')
        self.assertEqual(response.status_code, 403)

        viewer.user_permissions.add(
            Permission.objects.get(codename='view_project', content_type__app_label='projects'),
        )
        response = self.client.get(self.preview_url(project), HTTP_HOST='admin.localhost')
        self.assertEqual(response.status_code, 200)

    def test_preview_is_get_only(self):
        project = self.project()

        response = self.client.post(self.preview_url(project), HTTP_HOST='admin.localhost')

        self.assertEqual(response.status_code, 405)
