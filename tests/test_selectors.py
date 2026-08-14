from django.http import Http404
from django.test import TestCase

from apps.projects.models import Project
from apps.projects.models import ProjectGalleryImage, ProjectImage
from apps.projects.filters import ProjectFilterState
from apps.projects.selectors import (
    get_featured_project,
    get_public_project_filter_options,
    get_project_by_slug,
    get_project_for_preview,
    get_published_projects,
)
from apps.projects.services import reorder_projects


class ProjectSelectorTests(TestCase):
    def create_project(
        self,
        *,
        slug='test-project',
        title='Test project',
        is_published=True,
        sort_order=0,
        category=Project.Category.APPS,
        summary=None,
        body='',
        technology_stack=None,
    ):
        return Project.objects.create(
            category=category,
            title=title,
            slug=slug,
            summary=summary if summary is not None else f'{title} summary',
            body=body,
            technology_stack=technology_stack or [],
            is_published=is_published,
            sort_order=sort_order,
        )

    def test_published_project_list_is_ordered(self):
        self.create_project(slug='second-project', title='Second project', sort_order=2)
        self.create_project(
            slug='first-project',
            title='First project',
            sort_order=1,
        )
        projects = list(get_published_projects())

        self.assertEqual([project.slug for project in projects], ['first-project', 'second-project'])

    def test_saved_shared_order_reaches_public_selector_while_drafts_stay_hidden(self):
        first = self.create_project(slug='first-project', sort_order=0)
        draft = self.create_project(slug='draft-project', is_published=False, sort_order=1)
        second = self.create_project(slug='second-project', sort_order=2)

        reorder_projects(
            [second.pk, draft.pk, first.pk],
            [first.pk, draft.pk, second.pk],
        )

        self.assertEqual(
            list(get_published_projects().values_list('pk', flat=True)),
            [second.pk, first.pk],
        )

    def test_published_project_list_filters_category_in_editorial_order(self):
        second_app = self.create_project(slug='second-app', sort_order=2)
        self.create_project(
            slug='theme-project',
            sort_order=0,
            category=Project.Category.THEMES,
        )
        first_app = self.create_project(slug='first-app', sort_order=1)
        self.create_project(slug='draft-app', sort_order=0, is_published=False)

        self.assertEqual(
            list(
                get_published_projects(category=Project.Category.APPS).values_list(
                    'pk', flat=True
                )
            ),
            [first_app.pk, second_app.pk],
        )

    def test_project_filter_options_are_registry_ordered_and_ignore_draft_stacks(self):
        self.create_project(
            slug='published-project',
            technology_stack=['docker', 'python'],
        )
        self.create_project(
            slug='draft-project',
            is_published=False,
            technology_stack=['fast_api'],
        )

        options = get_public_project_filter_options()

        self.assertEqual(
            [option.value for option in options.technologies],
            ['python', 'docker'],
        )
        self.assertNotIn('fast_api', options.technology_values)

    def test_project_filters_match_category_and_every_selected_technology(self):
        matching = self.create_project(
            slug='matching-project',
            category=Project.Category.THEMES,
            technology_stack=['python', 'django'],
        )
        self.create_project(
            slug='missing-technology',
            category=Project.Category.THEMES,
            technology_stack=['python'],
        )
        self.create_project(
            slug='wrong-category',
            technology_stack=['python', 'django'],
        )

        projects = get_published_projects(
            filters=ProjectFilterState(
                category=Project.Category.THEMES,
                technology_keys=('python', 'django'),
            )
        )

        self.assertEqual(list(projects), [matching])

    def test_search_matches_all_terms_across_project_fields_and_technology_aliases(self):
        body_match = self.create_project(
            slug='body-match',
            body='A durable publishing workflow.',
            summary='A useful project.',
        )
        self.create_project(
            slug='fast-api-match',
            technology_stack=['fast_api'],
            summary='An API project.',
        )

        self.assertEqual(
            list(
                get_published_projects(
                    filters=ProjectFilterState(search_query='publishing durable'),
                )
            ),
            [body_match],
        )
        self.assertEqual(
            list(
                get_published_projects(
                    filters=ProjectFilterState(search_query='Fast API'),
                )
            )[0].slug,
            'fast-api-match',
        )

    def test_search_relevance_prioritizes_title_content_then_technology(self):
        technology_match = self.create_project(
            slug='technology-match',
            title='Portfolio entry',
            summary='A project summary.',
            technology_stack=['python'],
            sort_order=0,
        )
        content_match = self.create_project(
            slug='content-match',
            title='Portfolio entry',
            summary='Python project summary.',
            sort_order=0,
        )
        title_match = self.create_project(
            slug='title-match',
            title='Python portfolio entry',
            summary='A project summary.',
            sort_order=0,
        )

        projects = list(
            get_published_projects(
                filters=ProjectFilterState(search_query='Python'),
            )
        )

        self.assertEqual(
            [project.pk for project in projects],
            [title_match.pk, content_match.pk, technology_match.pk],
        )

    def test_search_ties_use_editorial_order_then_primary_key(self):
        later = self.create_project(
            slug='later-project',
            title='Same title',
            sort_order=2,
        )
        earlier = self.create_project(
            slug='earlier-project',
            title='Same title',
            sort_order=1,
        )

        self.assertEqual(
            [project.slug for project in get_published_projects(
                filters=ProjectFilterState(search_query='Same'),
            )],
            [earlier.slug, later.slug],
        )

    def test_get_project_by_slug_rejects_unpublished_projects(self):
        self.create_project(slug='draft-project', title='Draft project', is_published=False)
        self.create_project(slug='english-project', title='English project')

        with self.assertRaises(Http404):
            get_project_by_slug('draft-project')

    def test_featured_selector_returns_only_published_featured_project(self):
        featured = self.create_project(slug='featured-project')
        featured.is_featured = True
        featured.save(update_fields=['is_featured'])

        self.assertEqual(get_featured_project().pk, featured.pk)

    def test_detail_and_preview_selectors_preserve_gallery_order_and_preview_saved_state(self):
        project = self.create_project(slug='ordered-project')
        first = ProjectImage.objects.create(project=project, name='First', original='first.png')
        second = ProjectImage.objects.create(project=project, name='Second', original='second.png')
        ProjectGalleryImage.objects.create(project=project, image=second, position=2)
        ProjectGalleryImage.objects.create(project=project, image=first, position=1)
        draft = self.create_project(slug='saved-draft', is_published=False)

        detail = get_project_by_slug(project.slug)
        preview = get_project_for_preview(draft.pk)

        self.assertEqual(
            [item.position for item in detail.gallery_items.all()],
            [1, 2],
        )
        self.assertEqual(preview.pk, draft.pk)
        with self.assertRaises(Http404):
            get_project_by_slug(draft.slug)
