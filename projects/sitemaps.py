from django.urls import reverse
from apps.core.sites import PRIMARY_SITE, build_site_absolute_url

from .models import Project


def get_sitemap_entries(*, request, site, languages):
    if site.slug != PRIMARY_SITE:
        return []

    entries = [_entry(site.slug, reverse('personal:projects'), changefreq='weekly', priority='0.8')]

    populated_categories = (
        Project.objects.filter(is_published=True)
        .order_by('category')
        .values_list('category', flat=True)
        .distinct()
    )
    for category in populated_categories:
        entries.append(
            _entry(
                site.slug,
                reverse('personal:projects-category', kwargs={'category': category}),
                changefreq='weekly',
                priority='0.7',
            )
        )

    for project in Project.objects.filter(is_published=True).order_by('slug'):
        entries.append(
            _entry(
                site.slug,
                reverse('personal:project-detail', kwargs={'slug': project.slug}),
                lastmod=project.updated_at.date().isoformat(),
                changefreq='monthly',
                priority='0.7',
            )
        )

    return entries


def _entry(site_slug, path, *, lastmod=None, changefreq=None, priority=None):
    return {
        'loc': build_site_absolute_url(site_slug, path),
        'lastmod': lastmod,
        'changefreq': changefreq,
        'priority': priority,
    }
