from pathlib import PurePath
from urllib.parse import urlencode

from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.contrib.admin.utils import display_for_value
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, transaction
from django.forms import Media, formset_factory
from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _, ngettext

from .forms import (
    ProjectAdminForm,
    ProjectGalleryImageAdminForm,
    ProjectGalleryImageFormSet,
    ProjectImageAdminForm,
    ProjectImageBatchMetadataForm,
    ProjectImageBatchMetadataFormSet,
    ProjectImageBatchUploadForm,
    ProjectImageReplacementForm,
)
from .image_services import image_state, process_image, replace_image
from .models import Project, ProjectGalleryImage, ProjectImage
from .selectors import get_project_for_preview
from .services import (
    FeaturedProjectOutcome,
    ProjectOrderOutcome,
    append_project,
    get_projects_in_order,
    normalize_project_order,
    reorder_projects,
    set_featured_project,
    unfeature_project,
    unpublish_project,
)


PROJECT_IMAGE_PROCESSING_ERROR_ATTR = '_projects_image_processing_error'
PROJECT_IMAGE_BATCH_TOKEN_SALT = 'projects.project-image-batch'
PROJECT_IMAGE_BATCH_TOKEN_MAX_AGE = 24 * 60 * 60

# Keep the editorial label visible in the Admin without adding a schema-only
# migration to the already-established media model.
ProjectImage._meta.verbose_name = _('Project image')
ProjectImage._meta.verbose_name_plural = _('Project images')


