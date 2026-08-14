from django.test import RequestFactory
from django.test import TestCase

from apps.core.sites import PRIMARY_SITE, SECONDARY_SITE, get_site_definition
from apps.projects.models import Project
from apps.projects.sitemaps import get_sitemap_entries


class ProjectSitemapTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_project_provider_returns_personal_list_and_detail_urls(self):
        Project.objects.create(
            category=Project.Category.APPS,
            is_published=True,
            title='English project',
            slug='english-project',
            summary='English summary',
        )

        request = self.factory.get('/sitemap.xml', HTTP_HOST='testserver')
        entries = get_sitemap_entries(
            request=request,
            site=get_site_definition(PRIMARY_SITE),
            languages=['en', 'fr', 'nl'],
        )

        self.assertIn('http://example.com/projects/', [entry['loc'] for entry in entries])
        self.assertIn('http://example.com/projects/apps/', [entry['loc'] for entry in entries])
        self.assertIn('http://example.com/projects/english-project/', [entry['loc'] for entry in entries])

    def test_project_provider_returns_nothing_for_secondary_site(self):
        request = self.factory.get('/sitemap.xml', HTTP_HOST='easymeals.fit')
        entries = get_sitemap_entries(
            request=request,
            site=get_site_definition(SECONDARY_SITE),
            languages=['en', 'fr', 'nl'],
        )

        self.assertEqual(entries, [])

    def test_project_provider_lists_each_populated_category_once(self):
        for index in range(2):
            Project.objects.create(
                category=Project.Category.APPS,
                is_published=True,
                sort_order=index,
                title=f'App project {index}',
                slug=f'app-project-{index}',
                summary='Published summary',
            )

        request = self.factory.get('/sitemap.xml', HTTP_HOST='testserver')
        entries = get_sitemap_entries(
            request=request,
            site=get_site_definition(PRIMARY_SITE),
            languages=['en', 'fr', 'nl'],
        )

        locations = [entry['loc'] for entry in entries]
        self.assertEqual(locations.count('http://example.com/projects/apps/'), 1)

    def test_drafts_and_media_state_do_not_create_public_sitemap_records(self):
        Project.objects.create(
            category=Project.Category.APPS,
            is_published=True,
            title='Published project',
            slug='published-project',
            summary='Published summary',
        )
        Project.objects.create(
            category=Project.Category.THEMES,
            is_published=False,
            title='Draft project',
            slug='draft-project',
            summary='Draft summary',
        )

        request = self.factory.get('/sitemap.xml', HTTP_HOST='testserver')
        entries = get_sitemap_entries(
            request=request,
            site=get_site_definition(PRIMARY_SITE),
            languages=['en', 'fr', 'nl'],
        )
        locations = [entry['loc'] for entry in entries]

        self.assertIn('http://example.com/projects/published-project/', locations)
        self.assertIn('http://example.com/projects/apps/', locations)
        self.assertNotIn('http://example.com/projects/themes/', locations)
        self.assertNotIn('http://example.com/projects/draft-project/', locations)
        self.assertFalse(any('/media/' in location for location in locations))
