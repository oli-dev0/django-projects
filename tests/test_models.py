from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.test import TestCase

from apps.projects.models import Project, ProjectGalleryImage, ProjectImage
from apps.projects.technologies import TECHNOLOGY_KEYS


class ProjectModelTests(TestCase):
    def test_category_choices_are_fixed_and_have_no_runtime_default(self):
        self.assertEqual(
            Project.Category.choices,
            [
                ('apps', 'Apps'),
                ('themes', 'Themes'),
                ('publishing', 'Publishing'),
                ('features', 'Features'),
                ('operations', 'Operations'),
            ],
        )
        self.assertIs(Project._meta.get_field('category').default, models.NOT_PROVIDED)

    def test_category_is_required_and_rejects_unknown_values(self):
        for category in Project.Category.values:
            with self.subTest(category=category):
                Project(
                    title=category,
                    slug=f'{category}-project',
                    category=category,
                    summary='Summary',
                ).full_clean()

        for category in ('', 'unknown'):
            with self.subTest(category=category), self.assertRaises(ValidationError):
                Project(
                    title='Invalid category',
                    slug=f'invalid-{category or "empty"}',
                    category=category,
                    summary='Summary',
                ).full_clean()

    def test_project_string_value_is_readable(self):
        project = Project.objects.create(
            category=Project.Category.APPS,
            title='Readable project',
            slug='readable-project',
            summary='Readable project summary',
        )

        self.assertEqual(str(project), 'Readable project')

    def test_project_slug_is_unique(self):
        Project.objects.create(
            category=Project.Category.APPS,
            title='Shared slug',
            slug='shared-slug',
            summary='Shared slug summary',
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Project.objects.create(
                    category=Project.Category.APPS,
                    title='Duplicate slug',
                    slug='shared-slug',
                    summary='Duplicate slug summary',
                )

    def test_technology_stack_is_unique_and_follows_registry_order(self):
        project = Project(
            category=Project.Category.APPS,
            title='Technology project',
            slug='technology-project',
            summary='Technology project summary',
            technology_stack=['docker', 'python', 'docker'],
        )

        project.full_clean()

        self.assertEqual(project.technology_stack, ['python', 'docker'])
        self.assertEqual(
            TECHNOLOGY_KEYS,
            (
                'python',
                'django',
                'flutter',
                'postgresql',
                'docker',
                'html5',
                'css3',
                'javascript',
                'htmx',
                'bash',
                'dart',
                'fast_api',
                'flask',
                'linux',
                'ubuntu',
                'cloudflare',
                'pypi',
                'android_studio',
                'pycharm',
                'sublime',
            ),
        )

    def test_unknown_technology_key_is_rejected(self):
        project = Project(
            category=Project.Category.APPS,
            title='Unknown technology project',
            slug='unknown-technology-project',
            summary='Unknown technology project summary',
            technology_stack=['python', 'unknown'],
        )

        with self.assertRaises(ValidationError):
            project.full_clean()


class ProjectImageModelTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(
            category=Project.Category.APPS,
            title='Project image owner',
            slug='project-image-owner',
            summary='Project image owner summary',
        )
        self.other_project = Project.objects.create(
            category=Project.Category.APPS,
            title='Other project',
            slug='other-project',
            summary='Other project summary',
        )

    def image(self, *, project=None, name='Project image', alt_text='A project image', **kwargs):
        return ProjectImage.objects.create(
            project=project or self.project,
            name=name,
            alt_text=alt_text,
            **kwargs,
        )

    def test_informative_images_require_non_empty_alternative_text(self):
        image = self.image(alt_text='   ')

        with self.assertRaises(ValidationError):
            image.full_clean(exclude=['original'])

    def test_decorative_images_require_empty_alternative_text(self):
        image = self.image(alt_text='Decoration', is_decorative=True)

        with self.assertRaises(ValidationError):
            image.full_clean(exclude=['original'])

    def test_publication_readiness_requires_valid_alternative_text_state(self):
        image = self.image(alt_text='')
        image.has_publication_files = lambda: True

        self.assertFalse(image.is_ready_for_publication())

        image.alt_text = 'An informative description'
        self.assertTrue(image.is_ready_for_publication())

        image.is_decorative = True
        self.assertFalse(image.is_ready_for_publication())

        image.alt_text = ''
        self.assertTrue(image.is_ready_for_publication())

    def test_existing_image_cannot_move_to_another_project(self):
        image = self.image()
        image.project = self.other_project

        with self.assertRaises(ValidationError):
            image.full_clean(exclude=['original'])

    def test_gallery_image_requires_same_project_and_public_ready_image(self):
        image = self.image()
        gallery_item = ProjectGalleryImage(project=self.project, image=image, position=0)

        with self.assertRaises(ValidationError):
            gallery_item.full_clean()

        gallery_item.project = self.other_project
        with self.assertRaises(ValidationError):
            gallery_item.full_clean()

    def test_duplicate_gallery_image_and_position_are_rejected(self):
        first_image = self.image()
        second_image = self.image(name='Second project image')
        first = ProjectGalleryImage.objects.create(project=self.project, image=first_image, position=0)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProjectGalleryImage.objects.create(project=self.project, image=first_image, position=1)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProjectGalleryImage.objects.create(project=self.project, image=second_image, position=first.position)

    def test_cover_deletion_sets_project_relation_to_null(self):
        image = self.image()
        self.project.cover_image = image
        self.project.save(update_fields=['cover_image'])

        image.delete()

        self.project.refresh_from_db()
        self.assertIsNone(self.project.cover_image_id)

    def test_unsaved_project_cannot_use_another_projects_cover_image(self):
        image = self.image()
        project = Project(
            category=Project.Category.APPS,
            title='New project',
            slug='new-project',
            summary='New project summary',
            cover_image=image,
        )

        with self.assertRaisesMessage(
            ValidationError,
            'Choose an image owned by this project.',
        ):
            project.full_clean()

    def test_project_deletion_cascades_to_images_and_gallery_items(self):
        image = self.image()
        ProjectGalleryImage.objects.create(project=self.project, image=image, position=0)

        self.project.delete()

        self.assertFalse(ProjectImage.objects.filter(pk=image.pk).exists())
        self.assertFalse(ProjectGalleryImage.objects.filter(image_id=image.pk).exists())


class ProjectConstraintTests(TestCase):
    def project(self, *, slug, is_published=True, is_featured=False):
        return Project.objects.create(
            category=Project.Category.APPS,
            title=slug,
            slug=slug,
            summary=f'{slug} summary',
            is_published=is_published,
            is_featured=is_featured,
        )

    def test_only_one_project_can_be_featured(self):
        self.project(slug='first-featured', is_featured=True)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.project(slug='second-featured', is_featured=True)

    def test_featured_project_must_be_published(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.project(slug='unpublished-featured', is_published=False, is_featured=True)

    def test_database_rejects_empty_and_unknown_categories(self):
        for category in ('', 'unknown'):
            with self.subTest(category=category), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Project.objects.create(
                        title='Invalid category',
                        slug=f'invalid-{category or "empty"}',
                        category=category,
                        summary='Summary',
                    )

    def test_category_segments_are_reserved_project_slugs(self):
        for slug in Project.Category.values:
            with self.subTest(slug=slug), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    self.project(slug=slug)
