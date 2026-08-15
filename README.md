# Django Projects

I built this Django app to manage and publish the projects on my website.

It gives me one place in Django Admin to write project pages, upload images, choose the technology stack, and control which projects are public. Visitors can browse the finished pages, search by name, and filter projects by category or technology.

[Read more about the project](https://oli-dev0.me/projects/django-projects/).

[View a live demo](https://oli-dev0.me/projects/).

## What it includes

- Public project list and detail pages.
- Search and filters for categories and technologies.
- Drafts, previews, publishing controls, and one featured project.
- Project covers and image galleries with responsive image sizes.
- A simple way to reorder projects and gallery images in Django Admin.
- Markdown for longer descriptions and feature lists.
- SEO details such as canonical links, social images, and sitemap entries.
- Tests for the models, views, Admin tools, images, filters, and publishing rules.

The public pages still work without JavaScript. JavaScript adds small improvements such as automatic filters, gallery dialogs with keyboard and touch navigation, and drag-and-drop ordering in Django Admin.

## What this repository is

This is the Projects app from a larger Django website, together with a small
reference frontend based on the layout I use on my site. It still isn't a
complete website that you can clone and run on its own.

The repository includes the models, Admin tools, image handling, migrations,
public views, tests, and the `site_frontend` app with reference templates,
styling, fonts, icons, and JavaScript. The host website still provides the
Django settings, login setup, shared helpers, and root URLs.

I kept that split because the Projects app owns the content and editing tools,
while the frontend owns how the public pages look. You can use the included
frontend as a starting point, or replace it with templates from your own site.
Either way, you'll need to connect the app to your own Django settings and URL
configuration.

## Using it in another Django project

The basic process is:

1. Copy `projects/` into your project as `apps/projects/`.
2. Add `apps.projects.apps.ProjectsConfig` to `INSTALLED_APPS`.
3. If you want to use the reference frontend, copy `site_frontend/` into your
   project and add `site_frontend.apps.SiteFrontendConfig` to
   `INSTALLED_APPS`.
4. Connect the included views to your URL configuration.
5. Keep the reference templates, or replace them with your own project list and
   detail templates.
6. Connect the small shared helpers imported from `apps.core` to the equivalent
   code in your project.
7. Configure media storage and run the migrations.

The reference frontend keeps its templates and static assets under the
`site_frontend` namespace. Its stylesheet uses relative asset paths, so it can
also work with a custom `STATIC_URL` or an asset host.

The app uses Pillow for images, `markdown-it-py` and `nh3` for safe Markdown, and `django-otp` for the protected Admin tests.

There are two optional image limits you can change in your Django settings:

```python
PROJECT_IMAGE_MAX_BYTES = 15 * 1024 * 1024
PROJECT_IMAGE_MAX_PIXELS = 40_000_000
```

Uploads can be JPEG, PNG, or WebP. Animated images are rejected, and the app creates smaller versions for different screen sizes.

## Documentation

If you want to look closer at how it works, start here:

- [Overview](docs/overview.md)
- [Database models](docs/database.md)
- [Services and selectors](docs/services-selectors.md)
- [Design decisions](docs/decisions.md)
- [Public pages](docs/api.md)
- [Tests](docs/tests-backend-web-api.md)

## Tests

The full test suite needs the larger Django project because this repository
doesn't include `manage.py`, settings, or root URL configuration.

Once the app is connected to a Django project, you can run its tests with:

```bash
DJANGO_SETTINGS_MODULE=config.settings.local uv run python manage.py test tests.projects
```

The Python and JavaScript files in this repository have also been checked separately for syntax errors.

The reference frontend's asset and fallback checks can run without the host
project:

```bash
python3 -m unittest tests.test_reference_frontend_assets
```

## Security and privacy

Images are checked before they are processed, and Markdown is cleaned before it is shown on a public page. Drafts stay private, while Django permissions and CSRF protection cover the Admin actions.

If you use the app in production, you still need the normal Django security setup, HTTPS, private secrets, secure media storage, and sensible upload limits.

## License

Released under the [MIT License](LICENSE).
