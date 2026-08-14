import json
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

import nh3
from markdown_it import MarkdownIt
from django.templatetags.static import static
from django.utils.safestring import mark_safe

from apps.core.sites import PRIMARY_SITE, build_site_absolute_url

from .technologies import TECHNOLOGY_REGISTRY


class FeatureMarkdownRenderError(Exception):
    """Raised when Project feature Markdown cannot cross the HTML boundary."""


class FeatureMarkdownHeadingError(Exception):
    """Raised when Project Markdown conflicts with the public page heading structure."""


_FEATURE_MARKDOWN = MarkdownIt(
    'commonmark',
    {
        'html': False,
        'linkify': False,
    },
)
_FEATURE_TAGS = {
    'a',
    'blockquote',
    'br',
    'code',
    'em',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'li',
    'ol',
    'p',
    'pre',
    'strong',
    'ul',
}
_FEATURE_ATTRIBUTES = {
    'a': {'href', 'title'},
}
_FEATURE_URL_SCHEMES = {'http', 'https', 'mailto'}


class _ExternalLinkAttributes(HTMLParser):
    """Normalize headings and add public link attributes after sanitization."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []
        self.heading_tags = []
        self.previous_heading_level = 1

    def handle_starttag(self, tag, attrs):
        if tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            source_level = int(tag[1])
            normalized_level = max(2, min(source_level, self.previous_heading_level + 1))
            tag = f'h{normalized_level}'
            self.heading_tags.append(tag)
            self.previous_heading_level = normalized_level
            self.parts.append(f'<{tag}>')
            return
        if tag == 'a':
            attributes = dict(attrs)
            href = attributes.get('href') or ''
            if href.replace('\\', '/').startswith('//'):
                attributes.pop('href', None)
            scheme = urlsplit(href).scheme.lower()
            if scheme in {'http', 'https'}:
                attributes['target'] = '_blank'
                attributes['rel'] = 'noopener noreferrer'
            attrs = ''.join(
                f' {name}="{escape(value or "", quote=True)}"'
                for name, value in attributes.items()
            )
            self.parts.append(f'<{tag}{attrs}>')
            return
        self.parts.append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'} and self.heading_tags:
            tag = self.heading_tags.pop()
        self.parts.append(f'</{tag}>')

    def handle_data(self, data):
        self.parts.append(data)

    def handle_entityref(self, name):
        self.parts.append(f'&{name};')

    def handle_charref(self, name):
        self.parts.append(f'&#{name};')

    def handle_comment(self, data):
        self.parts.append(f'<!--{data}-->')

    def handle_decl(self, decl):
        self.parts.append(f'<!{decl}>')

    def handle_pi(self, data):
        self.parts.append(f'<?{data}>')

    def output(self):
        return ''.join(self.parts)


def _add_external_link_attributes(value):
    parser = _ExternalLinkAttributes()
    parser.feed(value)
    parser.close()
    return parser.output()


def validate_feature_markdown_headings(source):
    """Reject headings that would break the Project detail page hierarchy."""
    previous_level = 1
    for token in _FEATURE_MARKDOWN.parse(source or ''):
        if token.type != 'heading_open':
            continue
        level = int(token.tag[1])
        if level == 1:
            raise FeatureMarkdownHeadingError(
                'Use heading level 2 or lower; the project title is already the page heading.'
            )
        if level > previous_level + 1:
            raise FeatureMarkdownHeadingError(
                f'Heading level {level} skips a level after heading level {previous_level}.'
            )
        previous_level = level


def render_feature_markdown(source):
    """Render Project Markdown through the single safe HTML boundary."""
    try:
        rendered = _FEATURE_MARKDOWN.render(source or '')
        sanitized = nh3.clean(
            rendered,
            tags=_FEATURE_TAGS,
            attributes=_FEATURE_ATTRIBUTES,
            url_schemes=_FEATURE_URL_SCHEMES,
            strip_comments=True,
            link_rel=None,
        )
        return mark_safe(_add_external_link_attributes(sanitized))
    except Exception as error:
        raise FeatureMarkdownRenderError from error


def _field_url(field):
    if not field or not field.name:
        return None
    try:
        if not field.storage.exists(field.name):
            return None
        return field.url
    except (OSError, ValueError):
        return None


def _absolute_media_url(url):
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme.lower() in {'http', 'https'} and parsed.netloc:
            return url
        return None
    if not url.startswith('/') or url.startswith('//'):
        return None
    return build_site_absolute_url(PRIMARY_SITE, url)


def build_responsive_image_data(image, *, loading='lazy', sizes='(min-width: 760px) 760px, 100vw'):
    """Return safe responsive data for a ready stored ProjectImage."""
    if not image:
        return None
    try:
        if not image.is_ready_for_publication():
            return None
    except (OSError, ValueError):
        return None

    renditions = (
        (image.rendition_480, 480),
        (image.rendition_960, 960),
        (image.rendition_1600, 1600),
    )
    sources = []
    source_widths = set()
    for field, target_width in renditions:
        url = _field_url(field)
        actual_width = min(image.width, target_width)
        if not url or actual_width in source_widths:
            continue
        sources.append({'url': url, 'width': actual_width})
        source_widths.add(actual_width)
    if not sources:
        return None

    source = next((item for item in sources if item['width'] >= 960), sources[-1])
    lightbox_url = _field_url(image.rendition_1600) or _field_url(image.original)
    if not lightbox_url:
        return None

    return {
        'src': source['url'],
        'srcset': ', '.join(f"{item['url']} {item['width']}w" for item in sources),
        'sizes': sizes,
        'width': image.width,
        'height': image.height,
        'alt': '' if image.is_decorative else image.alt_text,
        'loading': loading,
        'lightbox_url': lightbox_url,
        'social_url': _absolute_media_url(_field_url(image.social_1200x630)),
        'social_width': 1200,
        'social_height': 630,
        'social_type': 'image/jpeg',
    }


def _json_ld(value):
    serialized = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return mark_safe(
        serialized.replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    )


def build_technology_data(project):
    selected = set(project.technology_stack or ())
    return [
        {
            'key': technology.key,
            'label': technology.label,
            'icon_url': static(technology.icon),
        }
        for technology in TECHNOLOGY_REGISTRY
        if technology.key in selected
    ]


def build_project_presentation(
    project,
    *,
    canonical_url='',
    fallback_social_image_url='',
    fallback_social_image_alt='Django projects',
):
    """Build the shared public and saved-preview Project presentation model."""
    cover = build_responsive_image_data(
        project.cover_image,
        loading='eager',
    )
    gallery_items = []
    for gallery_item in project.gallery_items.all():
        image = build_responsive_image_data(gallery_item.image)
        gallery_items.append(
            {
                'position': gallery_item.position,
                'available': image is not None,
                'image': image,
            }
        )

    available_gallery = [item for item in gallery_items if item['available']]
    unavailable_gallery = [item for item in gallery_items if not item['available']]
    try:
        body_html = render_feature_markdown(project.body)
    except FeatureMarkdownRenderError:
        body_html = ''
    try:
        feature_html = render_feature_markdown(project.full_feature_list)
    except FeatureMarkdownRenderError:
        feature_html = ''

    social_image_url = (cover or {}).get('social_url') or fallback_social_image_url
    social_image_alt = (cover or {}).get('alt') if cover else fallback_social_image_alt
    creative_work = {
        '@type': 'CreativeWork',
        'name': project.title,
        'description': project.summary,
        'url': canonical_url,
    }
    if cover and cover['social_url']:
        creative_work['image'] = cover['social_url']
    structured_data = {
        '@context': 'https://schema.org',
        '@graph': [
            creative_work,
            {
                '@type': 'BreadcrumbList',
                'itemListElement': [
                    {
                        '@type': 'ListItem',
                        'position': 1,
                        'name': 'Projects',
                        'item': build_site_absolute_url(PRIMARY_SITE, '/projects/'),
                    },
                    {
                        '@type': 'ListItem',
                        'position': 2,
                        'name': project.title,
                        'item': canonical_url,
                    },
                ],
            },
        ],
    }
    return {
        'title': project.seo_title or project.title,
        'description': project.seo_description or project.summary,
        'canonical_url': canonical_url,
        'cover': cover,
        'cover_unavailable': bool(project.cover_image and not cover),
        'body_html': body_html,
        'gallery_items': gallery_items,
        'available_gallery': available_gallery,
        'unavailable_gallery': unavailable_gallery,
        'gallery_caption': project.gallery_caption,
        'technologies': build_technology_data(project),
        'feature_html': feature_html,
        'social_image_url': social_image_url,
        'social_image_alt': social_image_alt,
        'social_image_width': (cover or {}).get('social_width'),
        'social_image_height': (cover or {}).get('social_height'),
        'social_image_type': (cover or {}).get('social_type'),
        'structured_data_json': _json_ld(structured_data),
    }
