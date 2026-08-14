from django.db import connection, models
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ProjectCategoryMigrationTests(TransactionTestCase):
    migrate_from = ('projects', '0003_project_full_feature_list_project_gallery_caption_and_more')
    migrate_to = ('projects', '0004_project_category_project_projects_pub_cat_order_idx_and_more')

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        old_apps.get_model('projects', 'Project').objects.create(
            title='Existing project',
            slug='existing-project',
            summary='Existing summary',
        )

    def tearDown(self):
        MigrationExecutor(connection).migrate([self.migrate_to])
        super().tearDown()

    def test_existing_projects_receive_apps_without_a_runtime_default(self):
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        new_apps = executor.loader.project_state([self.migrate_to]).apps
        Project = new_apps.get_model('projects', 'Project')

        self.assertEqual(Project.objects.get(slug='existing-project').category, 'apps')
        self.assertIs(Project._meta.get_field('category').default, models.NOT_PROVIDED)
