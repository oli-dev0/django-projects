import logging
from io import BytesIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from PIL import Image, ImageOps

from apps.core.image_processing import (
    encode_image_bytes,
    normalize_image,
    resize_to_max_width,
    validate_image_bytes as validate_shared_image_bytes,
)

from .models import ProjectImage


logger = logging.getLogger(__name__)

DISPLAY_RENDITION_WIDTHS = (480, 960, 1600)
SOCIAL_SIZE = (1200, 630)
SOCIAL_BACKGROUND = (9, 11, 16)
IMAGE_FILE_FIELDS = (
    'original',
    'rendition_480',
    'rendition_960',
    'rendition_1600',
    'social_1200x630',
)
PROCESSING_ERROR = _('The image could not be processed.')


def _limits():
    return (
        getattr(settings, 'PROJECT_IMAGE_MAX_BYTES', 15 * 1024 * 1024),
        getattr(settings, 'PROJECT_IMAGE_MAX_PIXELS', 40_000_000),
    )


def validate_image_bytes(uploaded_file):
    max_bytes, max_pixels = _limits()
    validate_shared_image_bytes(
        uploaded_file,
        max_bytes=max_bytes,
        max_pixels=max_pixels,
        size_message=_('Images must be 15 MB or smaller.'),
        format_message=_('Use a JPEG, PNG, or WebP image.'),
        animation_message=_('Animated images are not supported.'),
        pixel_message=_('Images must contain 40 megapixels or fewer.'),
        invalid_message=_('The uploaded file is not a valid image.'),
    )


def _is_field_file(upload):
    return hasattr(upload, 'storage') and hasattr(upload, 'open')


def _read_source(upload):
    if not upload:
        raise ValidationError({'original': _('Choose an image to process.')})

    if _is_field_file(upload):
        with upload:
            validate_image_bytes(upload.file)
            upload.open('rb')
            return upload.read()

    validate_image_bytes(upload)
    upload.seek(0)
    return upload.read()


def _flatten_transparency(image):
    if image.mode == 'RGB':
        return image.copy()

    background = Image.new('RGB', image.size, SOCIAL_BACKGROUND)
    if 'A' in image.getbands():
        background.paste(image, mask=image.getchannel('A'))
    else:
        background.paste(image.convert('RGB'))
    return background