class ProjectGalleryImageInline(admin.TabularInline):
    model = ProjectGalleryImage
    form = ProjectGalleryImageAdminForm
    formset = ProjectGalleryImageFormSet
    extra = 0
    show_change_link = True


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    form = ProjectAdminForm
    inlines = (ProjectGalleryImageInline,)
    change_form_template = 'admin/projects/project/change_form.html'
    change_list_template = 'admin/projects/project/change_list.html'
    list_display = (
        'title',
        'category',
        'publication_status',
        'featured_status',
        'updated_at',
    )
    list_filter = ('category', 'is_published', 'is_featured')
    search_fields = ('title', 'slug')
    prepopulated_fields = {'slug': ('title',)}
    ordering = ('sort_order', '-created_at', 'pk')

    def get_inline_instances(self, request, obj=None):
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if obj is not None:
            return fieldsets

        return tuple(
            (
                name,
                {
                    **options,
                    'fields': tuple(
                        field_name
                        for field_name in options.get('fields', ())
                        if field_name != 'cover_image'
                    ),
                },
            )
            for name, options in fieldsets
        )

    @admin.display(description=_('Publication status'), ordering='is_published')
    def publication_status(self, obj):
        return _('Published') if obj.is_published else _('Draft')

    @admin.display(description=_('Featured status'), ordering='is_featured')
    def featured_status(self, obj):
        return _('Featured') if obj.is_featured else _('Not featured')

    class Media:
        css = {'all': ('projects/css/admin.css',)}
        js = ('projects/js/project-gallery.js',)

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        context['project_preview_url'] = (
            reverse(
                f'{self.admin_site.name}:projects_project_preview',
                args=(obj.pk,),
            )
            if obj
            else None
        )
        context['project_feature_url'] = (
            reverse(
                f'{self.admin_site.name}:projects_project_feature',
                args=(obj.pk,),
            )
            if obj
            else None
        )
        context['project_unfeature_url'] = (
            reverse(
                f'{self.admin_site.name}:projects_project_unfeature',
                args=(obj.pk,),
            )
            if obj and obj.is_featured
            else None
        )
        return super().render_change_form(
            request,
            context,
            add=add,
            change=change,
            form_url=form_url,
            obj=obj,
        )

    def save_model(self, request, obj, form, change):
        with transaction.atomic():
            if change and not obj.is_published:
                unpublish_project(obj)
                obj.is_featured = False
            if change:
                obj.save()
            else:
                append_project(obj)

    def delete_model(self, request, obj):
        with transaction.atomic():
            super().delete_model(request, obj)
            normalize_project_order()

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            super().delete_queryset(request, queryset)
            normalize_project_order()

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['project_reorder_url'] = reverse(
            f'{self.admin_site.name}:projects_project_reorder'
        )
        extra_context['has_project_reorder_permission'] = self.has_change_permission(request)
        return super().changelist_view(request, extra_context=extra_context)

    def save_formset(self, request, form, formset, change):
        if not isinstance(formset, ProjectGalleryImageFormSet):
            return super().save_formset(request, form, formset, change)

        formset.save(commit=False)
        for deleted_object in formset.deleted_objects:
            deleted_object.delete()
        retained_forms = [
            inline_form
            for inline_form in formset.forms
            if inline_form.cleaned_data and not inline_form.cleaned_data.get('DELETE')
        ]
        ordered_instances = [
            inline_form.instance
            for inline_form in sorted(
                retained_forms,
                key=lambda inline_form: inline_form.cleaned_data['position'],
            )
        ]
        highest_position = (
            ProjectGalleryImage.objects.filter(project=form.instance)
            .order_by('-position')
            .values_list('position', flat=True)
            .first()
        )
        position_offset = (highest_position or 0) + len(ordered_instances) + 1
        for offset, instance in enumerate(ordered_instances):
            instance.position = position_offset + offset
            instance.save()
        for position, instance in enumerate(ordered_instances):
            instance.position = position
            instance.save()
        formset.save_m2m()

        if request.POST.get('_gallery_add_all'):
            self._add_all_gallery_images(request, form.instance)

    def _add_all_gallery_images(self, request, project):
        existing_ids = set(
            ProjectGalleryImage.objects.filter(project=project).values_list('image_id', flat=True)
        )
        candidates = ProjectImage.objects.filter(project=project).order_by('name', 'pk')
        available = [
            image
            for image in candidates
            if image.pk not in existing_ids and image.is_ready_for_publication()
        ]
        next_position = ProjectGalleryImage.objects.filter(project=project).count()
        for image in available:
            ProjectGalleryImage.objects.create(
                project=project,
                image=image,
                position=next_position,
            )
            next_position += 1

        if available:
            self.message_user(
                request,
                ngettext(
                    '%(count)d image was added to the gallery.',
                    '%(count)d images were added to the gallery.',
                    len(available),
                ) % {'count': len(available)},
                messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                _('All ready project images are already in the gallery.'),
                messages.INFO,
            )

    def get_urls(self):
        custom_urls = [
            path(
                'reorder/',
                self.admin_site.admin_view(self.reorder),
                name='projects_project_reorder',
            ),
            path(
                '<path:object_id>/preview/',
                self.admin_site.admin_view(self.preview, cacheable=True),
                name='projects_project_preview',
            ),
            path(
                '<path:object_id>/feature/',
                self.admin_site.admin_view(self.feature),
                name='projects_project_feature',
            ),
            path(
                '<path:object_id>/unfeature/',
                self.admin_site.admin_view(self.unfeature),
                name='projects_project_unfeature',
            ),
        ]
        return custom_urls + super().get_urls()

    def _render_reorder(self, request, *, error=None):
        request.current_app = self.admin_site.name
        projects = get_projects_in_order()
        reorder_url = reverse(f'{self.admin_site.name}:projects_project_reorder')
        changelist_url = reverse(f'{self.admin_site.name}:projects_project_changelist')
        return render(
            request,
            'admin/projects/project/reorder.html',
            {
                **self.admin_site.each_context(request),
                'title': _('Reorder projects'),
                'opts': self.model._meta,
                'media': Media(
                    css={'all': ('projects/css/admin.css',)},
                    js=('projects/js/project-reorder.js',),
                ),
                'projects': projects,
                'project_reorder_url': reorder_url,
                'project_changelist_url': changelist_url,
                'reorder_error': error,
            },
        )

    def reorder(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied
        if request.method not in {'GET', 'POST'}:
            return HttpResponseNotAllowed(['GET', 'POST'])

        if request.method == 'GET':
            return self._render_reorder(request)

        outcome = reorder_projects(
            request.POST.getlist('project_id'),
            request.POST.getlist('expected_project_id'),
        )
        if outcome is ProjectOrderOutcome.UPDATED:
            self.message_user(request, _('Project order saved.'), messages.SUCCESS)
            return redirect(f'{self.admin_site.name}:projects_project_reorder')
        if outcome is ProjectOrderOutcome.STALE:
            error = _(
                'Projects changed since this page was loaded. Review the current order and try again.'
            )
        else:
            error = _(
                'The submitted project order was incomplete or invalid. Reload the page and try again.'
            )
        return self._render_reorder(request, error=error)

    def _get_project(self, request, object_id):
        project = self.get_object(request, object_id)
        if project is None:
            raise Http404
        return project

    def preview(self, request, object_id):
        project = self._get_project(request, object_id)
        if not self.has_view_permission(request, project):
            raise PermissionDenied
        if request.method != 'GET':
            return HttpResponseNotAllowed(['GET'])

        from .views import _project_context

        project = get_project_for_preview(project.pk)
        response = render(
            request,
            'site_frontend/projects/detail.html',
            _project_context(request, project, preview=True),
        )
        response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        response['Cache-Control'] = 'private, no-store'
        return response

    def _current_featured_project(self):
        return (
            Project.objects.select_related('cover_image')
            .filter(is_featured=True)
            .first()
        )

    def _feature_cover_url(self, project):
        if not project or not project.cover_image or not project.cover_image.has_publication_files():
            return None
        return _field_url(project.cover_image.rendition_960) or _field_url(project.cover_image.original)

    def _feature_confirmation_context(
        self,
        project,
        *,
        current=None,
        warning=None,
    ):
        return {
            'title': _('Change featured project?') if current else _('Feature project'),
            'feature_current_project': current,
            'feature_proposed_project': project,
            'feature_current_cover_url': self._feature_cover_url(current),
            'feature_proposed_cover_url': self._feature_cover_url(project),
            'feature_expected_current_id': current.pk if current else '',
            'feature_change_url': reverse(
                f'{self.admin_site.name}:projects_project_change',
                args=(project.pk,),
            ),
            'feature_url': reverse(
                f'{self.admin_site.name}:projects_project_feature',
                args=(project.pk,),
            ),
            'feature_warning': warning,
        }

    def _render_feature_confirmation(
        self,
        request,
        project,
        *,
        current=None,
        warning=None,
    ):
        request.current_app = self.admin_site.name
        response = render(
            request,
            'admin/projects/project/feature_confirmation.html',
            {
                **self.admin_site.each_context(request),
                'media': self.media,
                **self._feature_confirmation_context(
                    project,
                    current=current,
                    warning=warning,
                ),
            },
        )
        response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        response['Cache-Control'] = 'private, no-store'
        return response

    @staticmethod
    def _parse_expected_current_id(value):
        if value in (None, ''):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return -1

    def feature(self, request, object_id):
        project = self._get_project(request, object_id)
        if not self.has_change_permission(request, project):
            raise PermissionDenied
        if request.method not in {'GET', 'POST'}:
            return HttpResponseNotAllowed(['GET', 'POST'])

        if request.method == 'GET':
            if not project.is_published:
                self.message_user(
                    request,
                    _('Publish this project before featuring it on the homepage.'),
                    messages.WARNING,
                )
                return redirect(
                    f'{self.admin_site.name}:projects_project_change',
                    project.pk,
                )
            current = self._current_featured_project()
            return self._render_feature_confirmation(
                request,
                project,
                current=current,
            )

        expected_current_id = self._parse_expected_current_id(
            request.POST.get('expected_current_id')
        )
        outcome = set_featured_project(project, expected_current_id)
        if outcome is FeaturedProjectOutcome.UNPUBLISHED:
            self.message_user(
                request,
                _('Publish this project before featuring it on the homepage.'),
                messages.WARNING,
            )
            return redirect(
                f'{self.admin_site.name}:projects_project_change',
                project.pk,
            )
        if outcome is FeaturedProjectOutcome.STALE:
            current = self._current_featured_project()
            return self._render_feature_confirmation(
                request,
                project,
                current=current,
                warning=_(
                    'The featured project changed while you were confirming. Review the comparison and confirm again.'
                ),
            )

        self.message_user(request, _('The project is now featured on the homepage.'), messages.SUCCESS)
        return redirect(
            f'{self.admin_site.name}:projects_project_change',
            project.pk,
        )

    def unfeature(self, request, object_id):
        project = self._get_project(request, object_id)
        if not self.has_change_permission(request, project):
            raise PermissionDenied
        if request.method != 'POST':
            return HttpResponseNotAllowed(['POST'])

        unfeature_project(project)
        self.message_user(request, _('The project was removed from the homepage.'), messages.SUCCESS)
        return redirect(
            f'{self.admin_site.name}:projects_project_change',
            project.pk,
        )


def _field_url(field):
    if not field or not field.name:
        return None
    try:
        if not field.storage.exists(field.name):
            return None
        return field.url
    except (OSError, ValueError):
        return None


def _processing_error_message(error):
    if isinstance(error, ValidationError):
        try:
            messages_for_field = error.message_dict.get('original')
        except AttributeError:
            messages_for_field = None
        if messages_for_field:
            return messages_for_field[0]
    return _('The image could not be processed. Check the file and try again.')


@admin.register(ProjectImage)
class ProjectImageAdmin(admin.ModelAdmin):
    form = ProjectImageAdminForm
    actions = ('delete_selected',)
    change_form_template = 'admin/projects/projectimage/change_form.html'
    delete_confirmation_template = 'admin/projects/projectimage/delete_confirmation.html'
    list_display = (
        'thumbnail',
        'name',
        'project',
        'readiness',
        'usage_summary',
        'created_at',
        'updated_at',
        'rendition_summary',
    )
    list_display_links = ('name',)
    list_filter = ('processing_status', 'project')
    search_fields = ('name', 'project__title')
    ordering = ('-created_at', '-pk')

    class Media:
        css = {'all': ('projects/css/admin.css',)}

    def get_fields(self, request, obj=None):
        fields = ['project', 'name', 'original', 'alt_text', 'is_decorative']
        if obj is not None:
            fields.extend([
                'processing_status',
                'processing_error',
                'width',
                'height',
                'rendition_480',
                'rendition_960',
                'rendition_1600',
                'social_1200x630',
                'created_by',
                'created_at',
                'updated_at',
            ])
        return fields

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return (
            'project',
            'original',
            'processing_status',
            'processing_error',
            'width',
            'height',
            'rendition_480',
            'rendition_960',
            'rendition_1600',
            'social_1200x630',
            'created_by',
            'created_at',
            'updated_at',
        )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('project')

    def _batch_token(self, request, images):
        return signing.dumps(
            {
                'user_id': request.user.pk,
                'project_id': images[0].project_id,
                'images': [
                    [image.pk, image.updated_at.isoformat()]
                    for image in images
                ],
            },
            salt=PROJECT_IMAGE_BATCH_TOKEN_SALT,
            compress=True,
        )

    def _batch_images(self, request, token, *, for_update=False):
        try:
            payload = signing.loads(
                token,
                salt=PROJECT_IMAGE_BATCH_TOKEN_SALT,
                max_age=PROJECT_IMAGE_BATCH_TOKEN_MAX_AGE,
            )
            entries = payload['images']
            image_ids = [entry[0] for entry in entries]
            versions = [entry[1] for entry in entries]
            project_id = payload['project_id']
            user_id = payload['user_id']
        except (IndexError, KeyError, TypeError, signing.BadSignature):
            raise PermissionDenied from None

        if (
            not image_ids
            or len(image_ids) != len(set(image_ids))
            or not all(isinstance(image_id, int) for image_id in image_ids)
            or not all(isinstance(version, str) for version in versions)
            or user_id != request.user.pk
        ):
            raise PermissionDenied

        queryset = ProjectImage.objects.select_related('project')
        if for_update:
            queryset = queryset.select_for_update()
        images_by_id = queryset.in_bulk(image_ids)
        try:
            images = [images_by_id[image_id] for image_id in image_ids]
        except KeyError:
            raise PermissionDenied from None

        if any(
            image.project_id != project_id
            or image.created_by_id != user_id
            or image.updated_at.isoformat() != version
            for image, version in zip(images, versions)
        ):
            raise PermissionDenied
        return images

    def _batch_metadata_formset(self, images, data=None):
        formset_class = formset_factory(
            ProjectImageBatchMetadataForm,
            formset=ProjectImageBatchMetadataFormSet,
            extra=0,
            max_num=len(images),
            validate_max=True,
            absolute_max=len(images),
        )
        return formset_class(data=data, images=images)

    def _batch_rows(self, formset):
        return [
            {
                'form': form,
                'image': form.instance,
                'preview_url': (
                    _field_url(form.instance.rendition_480)
                    if form.instance.processing_status == ProjectImage.ProcessingStatus.READY
                    else None
                ),
            }
            for form in formset.forms
        ]

    def _render_batch_add(
        self,
        request,
        *,
        upload_form=None,
        images=None,
        formset=None,
        token='',
    ):
        images = images or []
        return self._render_admin_page(
            request,
            'admin/projects/projectimage/batch_add.html',
            {
                'title': _('Add project images'),
                'upload_form': upload_form,
                'batch_images': images,
                'batch_formset': formset,
                'batch_rows': self._batch_rows(formset) if formset is not None else [],
                'batch_token': token,
                'batch_ready_count': sum(
                    image.processing_status == ProjectImage.ProcessingStatus.READY
                    for image in images
                ),
                'batch_failed_count': sum(
                    image.processing_status == ProjectImage.ProcessingStatus.FAILED
                    for image in images
                ),
                'image_changelist_url': reverse(
                    f'{self.admin_site.name}:projects_projectimage_changelist'
                ),
            },
        )

    @staticmethod
    def _name_from_upload(upload):
        filename = upload.name.replace('\\', '/')
        return (PurePath(filename).stem.strip() or 'Untitled image')[:200]

    def _create_batch_images(self, request, project, uploads):
        images = []
        unsaved_failures = []
        for upload in uploads:
            image = ProjectImage(
                project=project,
                name=self._name_from_upload(upload),
                original=upload,
                created_by=request.user,
            )
            try:
                image.save()
                process_image(image)
            except (DatabaseError, OSError, ValidationError):
                if not image.pk:
                    unsaved_failures.append(upload.name)
            if image.pk:
                image.refresh_from_db()
                self.log_addition(
                    request,
                    image,
                    _('Added through batch upload.'),
                )
                images.append(image)
        return images, unsaved_failures

    def _save_batch_metadata(self, request, token, formset):
        with transaction.atomic():
            images = self._batch_images(request, token, for_update=True)
            for image, form in zip(images, formset.forms):
                image.name = form.cleaned_data['name']
                image.alt_text = form.cleaned_data['alt_text']
                image.is_decorative = form.cleaned_data['is_decorative']
                image.full_clean()
                image.save(update_fields=[
                    'name',
                    'alt_text',
                    'is_decorative',
                    'updated_at',
                ])
                self.log_change(
                    request,
                    image,
                    _('Updated metadata through batch upload.'),
                )
        return len(images)

    def add_view(self, request, form_url='', extra_context=None):
        if request.method not in {'GET', 'POST'}:
            return HttpResponseNotAllowed(['GET', 'POST'])
        if not self.has_add_permission(request):
            raise PermissionDenied

        if request.method == 'POST' and request.POST.get('step') == 'metadata':
            token = request.POST.get('batch_token', '')
            images = self._batch_images(request, token)
            formset = self._batch_metadata_formset(images, request.POST)
            if formset.is_valid():
                count = self._save_batch_metadata(request, token, formset)
                self.message_user(
                    request,
                    ngettext(
                        '%(count)d project image was updated.',
                        '%(count)d project images were updated.',
                        count,
                    ) % {'count': count},
                    messages.SUCCESS,
                )
                return redirect(
                    f'{self.admin_site.name}:projects_projectimage_changelist'
                )
            return self._render_batch_add(
                request,
                images=images,
                formset=formset,
                token=token,
            )

        if request.method == 'POST':
            upload_form = ProjectImageBatchUploadForm(request.POST, request.FILES)
            if upload_form.is_valid():
                images, unsaved_failures = self._create_batch_images(
                    request,
                    upload_form.cleaned_data['project'],
                    upload_form.cleaned_data['uploads'],
                )
                if not images:
                    upload_form.add_error(
                        'uploads',
                        _('The selected images could not be saved. Try again.'),
                    )
                else:
                    if unsaved_failures:
                        count = len(unsaved_failures)
                        self.message_user(
                            request,
                            ngettext(
                                '%(count)d selected file could not be saved.',
                                '%(count)d selected files could not be saved.',
                                count,
                            ) % {'count': count},
                            messages.WARNING,
                        )
                    token = self._batch_token(request, images)
                    add_url = reverse(
                        f'{self.admin_site.name}:projects_projectimage_add'
                    )
                    return redirect(f'{add_url}?{urlencode({"batch": token})}')
            return self._render_batch_add(request, upload_form=upload_form)

        token = request.GET.get('batch', '')
        if token:
            images = self._batch_images(request, token)
            return self._render_batch_add(
                request,
                images=images,
                formset=self._batch_metadata_formset(images),
                token=token,
            )
        return self._render_batch_add(
            request,
            upload_form=ProjectImageBatchUploadForm(),
        )

    @admin.display(description=_('Thumbnail'))
    def thumbnail(self, obj):
        url = _field_url(obj.rendition_480) or _field_url(obj.original)
        if url:
            return format_html(
                '<img class="project-image-admin__thumbnail" src="{}" alt="">',
                url,
            )
        return format_html(
            '<span class="project-image-admin__placeholder">{}</span>',
            _('Unavailable'),
        )

    @admin.display(description=_('Readiness'), ordering='processing_status')
    def readiness(self, obj):
        if obj.processing_status == ProjectImage.ProcessingStatus.READY:
            return _('Ready') if obj.has_publication_files() else _('Unavailable')
        return obj.get_processing_status_display()

    def _usage_rows(self, image):
        rows = []
        projects = Project.objects.filter(cover_image_id=image.pk).order_by('title', 'pk')
        rows.extend(
            {
                'project': project,
                'role': _('Cover'),
                'published': project.is_published,
                'url': reverse(
                    f'{self.admin_site.name}:projects_project_change',
                    args=(project.pk,),
                ),
            }
            for project in projects
        )
        gallery_items = ProjectGalleryImage.objects.filter(image_id=image.pk).select_related('project')
        rows.extend(
            {
                'project': item.project,
                'role': _('Gallery'),
                'published': item.project.is_published,
                'url': reverse(
                    f'{self.admin_site.name}:projects_project_change',
                    args=(item.project.pk,),
                ),
                'position': item.position,
            }
            for item in gallery_items
        )
        return rows

    @admin.display(description=_('Usage'))
    def usage_summary(self, obj):
        rows = self._usage_rows(obj)
        if not rows:
            return _('Unused')
        return _('%(count)s use(s)') % {'count': len(rows)}

    @admin.display(description=_('Ready renditions'))
    def rendition_summary(self, obj):
        rendition_labels = (
            ('rendition_480', '480 px'),
            ('rendition_960', '960 px'),
            ('rendition_1600', '1600 px'),
            ('social_1200x630', 'Social crop'),
        )
        available = [
            label
            for field_name, label in rendition_labels
            if _field_url(getattr(obj, field_name))
        ]
        return ', '.join(available) if available else _('None')

    def _image_context(self, request, image):
        usage_rows = self._usage_rows(image)
        rendition_rows = []
        for field_name, label in (
            ('original', _('Original')),
            ('rendition_480', _('480 px WebP')),
            ('rendition_960', _('960 px WebP')),
            ('rendition_1600', _('1600 px WebP')),
            ('social_1200x630', _('Social crop (1200 × 630 JPEG)')),
        ):
            field = getattr(image, field_name)
            rendition_rows.append({
                'label': label,
                'name': field.name,
                'url': _field_url(field),
            })
        return {
            'project_image_usage_rows': usage_rows,
            'project_image_published_usage': any(row['published'] for row in usage_rows),
            'project_image_rendition_rows': rendition_rows,
            'project_image_can_change': self.has_change_permission(request, image),
            'project_image_replace_url': reverse(
                f'{self.admin_site.name}:projects_projectimage_replace',
                args=(image.pk,),
            ),
        }

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        extra_context = dict(extra_context or {})
        if object_id is not None:
            image = self.get_object(request, object_id)
            if image is not None:
                extra_context.update(self._image_context(request, image))
        return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.save()
        if change:
            return

        try:
            process_image(obj)
        except (DatabaseError, OSError, ValidationError) as error:
            form.add_error('original', _processing_error_message(error))
            setattr(request, PROJECT_IMAGE_PROCESSING_ERROR_ATTR, True)

    def _render_processing_error(self, request, obj, form):
        fieldsets = self.get_fieldsets(request, obj)
        readonly_fields = self.get_readonly_fields(request, obj)
        admin_form = helpers.AdminForm(
            form,
            list(fieldsets),
            self.get_prepopulated_fields(request, obj),
            readonly_fields,
            model_admin=self,
        )
        context = {
            **self.admin_site.each_context(request),
            'title': _('Change %(name)s') % {'name': self.opts.verbose_name},
            'subtitle': display_for_value(str(obj), '-'),
            'adminform': admin_form,
            'object_id': str(obj.pk),
            'original': obj,
            'is_popup': False,
            'to_field': None,
            'media': self.media + admin_form.media,
            'action_form': None,
            'inline_admin_formsets': [],
            'errors': helpers.AdminErrorList(form, []),
            'preserved_filters': self.get_preserved_filters(request),
            **self._image_context(request, obj),
        }
        return self.render_change_form(
            request,
            context,
            add=False,
            change=True,
            obj=obj,
            form_url='',
        )

    def response_add(self, request, obj, post_url_continue=None):
        if getattr(request, PROJECT_IMAGE_PROCESSING_ERROR_ATTR, False):
            return self._render_processing_error(request, obj, request._projects_image_form)
        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if getattr(request, PROJECT_IMAGE_PROCESSING_ERROR_ATTR, False):
            return self._render_processing_error(request, obj, request._projects_image_form)
        return super().response_change(request, obj)

    def save_form(self, request, form, change):
        obj = super().save_form(request, form, change)
        if isinstance(form, ProjectImageAdminForm):
            request._projects_image_form = form
        return obj

    def get_urls(self):
        custom_urls = [
            path(
                '<path:object_id>/replace/',
                self.admin_site.admin_view(self.replace),
                name='projects_projectimage_replace',
            ),
        ]
        return custom_urls + super().get_urls()

    def get_deleted_objects(self, objs, request):
        # Gallery rows are detached by delete_model; editors should not need a
        # separate gallery-row delete permission to remove owned media.
        return [], {str(self.opts.verbose_name): len(objs)}, [], []

    def _get_image(self, request, object_id):
        image = self.get_object(request, object_id)
        if image is None:
            raise Http404
        return image

    def _render_admin_page(self, request, template_name, context):
        request.current_app = self.admin_site.name
        response = render(request, template_name, {
            **self.admin_site.each_context(request),
            'media': self.media,
            **context,
        })
        response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        response['Cache-Control'] = 'private, no-store'
        return response

    def replace(self, request, object_id):
        if request.method not in {'GET', 'POST'}:
            return HttpResponseNotAllowed(['GET', 'POST'])
        image = self._get_image(request, object_id)
        if not self.has_change_permission(request, image):
            raise PermissionDenied

        usage_rows = self._usage_rows(image)
        form = ProjectImageReplacementForm(
            request.POST or None,
            request.FILES or None,
        )
        if request.method == 'POST' and form.is_valid():
            try:
                replace_image(
                    image,
                    form.cleaned_data['upload'],
                    previous_state=image_state(image),
                )
            except (DatabaseError, OSError, ValidationError) as error:
                form.add_error('upload', _processing_error_message(error))
            else:
                image.refresh_from_db()
                if not image.has_publication_files():
                    form.add_error(
                        None,
                        _('The replacement could not be confirmed. Return to the image and try again.'),
                    )
                else:
                    self.message_user(request, _('The project image was replaced.'), messages.SUCCESS)
                    return redirect(
                        f'{self.admin_site.name}:projects_projectimage_change',
                        image.pk,
                    )

        return self._render_admin_page(
            request,
            'admin/projects/projectimage/action_form.html',
            {
                'image': image,
                'usage_rows': usage_rows,
                'published_usage': any(row['published'] for row in usage_rows),
                'form': form,
                'action': 'replace',
                'image_url': _field_url(image.rendition_960) or _field_url(image.original),
                'title': _('Replace project image'),
                'image_change_url': reverse(
                    f'{self.admin_site.name}:projects_projectimage_change',
                    args=(image.pk,),
                ),
                'image_changelist_url': reverse(
                    f'{self.admin_site.name}:projects_projectimage_changelist'
                ),
            },
        )

    def delete_view(self, request, object_id, extra_context=None):
        extra_context = dict(extra_context or {})
        image = self.get_object(request, object_id)
        if image is not None and self.has_delete_permission(request, image):
            usage_rows = self._usage_rows(image)
            extra_context.update({
                'project_image_usage_rows': usage_rows,
                'project_image_published_usage': any(row['published'] for row in usage_rows),
            })
        return super().delete_view(request, object_id, extra_context)

    def delete_model(self, request, obj):
        with transaction.atomic():
            Project.objects.filter(cover_image_id=obj.pk).update(cover_image=None)
            ProjectGalleryImage.objects.filter(image_id=obj.pk).delete()
            obj.delete()

    def delete_queryset(self, request, queryset):
        with transaction.atomic():
            for image in queryset:
                self.delete_model(request, image)
