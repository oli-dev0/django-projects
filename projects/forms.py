from django import forms
from django.core.exceptions import ValidationError
from django.forms.formsets import BaseFormSet
from django.forms.models import BaseInlineFormSet
from django.utils.translation import gettext_lazy as _

from .models import Project, ProjectGalleryImage, ProjectImage
from .rendering import (
    FeatureMarkdownHeadingError,
    FeatureMarkdownRenderError,
    render_feature_markdown,
    validate_feature_markdown_headings,
)
from .technologies import TECHNOLOGY_CHOICES


PROJECT_IMAGE_BATCH_MAX_FILES = 10


def _ready_project_images(project_id):
    if not project_id:
        return ProjectImage.objects.none()

    ready_ids = [
        image.pk
        for image in ProjectImage.objects.filter(
            project_id=project_id,
            processing_status=ProjectImage.ProcessingStatus.READY,
        )
        if image.is_ready_for_publication()
    ]
    return ProjectImage.objects.filter(pk__in=ready_ids).order_by('name', 'pk')


class ProjectAdminForm(forms.ModelForm):
    technology_stack = forms.MultipleChoiceField(
        label=_('Technology stack'),
        choices=TECHNOLOGY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(
            attrs={'class': 'project-technology-picker__choices'},
        ),
    )

    class Meta:
        model = Project
        fields = (
            'title',
            'slug',
            'category',
            'summary',
            'body',
            'seo_title',
            'seo_description',
            'is_published',
            'repo_url',
            'live_url',
            'cover_image',
            'gallery_caption',
            'technology_stack',
            'full_feature_list',
        )
        widgets = {
            'summary': forms.Textarea(attrs={'rows': 4}),
            'body': forms.Textarea(attrs={'rows': 8}),
            'seo_description': forms.Textarea(attrs={'rows': 3}),
            'gallery_caption': forms.Textarea(attrs={'rows': 3}),
            'full_feature_list': forms.Textarea(attrs={'rows': 16}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['cover_image'].queryset = _ready_project_images(self.instance.pk)
            self.fields['cover_image'].help_text = _(
                'Only ready images owned by this project can be used as the cover.'
            )
        else:
            self.fields.pop('cover_image', None)

        self.fields['gallery_caption'].help_text = _(
            'Optional caption describing the gallery as a whole.'
        )
        self.fields['full_feature_list'].label = _('Full feature list')
        self.fields['full_feature_list'].help_text = _(
            'Optional Markdown content shown in a popup on the project page.'
        )

    def clean_full_feature_list(self):
        value = self.cleaned_data.get('full_feature_list', '')
        if value:
            try:
                validate_feature_markdown_headings(value)
                render_feature_markdown(value)
            except FeatureMarkdownHeadingError as error:
                raise forms.ValidationError(str(error)) from error
            except FeatureMarkdownRenderError as error:
                raise forms.ValidationError(
                    _('The feature list could not be safely rendered. Check the Markdown and try again.')
                ) from error
        return value

    def clean_body(self):
        value = self.cleaned_data.get('body', '')
        if value:
            try:
                validate_feature_markdown_headings(value)
                render_feature_markdown(value)
            except FeatureMarkdownHeadingError as error:
                raise forms.ValidationError(str(error)) from error
            except FeatureMarkdownRenderError as error:
                raise forms.ValidationError(
                    _('The body could not be safely rendered. Check the Markdown and try again.')
                ) from error
        return value

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('is_published') and self.instance.is_featured:
            # The transition service clears this state during the Admin save.
            # Keep model validation from rejecting the intended unpublish.
            self.instance.is_featured = False
        cover_image = cleaned_data.get('cover_image')
        if cover_image:
            if cover_image.project_id != self.instance.pk:
                self.add_error('cover_image', _('Choose an image owned by this project.'))
            elif not cover_image.is_ready_for_publication():
                self.add_error(
                    'cover_image',
                    _('Choose an image that is ready for publication.'),
                )
        return cleaned_data


class ProjectImageAdminForm(forms.ModelForm):
    # The lifecycle service, rather than Pillow's form field, owns upload
    # validation so failed initial uploads can remain retryable in Admin.
    original = forms.FileField(label=_('Original image'), required=False)

    class Meta:
        model = ProjectImage
        fields = ('project', 'name', 'original', 'alt_text', 'is_decorative')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'original' in self.fields:
            self.fields['original'].required = not bool(self.instance.pk)
            self.fields['original'].help_text = _(
                'JPEG, PNG, or WebP. Maximum 15 MB and 40 megapixels.'
            )

    def _get_validation_exclusions(self):
        exclusions = super()._get_validation_exclusions()
        exclusions.add('original')
        return exclusions

    def clean_alt_text(self):
        return self.cleaned_data.get('alt_text', '').strip()

    def clean(self):
        cleaned_data = super().clean()
        project = cleaned_data.get('project')
        if self.instance.pk and project and project.pk != self.instance.project_id:
            self.add_error('project', _('An existing image cannot be moved to another project.'))
        return cleaned_data


class ProjectImageMultipleFileInput(forms.FileInput):
    allow_multiple_selected = True


class ProjectImageMultipleFileField(forms.FileField):
    widget = ProjectImageMultipleFileInput

    def __init__(self, *args, max_files, **kwargs):
        self.max_files = max_files
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else [data]
        if not files:
            super().clean(None, initial)
        if len(files) > self.max_files:
            raise ValidationError(
                _('Select no more than %(max_files)d images at a time.'),
                params={'max_files': self.max_files},
            )
        clean_file = super().clean
        cleaned_files = [clean_file(upload, initial) for upload in files]
        return [upload for upload in cleaned_files if upload]


class ProjectImageBatchUploadForm(forms.Form):
    project = forms.ModelChoiceField(
        label=_('Project'),
        queryset=Project.objects.order_by('title', 'pk'),
    )
    uploads = ProjectImageMultipleFileField(
        label=_('Images'),
        max_files=PROJECT_IMAGE_BATCH_MAX_FILES,
        help_text=_(
            'Select up to 10 JPEG, PNG, or WebP files. Each file can be up to 15 MB and 40 megapixels.'
        ),
        widget=ProjectImageMultipleFileInput(
            attrs={'accept': 'image/jpeg,image/png,image/webp'},
        ),
    )


class ProjectImageBatchMetadataForm(forms.ModelForm):
    class Meta:
        model = ProjectImage
        fields = ('name', 'alt_text', 'is_decorative')

    def clean_alt_text(self):
        return self.cleaned_data.get('alt_text', '').strip()


class ProjectImageBatchMetadataFormSet(BaseFormSet):
    def __init__(self, *args, images, **kwargs):
        self.images = tuple(images)
        kwargs['initial'] = [{} for _ in self.images]
        super().__init__(*args, **kwargs)

    def initial_form_count(self):
        return len(self.images)

    def _construct_form(self, i, **kwargs):
        if i < len(self.images):
            kwargs['instance'] = self.images[i]
        return super()._construct_form(i, **kwargs)

    def clean(self):
        super().clean()
        if len(self.forms) != len(self.images):
            raise ValidationError(_('The uploaded image list changed. Reload the page and try again.'))


class ProjectImageReplacementForm(forms.Form):
    upload = forms.FileField(
        label=_('Replacement image'),
        help_text=_('JPEG, PNG, or WebP. Maximum 15 MB and 40 megapixels.'),
    )


class ProjectGalleryImageAdminForm(forms.ModelForm):
    class Meta:
        model = ProjectGalleryImage
        fields = ('image', 'position')
        labels = {
            'image': _('Image'),
            'position': _('Order'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['image'].queryset = _ready_project_images(
            getattr(self.instance, 'project_id', None)
        )

    def _validation_exclusions_without_position(self):
        exclude = self._get_validation_exclusions()
        exclude.add('position')
        return exclude

    def validate_unique(self):
        try:
            self.instance.validate_unique(
                exclude=self._validation_exclusions_without_position()
            )
        except ValidationError as error:
            self._update_errors(error)

    def validate_constraints(self):
        try:
            self.instance.validate_constraints(
                exclude=self._validation_exclusions_without_position()
            )
        except ValidationError as error:
            self._update_errors(error)


class ProjectGalleryImageFormSet(BaseInlineFormSet):
    @property
    def empty_form(self):
        form = super().empty_form
        form.fields['image'].queryset = _ready_project_images(self.instance.pk)
        return form

    def _construct_form(self, i, **kwargs):
        form = super()._construct_form(i, **kwargs)
        form.fields['image'].queryset = _ready_project_images(self.instance.pk)
        return form

    def clean(self):
        try:
            super().clean()
        except ValidationError as error:
            base_error = error
        else:
            base_error = None
        images = {}
        for form in self.forms:
            if not hasattr(form, 'cleaned_data'):
                continue
            if self.can_delete and form.data.get(form.add_prefix('DELETE')):
                continue

            image = form.cleaned_data.get('image')
            if image is not None:
                duplicate = images.get(image.pk)
                if duplicate is not None:
                    message = _('An image can appear only once in this gallery.')
                    form.add_error('image', message)
                    duplicate.add_error('image', message)
                images[image.pk] = form
        if base_error is not None:
            raise base_error

    def validate_unique(self):
        # Position is normalized from the submitted row order on save. The
        # formset still validates duplicate images in clean() above.
        return