def _prepare_outputs(upload):
    source_bytes = _read_source(upload)
    with Image.open(BytesIO(source_bytes)) as source:
        source_format = source.format
        normalized = normalize_image(
            source,
            source_format=source_format,
            normalize_mode=True,
        )
        try:
            extension = {
                'JPEG': '.jpg',
                'PNG': '.png',
                'WEBP': '.webp',
            }[source_format]
            outputs = {
                'original': (
                    f'original{extension}',
                    encode_image_bytes(normalized, image_format=source_format),
                ),
            }

            for width in DISPLAY_RENDITION_WIDTHS:
                rendition = resize_to_max_width(normalized, width)
                try:
                    outputs[f'rendition_{width}'] = (
                        f'rendition_{width}.webp',
                        encode_image_bytes(rendition, image_format='WEBP'),
                    )
                finally:
                    rendition.close()

            social = ImageOps.fit(
                normalized,
                SOCIAL_SIZE,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            try:
                social_rgb = _flatten_transparency(social)
                try:
                    outputs['social_1200x630'] = (
                        'social_1200x630.jpg',
                        encode_image_bytes(social_rgb, image_format='JPEG'),
                    )
                finally:
                    social_rgb.close()
            finally:
                social.close()

            return outputs, normalized.size
        finally:
            normalized.close()


def _snapshot_state(image):
    return {
        'files': {
            field_name: getattr(image, field_name).name
            for field_name in IMAGE_FILE_FIELDS
        },
        'file_refs': tuple(
            (getattr(image, field_name).storage, getattr(image, field_name).name)
            for field_name in IMAGE_FILE_FIELDS
            if getattr(image, field_name).name
        ),
        'width': image.width,
        'height': image.height,
        'processing_status': image.processing_status,
        'processing_error': image.processing_error,
    }


def image_state(image):
    """Return lifecycle fields for callers that need to restore a replacement."""
    return _snapshot_state(image)


def _restore_state(image, state):
    for field_name, value in state['files'].items():
        setattr(image, field_name, value)
    image.width = state['width']
    image.height = state['height']
    image.processing_status = state['processing_status']
    image.processing_error = state['processing_error']


def _reference_key(storage, name):
    return id(storage), name


def _unique_references(references):
    result = []
    seen = set()
    for storage, name in references:
        if not name:
            continue
        key = _reference_key(storage, name)
        if key not in seen:
            seen.add(key)
            result.append((storage, name))
    return result


def _delete_references(references, *, object_id, reason):
    for storage, name in _unique_references(references):
        try:
            storage.delete(name)
        except Exception as error:  # Storage cleanup must not undo a DB commit.
            logger.warning(
                'Project image %s cleanup failed for image %s: %s',
                reason,
                object_id,
                error.__class__.__name__,
            )


def schedule_file_cleanup(references, *, object_id, reason='deletion'):
    references = tuple(_unique_references(references))
    if references:
        transaction.on_commit(
            lambda: _delete_references(
                references,
                object_id=object_id,
                reason=reason,
            )
        )


def schedule_image_file_cleanup(image):
    state = _snapshot_state(image)
    schedule_file_cleanup(state['file_refs'], object_id=image.pk)


def _current_file_references(image):
    return tuple(
        (getattr(image, field_name).storage, getattr(image, field_name).name)
        for field_name in IMAGE_FILE_FIELDS
        if getattr(image, field_name).name
    )


def _references_not_in(references, excluded):
    excluded_keys = {_reference_key(storage, name) for storage, name in excluded}
    return tuple(
        (storage, name)
        for storage, name in _unique_references(references)
        if _reference_key(storage, name) not in excluded_keys
    )


def _stage_outputs(image, outputs):
    staged = []
    for field_name, (filename, data) in outputs.items():
        field = getattr(image, field_name)
        field.save(filename, ContentFile(data), save=False)
        staged.append((field.storage, field.name))
    return tuple(staged)


def _lifecycle_update_fields():
    return [*IMAGE_FILE_FIELDS, 'width', 'height', 'processing_status', 'processing_error', 'updated_at']


def _persisted_lifecycle_fields():
    return [*IMAGE_FILE_FIELDS, 'width', 'height', 'processing_status', 'processing_error']


def _save_pending(image, *, initial_upload):
    image.processing_status = ProjectImage.ProcessingStatus.PENDING
    image.processing_error = ''
    fields = ['processing_status', 'processing_error', 'updated_at']
    if initial_upload:
        fields.insert(0, 'original')
    if image.pk:
        image.save(update_fields=fields)
    else:
        image.save()


def _save_initial_failure(image, *, source_name):
    image.original = source_name or ''
    for field_name in IMAGE_FILE_FIELDS[1:]:
        setattr(image, field_name, '')
    image.width = 0
    image.height = 0
    image.processing_status = ProjectImage.ProcessingStatus.FAILED
    image.processing_error = str(PROCESSING_ERROR)
    image.save(update_fields=_lifecycle_update_fields())


def _public_processing_error(error):
    if isinstance(error, ValidationError):
        try:
            messages = error.message_dict.get('original')
        except AttributeError:
            messages = None
        if messages:
            return ValidationError({'original': messages})
    return ValidationError({'original': PROCESSING_ERROR})


def _process_image(image, *, upload=None, previous_state=None, database_image=None):
    """Validate and synchronously publish a ProjectImage's complete file set.

    A ready row is replaced entirely in memory and committed only after every
    output has been staged. Initial rows are kept as retryable failed records.
    """
    locked_database_state = _snapshot_state(database_image) if database_image is not None else None
    database_state = previous_state or locked_database_state

    replacing_ready_image = bool(
        database_state
        and database_state['processing_status'] == ProjectImage.ProcessingStatus.READY
    )
    if not replacing_ready_image:
        persist_initial_upload = upload is not None and not image.pk
        if persist_initial_upload:
            image.original = upload
        _save_pending(image, initial_upload=persist_initial_upload)

    source = upload if upload is not None else image.original
    source_name = image.original.name
    try:
        outputs, dimensions = _prepare_outputs(source)
        _stage_outputs(image, outputs)
        image.width, image.height = dimensions
        image.processing_status = ProjectImage.ProcessingStatus.READY
        image.processing_error = ''
        current_references = _current_file_references(image)
        old_references = (
            *(database_state['file_refs'] if database_state else ()),
            *(locked_database_state['file_refs'] if locked_database_state else ()),
        )
        replaced_references = _references_not_in(old_references, current_references)

        with transaction.atomic():
            image.save(update_fields=_lifecycle_update_fields())
            schedule_file_cleanup(
                replaced_references,
                object_id=image.pk,
                reason='replacement',
            )
        return image
    except Exception as error:
        current_references = _current_file_references(image)
        if replacing_ready_image:
            new_references = _references_not_in(current_references, database_state['file_refs'])
            _delete_references(
                new_references,
                object_id=image.pk,
                reason='failed replacement',
            )
            _restore_state(image, database_state)
            if previous_state is not None:
                image.save(update_fields=_persisted_lifecycle_fields())
        else:
            generated_references = _references_not_in(current_references, ((
                image.original.storage,
                source_name,
            ),) if source_name else ())
            _delete_references(
                generated_references,
                object_id=image.pk,
                reason='failed processing',
            )
            _save_initial_failure(image, source_name=source_name)

        logger.warning(
            'Project image processing failed for image %s: %s',
            image.pk,
            error.__class__.__name__,
        )
        raise _public_processing_error(error) from error


def process_image(image, *, upload=None, previous_state=None):
    if not image.pk:
        return _process_image(image, upload=upload, previous_state=previous_state)

    processing_error = None
    with transaction.atomic():
        database_image = ProjectImage.objects.select_for_update().filter(pk=image.pk).first()
        try:
            return _process_image(
                image,
                upload=upload,
                previous_state=previous_state,
                database_image=database_image,
            )
        except ValidationError as error:
            processing_error = error

    raise processing_error


def replace_image(image, upload, *, previous_state=None):
    return process_image(image, upload=upload, previous_state=previous_state)
