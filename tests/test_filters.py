from django.http import QueryDict
from django.test import SimpleTestCase

from apps.projects.filters import (
    CATEGORY_PARAMETER,
    SEARCH_PARAMETER,
    TECHNOLOGY_PARAMETER,
    ProjectFilterOption,
    ProjectFilterOptions,
    ProjectFilterState,
    active_filters,
    normalize_search_query,
    parse_filter_state,
    serialize_filter_state,
)
from apps.projects.models import Project


class ProjectFilterTests(SimpleTestCase):
    def setUp(self):
        self.options = ProjectFilterOptions(
            categories=tuple(
                ProjectFilterOption(value, label)
                for value, label in Project.Category.choices
            ),
            technologies=(
                ProjectFilterOption('python', 'Python'),
                ProjectFilterOption('django', 'Django'),
                ProjectFilterOption('docker', 'Docker'),
            ),
        )

    def test_search_normalization_bounds_whitespace_terms_and_length(self):
        self.assertEqual(
            normalize_search_query('  one   two  three '),
            'one two three',
        )
        self.assertEqual(
            normalize_search_query(' '.join(str(number) for number in range(12))),
            '0 1 2 3 4 5 6 7 8 9',
        )
        self.assertEqual(len(normalize_search_query('x' * 220)), 200)
        self.assertEqual(normalize_search_query('   '), '')

    def test_parse_state_keeps_valid_values_and_registry_order(self):
        query = QueryDict(
            'q=  Django   tools &category=unsupported&category=themes'
            '&tech=docker&tech=stale&tech=python&tech=docker'
        )

        state = parse_filter_state(query, self.options)

        self.assertEqual(state.search_query, 'Django tools')
        self.assertEqual(state.category, Project.Category.THEMES)
        self.assertEqual(state.technology_keys, ('python', 'docker'))

    def test_parse_state_accepts_empty_category_and_discards_invalid_state(self):
        query = QueryDict(
            'category=&tech=stale&q=%20%20'
        )

        self.assertEqual(
            parse_filter_state(query, self.options),
            ProjectFilterState(),
        )

    def test_serialization_is_canonical_and_repeats_technologies(self):
        state = ProjectFilterState(
            search_query='Django tools',
            category=Project.Category.APPS,
            technology_keys=('python', 'docker'),
        )

        self.assertEqual(
            serialize_filter_state(state),
            'q=Django+tools&tech=python&tech=docker',
        )

    def test_active_count_labels_and_single_value_removal(self):
        state = ProjectFilterState(
            search_query='Django',
            category=Project.Category.APPS,
            technology_keys=('python', 'docker'),
        )

        self.assertTrue(state.is_active)
        self.assertEqual(state.active_value_count, 4)
        self.assertEqual(
            [(item.dimension, item.value_label) for item in active_filters(state, self.options)],
            [
                (SEARCH_PARAMETER, 'Django'),
                (CATEGORY_PARAMETER, 'Apps'),
                (TECHNOLOGY_PARAMETER, 'Python'),
                (TECHNOLOGY_PARAMETER, 'Docker'),
            ],
        )
        self.assertEqual(
            state.without(SEARCH_PARAMETER).search_query,
            None,
        )
        self.assertEqual(
            state.without(CATEGORY_PARAMETER).category,
            None,
        )
        self.assertEqual(
            state.without(TECHNOLOGY_PARAMETER, 'python').technology_keys,
            ('docker',),
        )
