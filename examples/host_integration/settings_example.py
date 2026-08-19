"""Safe Projects settings to adapt in the host project's settings module."""

INSTALLED_APPS += [  # noqa: F821
    'apps.projects.apps.ProjectsConfig',
    'site_frontend.apps.SiteFrontendConfig',
]

PROJECT_IMAGE_MAX_BYTES = 15 * 1024 * 1024
PROJECT_IMAGE_MAX_PIXELS = 40_000_000
