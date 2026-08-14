from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from .technologies import normalize_technology_stack


def _uuid_upload_path(prefix, filename, *, extension=None):
    suffix = extension or Path(filename).suffix.lower()
    if suffix not in {'.jpg', '.jpeg', '.png', '.webp'}:
        suffix = '.img'
    return f'{prefix}/{uuid4().hex}{suffix}'


def project_original_upload_path(instance, filename):
    return _uuid_upload_path('projects/originals', filename)


def project_rendition_upload_path(instance, filename):
    return _uuid_upload_path('projects/renditions', filename, extension='.webp')


def project_social_upload_path(instance, filename):
    return _uuid_upload_path('projects/social', filename, extension='.jpg')


class ProjectCategory(models.TextChoices):
    APPS = 'apps', 'Apps'
    THEMES = 'themes', 'Themes'
    PUBLISHING = 'publishing', 'Publishing'
    FEATURES = 'features', 'Features'
    OPERATIONS = 'operations', 'Operations'


class Project(models.Model):
    Category = ProjectCategory

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    category = models.CharField(max_length=10, choices=Category.choices)
    summary = models.TextField()
    body = models.TextField(blank=True)
    seo_title = models.CharField(max_length=70, blank=True)
    seo_description = models.CharField(max_length=160, blank=True)
    is_published = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    repo_url = models.URLField(blank=True)
    live_url = models.URLField(blank=True)
    cover_image = models.ForeignKey(
        'ProjectImage',
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='cover_for_projects',
    )
    gallery_caption = models.CharField(max_length=500, blank=True)
    technology_stack = models.JSONField(default=list, blank=True)
    full_feature_list = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['is_published', 'is_featured', 'sort_order']),
            models.Index(
                fields=['is_published', 'category', 'sort_order'],
                name='projects_pub_cat_order_idx',
            ),
        ]
        ordering = ['sort_order', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['is_featured'],
                condition=Q(is_featured=True),
                name='projects_one_featured_project',
            ),
            models.CheckConstraint(
                condition=Q(is_featured=False) | Q(is_published=True),
                name='projects_featured_requires_published',
            ),
            models.CheckConstraint(
                condition=Q(category__in=ProjectCategory.values),
                name='projects_category_valid',
            ),
            models.CheckConstraint(
                condition=~Q(slug__in=ProjectCategory.values),
                name='projects_slug_not_category',
            ),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        errors = {}

        try:
            self.technology_stack = normalize_technology_stack(self.technology_stack)
        except ValidationError as error:
            errors['technology_stack'] = error

        if self.is_featured and not self.is_published:
            errors['is_featured'] = _('Only published projects can be featured.')

        if self.cover_image_id and self.cover_image.project_id != self.pk:
            errors['cover_image'] = _('Choose an image owned by this project.')

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.technology_stack = normalize_technology_stack(self.technology_stack)
        super().save(*args, **kwargs)


class ProjectImage(models.Model):
    class ProcessingStatus(models.TextChoices):
        PENDING = 'pending', _('Pending')
        READY = 'ready', _('Ready')
        FAILED = 'failed', _('Failed')

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='images')
    name = models.CharField(max_length=200)
    original = models.ImageField(upload_to=project_original_upload_path)
    rendition_480 = models.ImageField(upload_to=project_rendition_upload_path, blank=True)
    rendition_960 = models.ImageField(upload_to=project_rendition_upload_path, blank=True)
    rendition_1600 = models.ImageField(upload_to=project_rendition_upload_path, blank=True)
    social_1200x630 = models.ImageField(upload_to=project_social_upload_path, blank=True)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    alt_text = models.CharField(max_length=255, blank=True)
    is_decorative = models.BooleanField(default=False)
    processing_status = models.CharField(
        max_length=12,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
    )
    processing_error = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='created_project_images',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-pk']

    def __str__(self):
        return self.name or f'Project image #{self.pk}'

    def clean(self):
        super().clean()
        errors = {}

        if self.is_decorative and self.alt_text.strip():
            errors['alt_text'] = _('Decorative images must use empty alternative text.')
        elif not self.is_decorative and not self.alt_text.strip():
            errors['alt_text'] = _('Describe this image for readers who cannot see it.')

        if self.pk:
            existing_project_id = type(self).objects.filter(pk=self.pk).values_list('project_id', flat=True).first()
            if existing_project_id is not None and existing_project_id != self.project_id:
                errors['project'] = _('An existing image cannot be moved to another project.')

        if errors:
            raise ValidationError(errors)

    def has_publication_files(self):
        fields = (
            self.original,
            self.rendition_480,
            self.rendition_960,
            self.rendition_1600,
            self.social_1200x630,
        )
        if (
            self.processing_status != self.ProcessingStatus.READY
            or not self.width
            or not self.height
        ):
            return False
        try:
            return all(field and field.storage.exists(field.name) for field in fields)
        except (OSError, ValueError):
            return False

    def is_ready_for_publication(self):
        if not self.has_publication_files():
            return False
        if self.is_decorative:
            return not self.alt_text.strip()
        return bool(self.alt_text.strip())


class ProjectGalleryImage(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='gallery_items')
    image = models.ForeignKey(ProjectImage, on_delete=models.CASCADE, related_name='gallery_items')
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ['position', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'image'],
                name='projects_one_gallery_image',
            ),
            models.UniqueConstraint(
                fields=['project', 'position'],
                name='projects_unique_gallery_position',
            ),
        ]

    def __str__(self):
        return f'{self.project}: {self.image}'

    def clean(self):
        super().clean()
        if not self.project_id or not self.image_id:
            return

        image = ProjectImage.objects.filter(pk=self.image_id).first()
        if image is None:
            return

        errors = {}
        if image.project_id != self.project_id:
            errors['image'] = _('Choose an image owned by this project.')
        elif not image.is_ready_for_publication():
            errors['image'] = _('Choose an image that is ready for publication.')

        if errors:
            raise ValidationError(errors)
