from unittest.mock import Mock, patch

from django.db import DatabaseError, IntegrityError
from django.test import TestCase

from apps.projects.models import Project
from apps.projects.services import (
    FeaturedProjectOutcome,
    ProjectOrderOutcome,
    append_project,
    normalize_project_order,
    reorder_projects,
    set_featured_project,
    unfeature_project,
    unpublish_project,
)


class ProjectOrderServiceTests(TestCase):
    def project(self, slug, sort_order):
        return Project.objects.create(
            category=Project.Category.APPS,
            title=slug.replace('-', ' ').title(),
            slug=slug,
            summary=f'{slug} summary',
            sort_order=sort_order,
        )

    def order(self):
        return list(Project.objects.order_by('sort_order').values_list('pk', flat=True))

    def positions(self):
        return list(Project.objects.order_by('sort_order').values_list('sort_order', flat=True))

    def test_valid_reorder_shifts_projects_and_saves_contiguous_positions(self):
        first = self.project('first-project', 0)
        second = self.project('second-project', 1)
        third = self.project('third-project', 2)

        outcome = reorder_projects(
            [third.pk, first.pk, second.pk],
            [first.pk, second.pk, third.pk],
        )

        self.assertEqual(outcome, ProjectOrderOutcome.UPDATED)
        self.assertEqual(self.order(), [third.pk, first.pk, second.pk])
        self.assertEqual(self.positions(), [0, 1, 2])

    def test_normalization_preserves_public_ties_and_closes_legacy_gaps(self):
        older = self.project('older-project', 8)
        newer = self.project('newer-project', 8)
        last = self.project('last-project', 20)

        normalize_project_order()

        self.assertEqual(self.order(), [newer.pk, older.pk, last.pk])
        self.assertEqual(self.positions(), [0, 1, 2])

    def test_append_normalizes_existing_projects_and_uses_final_position(self):
        first = self.project('first-project', 4)
        second = self.project('second-project', 10)
        new_project = Project(
            category=Project.Category.APPS,
            title='New project',
            slug='new-project',
            summary='New project summary',
        )

        append_project(new_project)

        self.assertEqual(self.order(), [first.pk, second.pk, new_project.pk])
        self.assertEqual(self.positions(), [0, 1, 2])

    def test_invalid_submissions_do_not_change_any_positions(self):
        first = self.project('first-project', 3)
        second = self.project('second-project', 7)
        expected = [first.pk, second.pk]
        invalid_orders = (
            None,
            str(first.pk),
            [first.pk],
            [first.pk, first.pk],
            [first.pk, 999999],
            [first.pk, 'not-an-id'],
            [first.pk, 1.5],
        )

        for submitted in invalid_orders:
            with self.subTest(submitted=submitted):
                outcome = reorder_projects(submitted, expected)
                self.assertEqual(outcome, ProjectOrderOutcome.INVALID)
                self.assertEqual(
                    list(Project.objects.order_by('pk').values_list('sort_order', flat=True)),
                    [3, 7],
                )

    def test_stale_snapshot_does_not_overwrite_a_concurrent_change(self):
        first = self.project('first-project', 0)
        second = self.project('second-project', 1)
        expected = [first.pk, second.pk]
        third = self.project('third-project', 2)

        outcome = reorder_projects([second.pk, first.pk], expected)

        self.assertEqual(outcome, ProjectOrderOutcome.STALE)
        self.assertEqual(self.order(), [first.pk, second.pk, third.pk])

    def test_database_failure_rolls_back_all_position_updates(self):
        first = self.project('first-project', 0)
        second = self.project('second-project', 1)

        with patch.object(Project.objects, 'bulk_update', side_effect=DatabaseError('write failed')):
            with self.assertRaises(DatabaseError):
                reorder_projects([second.pk, first.pk], [first.pk, second.pk])

        self.assertEqual(self.order(), [first.pk, second.pk])
        self.assertEqual(self.positions(), [0, 1])


class FeaturedProjectServiceTests(TestCase):
    def project(self, slug, *, is_published=True, is_featured=False):
        return Project.objects.create(
            category=Project.Category.APPS,
            title=slug.replace('-', ' ').title(),
            slug=slug,
            summary=f'{slug} summary',
            is_published=is_published,
            is_featured=is_featured,
        )

    def test_first_selection_and_replacement_keep_one_featured_project(self):
        first = self.project('first-project')
        second = self.project('second-project')

        self.assertEqual(
            set_featured_project(first, expected_current_id=None),
            FeaturedProjectOutcome.FEATURED,
        )
        self.assertEqual(
            set_featured_project(second, expected_current_id=first.pk),
            FeaturedProjectOutcome.FEATURED,
        )

        self.assertEqual(
            list(Project.objects.filter(is_featured=True).values_list('pk', flat=True)),
            [second.pk],
        )
        self.assertTrue(Project.objects.get(pk=second.pk).is_published)

    def test_stale_confirmation_does_not_mutate_the_current_feature(self):
        first = self.project('first-project', is_featured=True)
        second = self.project('second-project')

        outcome = set_featured_project(second, expected_current_id=None)

        self.assertEqual(outcome, FeaturedProjectOutcome.STALE)
        self.assertTrue(Project.objects.get(pk=first.pk).is_featured)
        self.assertFalse(Project.objects.get(pk=second.pk).is_featured)

    def test_unpublished_proposal_is_rejected_without_mutation(self):
        draft = self.project('draft-project', is_published=False)

        outcome = set_featured_project(draft, expected_current_id=None)

        self.assertEqual(outcome, FeaturedProjectOutcome.UNPUBLISHED)
        self.assertFalse(Project.objects.get(pk=draft.pk).is_featured)

    def test_explicit_unfeature_preserves_publication(self):
        project = self.project('featured-project', is_featured=True)

        unfeature_project(project)

        project.refresh_from_db()
        self.assertFalse(project.is_featured)
        self.assertTrue(project.is_published)

    def test_unpublish_clears_featured_state_in_the_same_transition(self):
        project = self.project('featured-project', is_featured=True)

        unpublish_project(project)

        project.refresh_from_db()
        self.assertFalse(project.is_published)
        self.assertFalse(project.is_featured)

    def test_competing_expected_current_id_is_stale_and_leaves_at_most_one(self):
        first = self.project('first-project')
        second = self.project('second-project')

        set_featured_project(first, expected_current_id=None)
        outcome = set_featured_project(second, expected_current_id=None)

        self.assertEqual(outcome, FeaturedProjectOutcome.STALE)
        self.assertLessEqual(Project.objects.filter(is_featured=True).count(), 1)

    def test_competing_first_selection_constraint_conflict_returns_stale(self):
        proposed = self.project('proposed-project')
        update_query = Mock()
        update_query.update.side_effect = (0, IntegrityError('competing selection'))

        with patch.object(Project.objects, 'filter', return_value=update_query):
            outcome = set_featured_project(proposed, expected_current_id=None)

        self.assertEqual(outcome, FeaturedProjectOutcome.STALE)
        self.assertFalse(Project.objects.get(pk=proposed.pk).is_featured)
        self.assertLessEqual(Project.objects.filter(is_featured=True).count(), 1)
