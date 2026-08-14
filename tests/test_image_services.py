from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.projects.image_services import image_state, process_image
from apps.projects.models import Project, ProjectImage


def image_upload(
    *,
    image_format='PNG',
    size=(1600, 900),
    name='source.png',
    mode='RGB',
    color='white',
    orientation=None,
):
    output = BytesIO()
    image = Image.new(mode, size, color)
    save_kwargs = {}
    if orientation is not None:
        exif = image.getexif()
        exif[274] = orientation
        save_kwargs['exif'] = exif.tobytes()
    image.save(output, format=image_format, **save_kwargs)
    return SimpleUploadedFile(name, output.getvalue(), content_type=f'image/{image_format.lower()}')


def animated_webp_upload():
    output = BytesIO()
    first = Image.new('RGB', (20, 20), 'red')
    second = Image.new('RGB', (20, 20), 'blue')
    first.save(output, format='WEBP', save_all=True, append_images=[second], duration=100, loop=0)
    return SimpleUploadedFile('animated.webp', output.getvalue(), content_type='image/webp')


class ProjectImageServiceTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(
            category=Project.Category.APPS,
            title='Project image service',
            slug='project-image-service',
            summary='Project image service summary',
        )

    def create_image(self, upload=None, *, name='Project image'):
        return ProjectImage.objects.create(
            project=self.project,
            name=name,
            original=upload or image_upload(),
            alt_text='A project image',
        )

    def stored_fields(self, image):
        return [getattr(image, field_name) for field_name in (
            'original',
            'rendition_480',
            'rendition_960',
            'rendition_1600',
            'social_1200x630',
        )]

    def test_jpeg_png_and_webp_generate_the_complete_set(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            for image_format, extension in (('JPEG', 'jpg'), ('PNG', 'png'), ('WEBP', 'webp')):
                with self.subTest(image_format=image_format):
                    image = self.create_image(
                        image_upload(
                            image_format=image_format,
                            name=f'source.{extension}',
                        ),
                        name=f'{image_format} image',
                    )

                    process_image(image)
                    image.refresh_from_db()

                    self.assertEqual(image.processing_status, ProjectImage.ProcessingStatus.READY)
                    self.assertEqual((image.width, image.height), (1600, 900))
                    self.assertTrue(image.has_publication_files())
                    self.assertTrue(image.original.name.endswith(f'.{extension}'))
                    for field_name, expected_size in (
                        ('rendition_480', (480, 270)),
                        ('rendition_960', (960, 540)),
                        ('rendition_1600', (1600, 900)),
                    ):
                        with Image.open(getattr(image, field_name).path) as rendition:
                            self.assertEqual(rendition.format, 'WEBP')
                            self.assertEqual(rendition.size, expected_size)
                    with Image.open(image.social_1200x630.path) as social:
                        self.assertEqual(social.format, 'JPEG')
                        self.assertEqual(social.size, (1200, 630))

    def test_processing_applies_exif_orientation_and_does_not_enlarge_display_renditions(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.create_image(
                image_upload(
                    size=(3, 2),
                    name='oriented.jpg',
                    image_format='JPEG',
                    orientation=6,
                )
            )

            process_image(image)
            image.refresh_from_db()

            self.assertEqual((image.width, image.height), (2, 3))
            for field_name in ('rendition_480', 'rendition_960', 'rendition_1600'):
                with Image.open(getattr(image, field_name).path) as rendition:
                    self.assertEqual(rendition.size, (2, 3))

    def test_social_jpeg_flattens_transparency_against_the_site_dark_background(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.create_image(
                image_upload(
                    image_format='PNG',
                    mode='RGBA',
                    color=(255, 0, 0, 0),
                    name='transparent.png',
                )
            )

            process_image(image)
            image.refresh_from_db()

            with Image.open(image.social_1200x630.path) as social:
                self.assertEqual(social.mode, 'RGB')
                self.assertTrue(
                    all(
                        abs(actual - expected) <= 2
                        for actual, expected in zip(social.getpixel((0, 0)), (9, 11, 16))
                    )
                )

    def test_invalid_initial_uploads_remain_failed_and_retryable(self):
        invalid_uploads = (
            SimpleUploadedFile('source.svg', b'<svg></svg>', content_type='image/svg+xml'),
            SimpleUploadedFile('source.png', b'not an image', content_type='image/png'),
            animated_webp_upload(),
        )
        for index, upload in enumerate(invalid_uploads):
            with self.subTest(index=index):
                with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
                    image = self.create_image(upload, name=f'Invalid image {index}')

                    with self.assertRaises(ValidationError):
                        process_image(image)

                    image.refresh_from_db()
                    self.assertEqual(image.processing_status, ProjectImage.ProcessingStatus.FAILED)
                    self.assertEqual(image.processing_error, 'The image could not be processed.')
                    self.assertFalse(image.rendition_480.name)
                    self.assertFalse(image.rendition_960.name)
                    self.assertFalse(image.rendition_1600.name)
                    self.assertFalse(image.social_1200x630.name)
                    self.assertFalse(image.has_publication_files())

    def test_retrying_failed_image_does_not_leave_unreferenced_uploads(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.create_image(
                SimpleUploadedFile('invalid.png', b'not an image', content_type='image/png'),
                name='Retryable image',
            )
            with self.assertRaises(ValidationError):
                process_image(image)
            image.refresh_from_db()
            failed_original_name = image.original.name
            failed_files = {
                path.relative_to(media_root).as_posix()
                for path in Path(media_root).rglob('*')
                if path.is_file()
            }

            with self.assertRaises(ValidationError):
                process_image(
                    image,
                    upload=SimpleUploadedFile(
                        'invalid-retry.png',
                        b'still not an image',
                        content_type='image/png',
                    ),
                )
            image.refresh_from_db()

            self.assertEqual(image.original.name, failed_original_name)
            self.assertEqual(
                {
                    path.relative_to(media_root).as_posix()
                    for path in Path(media_root).rglob('*')
                    if path.is_file()
                },
                failed_files,
            )

            with self.captureOnCommitCallbacks(execute=True):
                process_image(image, upload=image_upload(name='valid-retry.png'))
            image.refresh_from_db()
            referenced_files = {
                field.name
                for field in self.stored_fields(image)
            }
            stored_files = {
                path.relative_to(media_root).as_posix()
                for path in Path(media_root).rglob('*')
                if path.is_file()
            }

            self.assertTrue(image.has_publication_files())
            self.assertEqual(stored_files, referenced_files)
            self.assertNotIn(failed_original_name, stored_files)

    def test_size_and_pixel_limits_are_applied_to_project_uploads(self):
        with TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root,
            PROJECT_IMAGE_MAX_BYTES=10,
        ):
            image = self.create_image(image_upload(), name='Oversized image')

            with self.assertRaises(ValidationError):
                process_image(image)

            image.refresh_from_db()
            self.assertEqual(image.processing_status, ProjectImage.ProcessingStatus.FAILED)

        with TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root,
            PROJECT_IMAGE_MAX_PIXELS=100,
        ):
            image = self.create_image(
                image_upload(size=(20, 20)),
                name='Too many pixels image',
            )

            with self.assertRaises(ValidationError):
                process_image(image)

            image.refresh_from_db()
            self.assertEqual(image.processing_status, ProjectImage.ProcessingStatus.FAILED)

    def test_processing_failure_cleans_staged_outputs_for_initial_image(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.create_image(name='Failed processing image')
            original_name = image.original.name

            with patch('apps.projects.image_services.encode_image_bytes', side_effect=OSError('failed')):
                with self.assertRaises(ValidationError):
                    process_image(image)

            image.refresh_from_db()
            self.assertEqual(image.processing_status, ProjectImage.ProcessingStatus.FAILED)
            self.assertTrue(image.original.storage.exists(original_name))
            self.assertFalse(any(field.name for field in self.stored_fields(image)[1:]))
            self.assertFalse((Path(media_root) / 'projects' / 'renditions').exists())

    def test_failed_replacement_preserves_ready_state_and_files(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.create_image(name='Replaceable image')
            process_image(image)
            image.refresh_from_db()
            old_names = [field.name for field in self.stored_fields(image)]

            with patch('apps.projects.image_services.encode_image_bytes', side_effect=OSError('failed')):
                with self.assertRaises(ValidationError):
                    process_image(image, upload=image_upload(name='replacement.png'))

            image.refresh_from_db()
            self.assertEqual(image.processing_status, ProjectImage.ProcessingStatus.READY)
            self.assertEqual([field.name for field in self.stored_fields(image)], old_names)
            self.assertTrue(all(image.original.storage.exists(name) for name in old_names))

    def test_failed_replacement_restores_database_after_raw_upload_was_saved(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.create_image(name='Saved replacement image')
            process_image(image)
            image.refresh_from_db()
            previous_state = image_state(image)
            old_names = [field.name for field in self.stored_fields(image)]

            image.original = image_upload(name='raw-replacement.png')
            image.save(update_fields=['original'])
            raw_name = image.original.name

            with patch('apps.projects.image_services.encode_image_bytes', side_effect=OSError('failed')):
                with self.assertRaises(ValidationError):
                    process_image(image, previous_state=previous_state)

            image.refresh_from_db()
            self.assertEqual([field.name for field in self.stored_fields(image)], old_names)
            self.assertTrue(all(image.original.storage.exists(name) for name in old_names))
            self.assertFalse(image.original.storage.exists(raw_name))

    def test_successful_replacement_switches_all_fields_before_old_cleanup(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.create_image(name='Replaceable image')
            process_image(image)
            image.refresh_from_db()
            old_names = [field.name for field in self.stored_fields(image)]

            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                process_image(image, upload=image_upload(name='replacement.webp', image_format='WEBP'))
                image.refresh_from_db()
                new_names = [field.name for field in self.stored_fields(image)]
                self.assertNotEqual(new_names, old_names)
                self.assertTrue(all(image.original.storage.exists(name) for name in old_names))

            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
            self.assertTrue(all(image.original.storage.exists(name) for name in new_names))
            self.assertTrue(all(not image.original.storage.exists(name) for name in old_names))

    def test_public_ready_detection_rejects_missing_or_incomplete_storage(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.create_image()
            process_image(image)
            image.refresh_from_db()
            self.assertTrue(image.is_ready_for_publication())

            rendition_name = image.rendition_960.name
            image.rendition_960.storage.delete(rendition_name)
            self.assertFalse(image.is_ready_for_publication())

            image.rendition_960 = ''
            image.save(update_fields=['rendition_960'])
            self.assertFalse(image.is_ready_for_publication())

    def test_direct_deletion_cleans_all_owned_files_after_commit(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.create_image()
            process_image(image)
            image.refresh_from_db()
            stored_fields = self.stored_fields(image)
            stored_names = [field.name for field in stored_fields]

            with self.captureOnCommitCallbacks(execute=True):
                image.delete()

            self.assertFalse(ProjectImage.objects.filter(pk=image.pk).exists())
            self.assertTrue(all(not field.storage.exists(name) for field, name in zip(stored_fields, stored_names)))

    def test_project_cascade_deletion_cleans_project_image_files_after_commit(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.create_image()
            process_image(image)
            image.refresh_from_db()
            stored_fields = self.stored_fields(image)
            stored_names = [field.name for field in stored_fields]

            with self.captureOnCommitCallbacks(execute=True):
                self.project.delete()

            self.assertTrue(all(not field.storage.exists(name) for field, name in zip(stored_fields, stored_names)))

    def test_cleanup_failure_does_not_turn_confirmed_deletion_into_an_error(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            image = self.create_image()
            process_image(image)
            storage = image.original.storage

            with patch.object(storage, 'delete', side_effect=OSError('storage failed')):
                with self.captureOnCommitCallbacks(execute=False) as callbacks:
                    image.delete()
                with self.assertLogs('apps.projects.image_services', level='WARNING') as logs:
                    callbacks[0]()

            self.assertFalse(ProjectImage.objects.filter(pk=image.pk).exists())
            self.assertTrue(logs.output)
            self.assertTrue(all('projects/' not in message for message in logs.output))
