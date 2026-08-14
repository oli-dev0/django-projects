from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from django.contrib import admin
from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms.models import inlineformset_factory
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_totp.models import TOTPDevice
from PIL import Image

from apps.projects.admin import ProjectAdmin, ProjectImageAdmin
from apps.projects.forms import (
    ProjectAdminForm,
    ProjectGalleryImageAdminForm,
    ProjectGalleryImageFormSet,
    ProjectImageAdminForm,
)
from apps.projects.image_services import process_image
from apps.projects.models import Project, ProjectGalleryImage, ProjectImage
from apps.projects.rendering import FeatureMarkdownRenderError


def image_upload(*, name='source.png', image_format='PNG', size=(1600, 900), color='white'):
    output = BytesIO()
    Image.new('RGB', size, color).save(output, format=image_format)
    return SimpleUploadedFile(name, output.getvalue(), content_type=f'image/{image_format.lower()}')


class ProjectAdminFormTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(
            category=Project.Category.APPS,
            title='Project admin',
            slug='project-admin',
            summary='Project admin summary',
        )
        self.other_project = Project.objects.create(
            category=Project.Category.APPS,
            title='Other project',
            slug='other-project-admin',
            summary='Other project summary',
        )

    def ready_image(self, project, name):
        image = ProjectImage.objects.create(
            project=project,
            name=name,
            original=image_upload(name=f'{name}.png'),
            alt_text=f'{name} alternative text',
        )
        process_image(image)
        image.refresh_from_db()
        return image

    def test_project_add_form_hides_cover_and_admin_hides_gallery_until_save(self):
        form = ProjectAdminForm()
        request = RequestFactory().get('/admin/projects/project/add/')
        request.user = AnonymousUser()
        project_admin = ProjectAdmin(Project, admin.site)

        self.assertNotIn('cover_image', form.fields)
        self.assertNotIn('is_featured', form.fields)
        self.assertEqual(project_admin.get_inline_instances(request, None), [])
        add_fieldsets = project_admin.get_fieldsets(request, None)
        self.assertNotIn(
            'cover_image',
            tuple(field for _, options in add_fieldsets for field in options['fields']),
        )

    def test_project_category_is_required_and_available_in_admin_list_controls(self):
        form = ProjectAdminForm(
            data={
                'title': 'Missing category',
                'slug': 'missing-category',
                'category': '',
                'summary': 'Summary',
            }
        )
        project_admin = ProjectAdmin(Project, admin.site)

        self.assertFalse(form.is_valid())
        self.assertIn('category', form.errors)
        self.assertIn('category', project_admin.list_display)
        self.assertIn('category', project_admin.list_filter)

    @override_settings(MEDIA_ROOT='/tmp/project-admin-form-media')
    def test_project_cover_choices_are_ready_and_owned_by_the_project(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            own_image = self.ready_image(self.project, 'Own image')
            other_image = self.ready_image(self.other_project, 'Other image')
            form = ProjectAdminForm(instance=self.project)

            self.assertEqual(list(form.fields['cover_image'].queryset), [own_image])
            self.assertNotIn(other_image, form.fields['cover_image'].queryset)

    def test_project_form_reports_renderer_failure_on_feature_markdown(self):
        form = ProjectAdminForm(
            data={
                'title': 'Markdown project',
                'slug': 'markdown-project',
                'summary': 'Summary',
                'body': '',
                'seo_title': '',
                'seo_description': '',
                'is_published': '',
                'sort_order': '0',
                'repo_url': '',
                'live_url': '',
                'gallery_caption': '',
                'technology_stack': [],
                'full_feature_list': '## Features',
            }
        )
        with patch(
            'apps.projects.forms.render_feature_markdown',
            side_effect=FeatureMarkdownRenderError,
        ):
            self.assertFalse(form.is_valid())

        self.assertIn('full_feature_list', form.errors)
        self.assertIn('safely rendered', str(form.errors['full_feature_list']))

    def test_project_form_reports_renderer_failure_on_body_markdown(self):
        form = ProjectAdminForm(
            data={
                'title': 'Markdown body project',
                'slug': 'markdown-body-project',
                'summary': 'Summary',
                'body': 'Body',
                'sort_order': '0',
            }
        )
        with patch(
            'apps.projects.forms.render_feature_markdown',
            side_effect=FeatureMarkdownRenderError,
        ):
            self.assertFalse(form.is_valid())

        self.assertIn('body', form.errors)
        self.assertIn('safely rendered', str(form.errors['body']))

    def test_project_form_rejects_level_one_and_skipped_markdown_headings(self):
        cases = (
            ('body', '# Duplicate page title', 'heading level 2 or lower'),
            ('full_feature_list', '## Features\n\n#### Skipped', 'skips a level'),
        )
        for field_name, markdown, message in cases:
            with self.subTest(field_name=field_name):
                data = {
                    'title': 'Markdown headings',
                    'slug': f'markdown-{field_name}',
                    'category': Project.Category.APPS,
                    'summary': 'Summary',
                    'body': '',
                    'seo_title': '',
                    'seo_description': '',
                    'is_published': '',
                    'repo_url': '',
                    'live_url': '',
                    'gallery_caption': '',
                    'technology_stack': [],
                    'full_feature_list': '',
                }
                data[field_name] = markdown

                form = ProjectAdminForm(data=data)

                self.assertFalse(form.is_valid())
                self.assertIn(message, str(form.errors[field_name]))

    def test_gallery_formset_filters_images_and_ignores_submitted_order_values(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            first = self.ready_image(self.project, 'First image')
            second = self.ready_image(self.project, 'Second image')
            FormSet = inlineformset_factory(
                Project,
                ProjectGalleryImage,
                form=ProjectGalleryImageAdminForm,
                formset=ProjectGalleryImageFormSet,
                extra=0,
            )
            formset = FormSet(
                data={
                    'gallery_items-TOTAL_FORMS': '2',
                    'gallery_items-INITIAL_FORMS': '0',
                    'gallery_items-MIN_NUM_FORMS': '0',
                    'gallery_items-MAX_NUM_FORMS': '1000',
                    'gallery_items-0-image': str(first.pk),
                    'gallery_items-0-position': '0',
                    'gallery_items-1-image': str(second.pk),
                    'gallery_items-1-position': '0',
                },
                instance=self.project,
            )

            self.assertEqual(
                list(formset.empty_form.fields['image'].queryset),
                [first, second],
            )
            self.assertTrue(formset.is_valid(), formset.errors)
            self.assertEqual(formset.forms[0].data['gallery_items-0-position'], '0')

    def test_project_image_form_keeps_invalid_upload_for_lifecycle_processing(self):
        form = ProjectImageAdminForm(
            data={
                'project': str(self.project.pk),
                'name': 'Invalid image',
                'alt_text': 'Description',
                'is_decorative': '',
            },
            files={
                'original': SimpleUploadedFile(
                    'not-an-image.png',
                    b'not an image',
                    content_type='image/png',
                )
            },
        )

        self.assertTrue(form.is_valid(), form.errors)


class ProjectGalleryAdminTests(TestCase):
    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.project = Project.objects.create(
            category=Project.Category.APPS,
            title='Gallery admin project',
            slug='gallery-admin-project',
            summary='Gallery admin project summary',
        )
        self.user = get_user_model().objects.create_superuser(
            username='gallery-admin',
            email='gallery-admin@example.com',
            password='test-password',
        )
        self.model_admin = ProjectAdmin(Project, admin.site)

    def ready_image(self, name):
        image = ProjectImage.objects.create(
            project=self.project,
            name=name,
            original=image_upload(name=f'{name}.png'),
            alt_text=f'{name} alternative text',
        )
        process_image(image)
        image.refresh_from_db()
        return image

    def formset(self, data):
        FormSet = inlineformset_factory(
            Project,
            ProjectGalleryImage,
            form=ProjectGalleryImageAdminForm,
            formset=ProjectGalleryImageFormSet,
            extra=0,
        )
        return FormSet(data=data, instance=self.project, prefix='gallery_items')

    def test_save_formset_uses_inline_row_order_and_add_all_appends_missing_ready_images(self):
        first = self.ready_image('First image')
        second = self.ready_image('Second image')
        third = self.ready_image('Third image')
        first_item = ProjectGalleryImage.objects.create(
            project=self.project,
            image=first,
            position=0,
        )

        formset = self.formset({
            'gallery_items-TOTAL_FORMS': '1',
            'gallery_items-INITIAL_FORMS': '1',
            'gallery_items-MIN_NUM_FORMS': '0',
            'gallery_items-MAX_NUM_FORMS': '1000',
            'gallery_items-0-id': str(first_item.pk),
            'gallery_items-0-project': str(self.project.pk),
            'gallery_items-0-image': str(first.pk),
            'gallery_items-0-position': '99',
        })
        self.assertTrue(formset.is_valid(), formset.errors)

        request = RequestFactory().post('/admin/projects/project/change/', {'_gallery_add_all': '1'})
        request.user = self.user
        project_form = ProjectAdminForm(instance=self.project)
        with patch.object(self.model_admin, 'message_user'):
            self.model_admin.save_formset(request, project_form, formset, change=True)

        self.assertEqual(
            list(
                ProjectGalleryImage.objects.filter(project=self.project)
                .order_by('position')
                .values_list('image_id', 'position')
            ),
            [(first.pk, 0), (second.pk, 1), (third.pk, 2)],
        )

    def test_save_formset_reorders_rows_without_requiring_numeric_order_values(self):
        first = self.ready_image('First image')
        second = self.ready_image('Second image')
        first_item = ProjectGalleryImage.objects.create(
            project=self.project,
            image=first,
            position=0,
        )
        second_item = ProjectGalleryImage.objects.create(
            project=self.project,
            image=second,
            position=1,
        )

        formset = self.formset({
            'gallery_items-TOTAL_FORMS': '2',
            'gallery_items-INITIAL_FORMS': '2',
            'gallery_items-MIN_NUM_FORMS': '0',
            'gallery_items-MAX_NUM_FORMS': '1000',
            'gallery_items-0-id': str(first_item.pk),
            'gallery_items-0-project': str(self.project.pk),
            'gallery_items-0-image': str(first.pk),
            'gallery_items-0-position': '1',
            'gallery_items-1-id': str(second_item.pk),
            'gallery_items-1-project': str(self.project.pk),
            'gallery_items-1-image': str(second.pk),
            'gallery_items-1-position': '0',
        })
        self.assertTrue(formset.is_valid(), formset.errors)

        request = RequestFactory().post('/admin/projects/project/change/')
        request.user = self.user
        self.model_admin.save_formset(
            request,
            ProjectAdminForm(instance=self.project),
            formset,
            change=True,
        )

        self.assertEqual(
            list(
                ProjectGalleryImage.objects.filter(project=self.project)
                .order_by('position')
                .values_list('image_id', flat=True)
            ),
            [second.pk, first.pk],
        )

    def test_save_formset_reorders_changed_rows_around_an_unchanged_row(self):
        first = self.ready_image('First image')
        second = self.ready_image('Second image')
        third = self.ready_image('Third image')
        items = [
            ProjectGalleryImage.objects.create(
                project=self.project,
                image=image,
                position=position,
            )
            for position, image in enumerate((first, second, third))
        ]

        formset = self.formset({
            'gallery_items-TOTAL_FORMS': '3',
            'gallery_items-INITIAL_FORMS': '3',
            'gallery_items-MIN_NUM_FORMS': '0',
            'gallery_items-MAX_NUM_FORMS': '1000',
            'gallery_items-0-id': str(items[0].pk),
            'gallery_items-0-project': str(self.project.pk),
            'gallery_items-0-image': str(first.pk),
            'gallery_items-0-position': '0',
            'gallery_items-1-id': str(items[1].pk),
            'gallery_items-1-project': str(self.project.pk),
            'gallery_items-1-image': str(second.pk),
            'gallery_items-1-position': '2',
            'gallery_items-2-id': str(items[2].pk),
            'gallery_items-2-project': str(self.project.pk),
            'gallery_items-2-image': str(third.pk),
            'gallery_items-2-position': '1',
        })
        self.assertTrue(formset.is_valid(), formset.errors)

        request = RequestFactory().post('/admin/projects/project/change/')
        request.user = self.user
        self.model_admin.save_formset(
            request,
            ProjectAdminForm(instance=self.project),
            formset,
            change=True,
        )

        self.assertEqual(
            list(
                ProjectGalleryImage.objects.filter(project=self.project)
                .order_by('position')
                .values_list('image_id', 'position')
            ),
            [(first.pk, 0), (third.pk, 1), (second.pk, 2)],
        )

    def test_save_formset_normalizes_after_delete_before_add_all(self):
        first = self.ready_image('First image')
        second = self.ready_image('Second image')
        third = self.ready_image('Third image')
        fourth = self.ready_image('Fourth image')
        items = [
            ProjectGalleryImage.objects.create(
                project=self.project,
                image=image,
                position=position,
            )
            for position, image in enumerate((first, second, third))
        ]

        formset = self.formset({
            'gallery_items-TOTAL_FORMS': '3',
            'gallery_items-INITIAL_FORMS': '3',
            'gallery_items-MIN_NUM_FORMS': '0',
            'gallery_items-MAX_NUM_FORMS': '1000',
            'gallery_items-0-id': str(items[0].pk),
            'gallery_items-0-project': str(self.project.pk),
            'gallery_items-0-image': str(first.pk),
            'gallery_items-0-position': '0',
            'gallery_items-1-id': str(items[1].pk),
            'gallery_items-1-project': str(self.project.pk),
            'gallery_items-1-image': str(second.pk),
            'gallery_items-1-position': '1',
            'gallery_items-1-DELETE': 'on',
            'gallery_items-2-id': str(items[2].pk),
            'gallery_items-2-project': str(self.project.pk),
            'gallery_items-2-image': str(third.pk),
            'gallery_items-2-position': '2',
        })
        self.assertTrue(formset.is_valid(), formset.errors)

        request = RequestFactory().post(
            '/admin/projects/project/change/',
            {'_gallery_add_all': '1'},
        )
        request.user = self.user
        with patch.object(self.model_admin, 'message_user'):
            self.model_admin.save_formset(
                request,
                ProjectAdminForm(instance=self.project),
                formset,
                change=True,
            )

        self.assertEqual(
            list(
                ProjectGalleryImage.objects.filter(project=self.project)
                .order_by('position')
                .values_list('image_id', 'position')
            ),
            [(first.pk, 0), (third.pk, 1), (fourth.pk, 2), (second.pk, 3)],
        )


class ProjectImageAdminTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(
            category=Project.Category.APPS,
            title='Project image admin',
            slug='project-image-admin',
            summary='Project image admin summary',
            is_published=True,
        )
        self.request_factory = RequestFactory()
        self.model_admin = ProjectImageAdmin(ProjectImage, admin.site)

    def make_user(self, *codenames):
        user = get_user_model().objects.create_user(
            username=f'admin-{get_user_model().objects.count()}',
            password='test-password',
            is_staff=True,
        )
        permissions = Permission.objects.filter(
            content_type__app_label='projects',
            codename__in=codenames,
        )
        user.user_permissions.add(*permissions)
        user.is_verified = lambda: True
        return user

    def ready_image(self, name='Admin image'):
        image = ProjectImage.objects.create(
            project=self.project,
            name=name,
            original=image_upload(name=f'{name}.png'),
            alt_text=f'{name} alternative text',
        )
        process_image(image)
        image.refresh_from_db()
        return image

    def test_changelist_filters_by_project(self):
        self.assertIn('project', self.model_admin.list_filter)

    def test_list_contract_has_text_readiness_usage_renditions_and_bulk_delete_action(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.ready_image()
            self.project.cover_image = image
            self.project.save(update_fields=['cover_image'])
            ProjectGalleryImage.objects.create(project=self.project, image=image, position=0)
            request = self.request_factory.get('/admin/projects/projectimage/')
            request.user = self.make_user('delete_projectimage')

            self.assertIn('delete_selected', self.model_admin.get_actions(request))
            self.assertEqual(self.model_admin.readiness(image), 'Ready')
            self.assertIn('2 use(s)', self.model_admin.usage_summary(image))
            self.assertIn('Social crop', self.model_admin.rendition_summary(image))
            self.assertIn('project-image-admin__thumbnail', str(self.model_admin.thumbnail(image)))

    def test_bulk_delete_detaches_usage_and_deletes_selected_images(self):
        first = self.ready_image('First image')
        second = self.ready_image('Second image')
        self.project.cover_image = first
        self.project.save(update_fields=['cover_image'])
        ProjectGalleryImage.objects.create(project=self.project, image=first, position=0)
        ProjectGalleryImage.objects.create(project=self.project, image=second, position=1)
        request = self.request_factory.post('/admin/projects/projectimage/')
        request.user = self.make_user('delete_projectimage')

        self.model_admin.delete_queryset(
            request,
            ProjectImage.objects.filter(pk__in=[first.pk, second.pk]),
        )

        self.project.refresh_from_db()
        self.assertIsNone(self.project.cover_image_id)
        self.assertFalse(ProjectGalleryImage.objects.filter(project=self.project).exists())
        self.assertFalse(ProjectImage.objects.filter(pk__in=[first.pk, second.pk]).exists())

    def test_changelist_renders_selection_checkboxes_for_delete_users(self):
        self.ready_image()
        request = self.request_factory.get('/admin/projects/projectimage/')
        request.user = self.make_user('view_projectimage', 'delete_projectimage')

        response = self.model_admin.changelist_view(request)
        response.render()

        self.assertContains(response, 'name="_selected_action"')
        self.assertContains(response, 'id="action-toggle"')

    def test_change_page_shows_renditions_and_project_usage(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.ready_image()
            self.project.cover_image = image
            self.project.save(update_fields=['cover_image'])
            request = self.request_factory.get(
                f'/admin/projects/projectimage/{image.pk}/change/'
            )
            request.user = self.make_user('change_projectimage')

            response = self.model_admin.changeform_view(request, str(image.pk))

            self.assertContains(response, 'Generated renditions')
            self.assertContains(response, 'Social crop (120')
            self.assertContains(response, self.project.title)
            self.assertContains(response, 'Published')

    def test_existing_image_upload_can_only_be_changed_through_replacement(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.ready_image()
            request = self.request_factory.get(
                f'/admin/projects/projectimage/{image.pk}/change/'
            )

            readonly_fields = self.model_admin.get_readonly_fields(request, image)
            form_class = self.model_admin.get_form(request, image)

            self.assertIn('original', readonly_fields)
            self.assertNotIn('original', form_class.base_fields)

    def test_delete_confirmation_shows_usage_and_delete_permission_is_independent(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.ready_image()
            self.project.cover_image = image
            self.project.save(update_fields=['cover_image'])
            ProjectGalleryImage.objects.create(project=self.project, image=image, position=0)
            request = self.request_factory.get(
                f'/admin/projects/projectimage/{image.pk}/delete/'
            )
            request.user = self.make_user('delete_projectimage')

            response = self.model_admin.delete_view(request, str(image.pk))

            self.assertContains(response, 'detach every cover and gallery reference')
            self.assertContains(response, self.project.title)

    def test_failed_initial_processing_keeps_a_retryable_failed_record_and_form_error(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            invalid_upload = SimpleUploadedFile(
                'not-an-image.png',
                b'not an image',
                content_type='image/png',
            )
            form = ProjectImageAdminForm(
                data={
                    'project': str(self.project.pk),
                    'name': 'Failed image',
                    'alt_text': 'Failed image description',
                    'is_decorative': '',
                },
                files={'original': invalid_upload},
            )
            self.assertTrue(form.is_valid(), form.errors)
            image = form.save(commit=False)
            request = self.request_factory.post('/admin/projects/projectimage/add/')
            request.user = self.make_user('add_projectimage')

            self.model_admin.save_model(request, image, form, change=False)
            image.refresh_from_db()

            self.assertEqual(image.processing_status, ProjectImage.ProcessingStatus.FAILED)
            self.assertFalse(image.has_publication_files())
            self.assertIn('could not be processed', str(form.errors['original']))

    def test_replace_route_requires_change_permission_and_shows_published_usage(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.ready_image()
            self.project.cover_image = image
            self.project.save(update_fields=['cover_image'])
            request = self.request_factory.get(f'/admin/projects/projectimage/{image.pk}/replace/')
            request.user = self.make_user('view_projectimage')

            with self.assertRaises(PermissionDenied):
                self.model_admin.replace(request, image.pk)

            request.user = self.make_user('change_projectimage')
            response = self.model_admin.replace(request, image.pk)

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, self.project.title)
            self.assertContains(response, 'Published')

    def test_failed_replacement_returns_actionable_error_and_preserves_references(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.ready_image()
            self.project.cover_image = image
            self.project.save(update_fields=['cover_image'])
            ProjectGalleryImage.objects.create(project=self.project, image=image, position=0)
            old_names = [
                getattr(image, field_name).name
                for field_name in (
                    'original',
                    'rendition_480',
                    'rendition_960',
                    'rendition_1600',
                    'social_1200x630',
                )
            ]
            request = self.request_factory.post(
                f'/admin/projects/projectimage/{image.pk}/replace/',
                data={
                    'upload': SimpleUploadedFile(
                        'replacement.png',
                        b'not an image',
                        content_type='image/png',
                    )
                },
            )
            request.user = self.make_user('change_projectimage')

            response = self.model_admin.replace(request, image.pk)
            image.refresh_from_db()

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'could not be processed')
            self.assertEqual(image.processing_status, ProjectImage.ProcessingStatus.READY)
            self.assertEqual(
                [
                    getattr(image, field_name).name
                    for field_name in (
                        'original',
                        'rendition_480',
                        'rendition_960',
                        'rendition_1600',
                        'social_1200x630',
                    )
                ],
                old_names,
            )
            self.assertEqual(Project.objects.get(pk=self.project.pk).cover_image_id, image.pk)
            self.assertTrue(ProjectGalleryImage.objects.filter(image=image).exists())

    def test_confirmed_delete_detaches_cover_and_gallery_before_cleanup(self):
        image = self.ready_image()
        self.project.cover_image = image
        self.project.save(update_fields=['cover_image'])
        ProjectGalleryImage.objects.create(project=self.project, image=image, position=0)
        request = self.request_factory.post(f'/admin/projects/projectimage/{image.pk}/delete/')
        request.user = self.make_user('delete_projectimage')

        self.model_admin.delete_model(request, image)

        self.project.refresh_from_db()
        self.assertIsNone(self.project.cover_image_id)
        self.assertFalse(ProjectGalleryImage.objects.filter(image_id=image.pk).exists())
        self.assertFalse(ProjectImage.objects.filter(pk=image.pk).exists())


class ProjectImageBatchAdminTests(TestCase):
    def setUp(self):
        self.client.defaults['HTTP_HOST'] = 'admin.localhost'
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        media_override.enable()
        self.addCleanup(media_override.disable)

        self.project = Project.objects.create(
            category=Project.Category.APPS,
            title='Batch upload project',
            slug='batch-upload-project',
            summary='Batch upload summary',
        )
        self.admin_user = get_user_model().objects.create_superuser(
            username='batch-admin',
            email='batch-admin@example.com',
            password='test-password',
        )
        self.login_verified(self.admin_user)
        self.add_url = reverse('admin:projects_projectimage_add')
        self.changelist_url = reverse('admin:projects_projectimage_changelist')

    def login_verified(self, user):
        device = TOTPDevice.objects.create(
            user=user,
            name=f'{user.username}-device',
            confirmed=True,
        )
        self.client.force_login(user)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

    def upload_batch(self, *uploads):
        response = self.client.post(
            self.add_url,
            {
                'step': 'upload',
                'project': str(self.project.pk),
                'uploads': list(uploads),
            },
        )
        self.assertEqual(response.status_code, 302)
        return parse_qs(urlparse(response.url).query)['batch'][0], response

    @staticmethod
    def metadata_data(token, rows):
        data = {
            'step': 'metadata',
            'batch_token': token,
            'form-TOTAL_FORMS': str(len(rows)),
            'form-INITIAL_FORMS': str(len(rows)),
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': str(len(rows)),
        }
        for index, row in enumerate(rows):
            data[f'form-{index}-name'] = row['name']
            data[f'form-{index}-alt_text'] = row.get('alt_text', '')
            if row.get('is_decorative'):
                data[f'form-{index}-is_decorative'] = 'on'
        return data

    def test_add_page_only_shows_project_and_multiple_file_upload(self):
        response = self.client.get(self.add_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="project"')
        self.assertContains(response, 'name="uploads"')
        self.assertContains(response, 'multiple')
        self.assertNotContains(response, 'name="name"')
        self.assertNotContains(response, 'name="alt_text"')
        self.assertNotContains(response, 'name="is_decorative"')

        response = self.client.post(
            self.add_url,
            {'step': 'upload', 'project': str(self.project.pk)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This field is required')
        self.assertFalse(ProjectImage.objects.exists())

    def test_multiple_uploads_share_project_and_save_metadata_in_one_pass(self):
        token, _ = self.upload_batch(
            image_upload(name='first-shot.png'),
            image_upload(name='second.photo.png', color='black'),
        )

        images = list(ProjectImage.objects.order_by('pk'))
        self.assertEqual([image.project for image in images], [self.project, self.project])
        self.assertEqual([image.created_by for image in images], [self.admin_user, self.admin_user])
        self.assertEqual([image.name for image in images], ['first-shot', 'second.photo'])
        self.assertFalse(any(image.is_ready_for_publication() for image in images))
        self.assertFalse(ProjectAdminForm(instance=self.project).fields['cover_image'].queryset.exists())
        self.assertEqual(
            LogEntry.objects.filter(
                user=self.admin_user,
                action_flag=ADDITION,
                object_id__in=[str(image.pk) for image in images],
            ).count(),
            2,
        )

        review_response = self.client.get(f'{self.add_url}?batch={token}')
        self.assertContains(review_response, 'form-0-name')
        self.assertContains(review_response, 'form-1-name')
        self.assertContains(review_response, 'project-image-batch__preview')

        response = self.client.post(
            self.add_url,
            self.metadata_data(
                token,
                [
                    {'name': 'First image', 'alt_text': 'The first project image'},
                    {'name': 'Second image', 'is_decorative': True},
                ],
            ),
        )

        self.assertRedirects(response, self.changelist_url, fetch_redirect_response=False)
        images = list(ProjectImage.objects.order_by('pk'))
        self.assertEqual(images[0].name, 'First image')
        self.assertEqual(images[0].alt_text, 'The first project image')
        self.assertFalse(images[0].is_decorative)
        self.assertEqual(images[1].name, 'Second image')
        self.assertEqual(images[1].alt_text, '')
        self.assertTrue(images[1].is_decorative)
        self.assertTrue(all(image.is_ready_for_publication() for image in images))
        self.assertEqual(
            LogEntry.objects.filter(
                user=self.admin_user,
                action_flag=CHANGE,
                object_id__in=[str(image.pk) for image in images],
            ).count(),
            2,
        )
        self.assertEqual(self.client.get(f'{self.add_url}?batch={token}').status_code, 403)

    def test_batch_upload_rejects_more_than_ten_files(self):
        response = self.client.post(
            self.add_url,
            {
                'step': 'upload',
                'project': str(self.project.pk),
                'uploads': [
                    SimpleUploadedFile(
                        f'image-{index}.png',
                        b'not processed because the batch is too large',
                        content_type='image/png',
                    )
                    for index in range(11)
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Select no more than 10 images at a time.')
        self.assertFalse(ProjectImage.objects.exists())

    def test_invalid_file_does_not_discard_successful_upload(self):
        token, _ = self.upload_batch(
            image_upload(name='valid.png'),
            SimpleUploadedFile(
                'invalid.png',
                b'not an image',
                content_type='image/png',
            ),
        )

        images = list(ProjectImage.objects.order_by('pk'))
        self.assertEqual(
            [image.processing_status for image in images],
            [ProjectImage.ProcessingStatus.READY, ProjectImage.ProcessingStatus.FAILED],
        )
        response = self.client.get(f'{self.add_url}?batch={token}')
        self.assertContains(response, '1 image ready')
        self.assertContains(response, '1 image needs replacement')
        self.assertContains(response, 'The image could not be processed')

    def test_invalid_metadata_prevents_all_batch_updates(self):
        token, _ = self.upload_batch(
            image_upload(name='first.png'),
            image_upload(name='second.png', color='black'),
        )

        response = self.client.post(
            self.add_url,
            self.metadata_data(
                token,
                [
                    {'name': 'Changed first', 'alt_text': 'First description'},
                    {'name': 'Changed second'},
                ],
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Describe this image for readers who cannot see it')
        self.assertEqual(
            list(ProjectImage.objects.order_by('pk').values_list('name', flat=True)),
            ['first', 'second'],
        )

    def test_batch_token_is_tamper_resistant_creator_scoped_and_requires_add_permission(self):
        token, _ = self.upload_batch(image_upload(name='private-batch.png'))

        self.assertEqual(
            self.client.get(f'{self.add_url}?batch={token}tampered').status_code,
            403,
        )

        other_user = get_user_model().objects.create_user(
            username='other-batch-admin',
            password='test-password',
            is_staff=True,
        )
        other_user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label='projects',
                codename='add_projectimage',
            )
        )
        self.login_verified(other_user)
        self.assertEqual(self.client.get(f'{self.add_url}?batch={token}').status_code, 403)

        view_only_user = get_user_model().objects.create_user(
            username='batch-viewer',
            password='test-password',
            is_staff=True,
        )
        view_only_user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label='projects',
                codename='view_projectimage',
            )
        )
        self.login_verified(view_only_user)
        self.assertEqual(self.client.get(self.add_url).status_code, 403)


class ProjectReorderAdminTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_superuser(
            username='project-order-admin',
            email='project-order-admin@example.com',
            password='test-password',
        )
        self.login_verified(self.admin_user, 'project-order-admin-device')
        self.model_admin = ProjectAdmin(Project, admin.site)
        self.reorder_url = reverse('admin:projects_project_reorder')
        self.changelist_url = reverse('admin:projects_project_changelist')

    def login_verified(self, user, device_name):
        device = TOTPDevice.objects.create(
            user=user,
            name=device_name,
            confirmed=True,
        )
        self.client.force_login(user)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

    def project(
        self,
        slug,
        *,
        sort_order,
        is_published=True,
        is_featured=False,
    ):
        return Project.objects.create(
            category=Project.Category.APPS,
            title=slug.replace('-', ' ').title(),
            slug=slug,
            summary=f'{slug} summary',
            sort_order=sort_order,
            is_published=is_published,
            is_featured=is_featured,
        )

    def test_changelist_links_to_reorder_for_change_users(self):
        response = self.client.get(self.changelist_url, HTTP_HOST='admin.localhost')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.reorder_url)
        self.assertContains(response, 'Reorder projects')

    def test_reorder_page_includes_every_project_and_clear_status_labels(self):
        draft = self.project('draft-project', sort_order=1, is_published=False)
        published = self.project('published-project', sort_order=2)
        featured = self.project('featured-project', sort_order=3, is_featured=True)

        response = self.client.get(self.reorder_url, HTTP_HOST='admin.localhost')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, draft.title)
        self.assertContains(response, published.title)
        self.assertContains(response, featured.title)
        self.assertContains(response, 'project-reorder-admin__badge--draft', count=1)
        self.assertContains(response, 'project-reorder-admin__badge--published', count=2)
        self.assertContains(response, 'project-reorder-admin__badge--featured', count=1)
        self.assertContains(response, 'projects/js/project-reorder.')
        self.assertContains(response, 'data-project-move="up"', count=3)
        self.assertContains(response, 'data-project-move="down"', count=3)

    def test_view_only_user_cannot_see_or_open_reorder_tool(self):
        viewer = get_user_model().objects.create_user(
            username='project-order-viewer',
            password='test-password',
            is_staff=True,
        )
        viewer.user_permissions.add(
            Permission.objects.get(
                content_type__app_label='projects',
                codename='view_project',
            )
        )
        self.login_verified(viewer, 'project-order-viewer-device')

        changelist = self.client.get(self.changelist_url, HTTP_HOST='admin.localhost')
        reorder = self.client.get(self.reorder_url, HTTP_HOST='admin.localhost')

        self.assertEqual(changelist.status_code, 200)
        self.assertNotContains(changelist, self.reorder_url)
        self.assertEqual(reorder.status_code, 403)

    def test_valid_post_saves_order_and_redirects_with_message(self):
        first = self.project('first-project', sort_order=0)
        second = self.project('second-project', sort_order=1)
        third = self.project('third-project', sort_order=2)

        response = self.client.post(
            self.reorder_url,
            {
                'project_id': [str(third.pk), str(first.pk), str(second.pk)],
                'expected_project_id': [str(first.pk), str(second.pk), str(third.pk)],
            },
            HTTP_HOST='admin.localhost',
            follow=True,
        )

        self.assertRedirects(response, self.reorder_url)
        self.assertContains(response, 'Project order saved.')
        self.assertEqual(
            list(Project.objects.order_by('sort_order').values_list('pk', flat=True)),
            [third.pk, first.pk, second.pk],
        )

    def test_invalid_and_stale_posts_redisplay_authoritative_order_without_writes(self):
        first = self.project('first-project', sort_order=0)
        second = self.project('second-project', sort_order=1)

        invalid = self.client.post(
            self.reorder_url,
            {
                'project_id': [str(first.pk), str(first.pk)],
                'expected_project_id': [str(first.pk), str(second.pk)],
            },
            HTTP_HOST='admin.localhost',
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, 'incomplete or invalid')
        self.assertEqual(
            list(Project.objects.order_by('sort_order').values_list('pk', flat=True)),
            [first.pk, second.pk],
        )

        third = self.project('third-project', sort_order=2)
        stale = self.client.post(
            self.reorder_url,
            {
                'project_id': [str(second.pk), str(first.pk)],
                'expected_project_id': [str(first.pk), str(second.pk)],
            },
            HTTP_HOST='admin.localhost',
        )
        self.assertEqual(stale.status_code, 200)
        self.assertContains(stale, 'Projects changed since this page was loaded.')
        self.assertContains(stale, third.title)
        self.assertEqual(
            list(Project.objects.order_by('sort_order').values_list('pk', flat=True)),
            [first.pk, second.pk, third.pk],
        )

    def test_reorder_post_requires_csrf_token(self):
        project = self.project('csrf-project', sort_order=0)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin_user)
        session = csrf_client.session
        session[DEVICE_ID_SESSION_KEY] = TOTPDevice.objects.get(
            user=self.admin_user,
            name='project-order-admin-device',
        ).persistent_id
        session.save()

        response = csrf_client.post(
            self.reorder_url,
            {
                'project_id': [str(project.pk)],
                'expected_project_id': [str(project.pk)],
            },
            HTTP_HOST='admin.localhost',
        )

        self.assertEqual(response.status_code, 403)

    def test_admin_creation_appends_after_normalizing_legacy_positions(self):
        first = self.project('first-project', sort_order=4)
        second = self.project('second-project', sort_order=9)
        project = Project(
            category=Project.Category.APPS,
            title='New project',
            slug='new-project',
            summary='New project summary',
        )
        request = RequestFactory().post('/admin/projects/project/add/')
        request.user = self.admin_user

        self.model_admin.save_model(request, project, Mock(), change=False)

        self.assertEqual(
            list(Project.objects.order_by('sort_order').values_list('pk', flat=True)),
            [first.pk, second.pk, project.pk],
        )
        self.assertEqual(
            list(Project.objects.order_by('sort_order').values_list('sort_order', flat=True)),
            [0, 1, 2],
        )

    def test_single_and_bulk_deletion_close_order_gaps(self):
        first = self.project('first-project', sort_order=0)
        second = self.project('second-project', sort_order=1)
        third = self.project('third-project', sort_order=2)
        fourth = self.project('fourth-project', sort_order=3)
        request = RequestFactory().post('/admin/projects/project/delete/')
        request.user = self.admin_user

        self.model_admin.delete_model(request, second)
        self.assertEqual(
            list(Project.objects.order_by('sort_order').values_list('pk', flat=True)),
            [first.pk, third.pk, fourth.pk],
        )
        self.assertEqual(
            list(Project.objects.order_by('sort_order').values_list('sort_order', flat=True)),
            [0, 1, 2],
        )

        self.model_admin.delete_queryset(
            request,
            Project.objects.filter(pk__in=(first.pk, third.pk)),
        )
        fourth.refresh_from_db()
        self.assertEqual(fourth.sort_order, 0)

    def test_numeric_order_is_absent_from_form_and_changelist(self):
        self.assertNotIn('sort_order', ProjectAdminForm().fields)
        self.assertNotIn('sort_order', self.model_admin.list_display)


class ProjectFeaturedAdminTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_superuser(
            username='featured-admin',
            email='featured-admin@example.com',
            password='test-password',
        )
        device = TOTPDevice.objects.create(
            user=self.admin_user,
            name='featured-admin-device',
            confirmed=True,
        )
        self.client.force_login(self.admin_user)
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

    def project(self, slug, *, is_published=True, is_featured=False):
        return Project.objects.create(
            category=Project.Category.APPS,
            title=slug.replace('-', ' ').title(),
            slug=slug,
            summary=f'{slug} summary',
            is_published=is_published,
            is_featured=is_featured,
        )

    def feature_url(self, project):
        return reverse('admin:projects_project_feature', args=(project.pk,))

    def unfeature_url(self, project):
        return reverse('admin:projects_project_unfeature', args=(project.pk,))

    def test_get_feature_page_shows_comparison_copy_and_does_not_mutate(self):
        current = self.project('current-project', is_featured=True)
        proposed = self.project('proposed-project')

        response = self.client.get(self.feature_url(proposed), HTTP_HOST='admin.localhost')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Change featured project?')
        self.assertContains(response, 'This will replace the current featured project on the homepage.')
        self.assertContains(response, current.title)
        self.assertContains(response, proposed.title)
        self.assertContains(response, 'No ready cover image.')
        self.assertContains(response, 'Confirm change')
        self.assertContains(response, 'Cancel')
        self.assertTrue(Project.objects.get(pk=current.pk).is_featured)
        self.assertFalse(Project.objects.get(pk=proposed.pk).is_featured)

    def test_feature_page_uses_one_current_project_snapshot(self):
        current = self.project('current-project', is_featured=True)
        competing = self.project('competing-project')
        proposed = self.project('proposed-project')

        with patch.object(
            ProjectAdmin,
            '_current_featured_project',
            side_effect=(current, competing),
        ) as current_feature:
            response = self.client.get(
                self.feature_url(proposed),
                HTTP_HOST='admin.localhost',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(current_feature.call_count, 1)
        self.assertContains(response, current.title)
        self.assertNotContains(response, competing.title)
        self.assertContains(
            response,
            f'name="expected_current_id" value="{current.pk}"',
            html=False,
        )

    def test_feature_and_unfeature_routes_require_change_permission(self):
        project = self.project('permission-project')
        editor = get_user_model().objects.create_user(
            username='feature-viewer',
            password='test-password',
            is_staff=True,
        )
        project_admin = ProjectAdmin(Project, admin.site)
        request = RequestFactory().get('/admin/projects/project/feature/')
        request.user = editor

        with self.assertRaises(PermissionDenied):
            project_admin.feature(request, project.pk)

        request = RequestFactory().post('/admin/projects/project/unfeature/')
        request.user = editor
        with self.assertRaises(PermissionDenied):
            project_admin.unfeature(request, project.pk)

    def test_project_change_tools_expose_only_transition_actions(self):
        proposed = self.project('proposed-project')
        response = self.client.get(
            reverse('admin:projects_project_change', args=(proposed.pk,)),
            HTTP_HOST='admin.localhost',
        )

        self.assertContains(response, 'Preview project')
        self.assertContains(response, 'Feature on homepage')
        self.assertNotContains(response, 'Remove from homepage')
        self.assertNotContains(response, 'id="id_is_featured"', html=False)

        proposed.is_featured = True
        proposed.save(update_fields=['is_featured'])
        response = self.client.get(
            reverse('admin:projects_project_change', args=(proposed.pk,)),
            HTTP_HOST='admin.localhost',
        )

        self.assertContains(response, 'Remove from homepage')
        self.assertContains(response, 'class="project-feature-admin__unfeature"', html=False)
        self.assertNotContains(response, 'Feature on homepage')

    def test_first_feature_post_and_unfeature_are_csrf_protected_state_changes(self):
        proposed = self.project('proposed-project')

        response = self.client.post(
            self.feature_url(proposed),
            {'expected_current_id': ''},
            HTTP_HOST='admin.localhost',
        )

        self.assertEqual(response.status_code, 302)
        proposed.refresh_from_db()
        self.assertTrue(proposed.is_featured)

        response = self.client.get(self.unfeature_url(proposed), HTTP_HOST='admin.localhost')
        self.assertEqual(response.status_code, 405)
        proposed.refresh_from_db()
        self.assertTrue(proposed.is_featured)

        response = self.client.post(
            self.unfeature_url(proposed),
            HTTP_HOST='admin.localhost',
        )
        self.assertEqual(response.status_code, 302)
        proposed.refresh_from_db()
        self.assertFalse(proposed.is_featured)
        self.assertTrue(proposed.is_published)

    def test_feature_post_rejects_missing_csrf_token(self):
        proposed = self.project('proposed-project')
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.admin_user)
        session = csrf_client.session
        session[DEVICE_ID_SESSION_KEY] = TOTPDevice.objects.get(
            user=self.admin_user,
            name='featured-admin-device',
        ).persistent_id
        session.save()

        response = csrf_client.post(
            self.feature_url(proposed),
            {'expected_current_id': ''},
            HTTP_HOST='admin.localhost',
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Project.objects.get(pk=proposed.pk).is_featured)

    def test_stale_feature_post_redisplays_warning_and_new_comparison(self):
        current = self.project('current-project', is_featured=True)
        proposed = self.project('proposed-project')
        page = self.client.get(self.feature_url(proposed), HTTP_HOST='admin.localhost')
        self.assertContains(page, f'name="expected_current_id" value="{current.pk}"', html=False)

        competing = self.project('competing-project')
        current.is_featured = False
        current.save(update_fields=['is_featured'])
        competing.is_featured = True
        competing.save(update_fields=['is_featured'])

        response = self.client.post(
            self.feature_url(proposed),
            {'expected_current_id': current.pk},
            HTTP_HOST='admin.localhost',
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The featured project changed while you were confirming.')
        self.assertContains(response, competing.title)
        self.assertContains(response, proposed.title)
        self.assertFalse(Project.objects.get(pk=proposed.pk).is_featured)
        self.assertEqual(Project.objects.filter(is_featured=True).count(), 1)

    def test_unpublished_feature_redirects_with_actionable_warning(self):
        draft = self.project('draft-project', is_published=False)

        response = self.client.get(
            self.feature_url(draft),
            HTTP_HOST='admin.localhost',
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Publish this project before featuring it on the homepage.')
        draft.refresh_from_db()
        self.assertFalse(draft.is_featured)

    def test_unpublishing_featured_project_clears_featured_state(self):
        project = self.project('featured-project', is_featured=True)
        project_admin = ProjectAdmin(Project, admin.site)
        form = ProjectAdminForm(
            data={
                'title': project.title,
                'slug': project.slug,
                'category': project.category,
                'summary': project.summary,
                'body': project.body,
                'seo_title': project.seo_title,
                'seo_description': project.seo_description,
                'is_published': '',
                'sort_order': project.sort_order,
                'repo_url': project.repo_url,
                'live_url': project.live_url,
                'gallery_caption': project.gallery_caption,
                'technology_stack': [],
                'full_feature_list': project.full_feature_list,
            },
            instance=project,
        )
        self.assertTrue(form.is_valid(), form.errors)
        changed_project = form.save(commit=False)
        request = RequestFactory().post('/admin/projects/project/change/')
        request.user = self.admin_user

        project_admin.save_model(request, changed_project, form, change=True)

        project.refresh_from_db()
        self.assertFalse(project.is_published)
        self.assertFalse(project.is_featured)
