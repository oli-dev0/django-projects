# Django Projects

I built this Django app to manage and publish the projects on my website.

It gives me one place in Django Admin to write project pages, upload images, choose the technology stack, and control which projects are public. Visitors can browse the finished pages, search by name, and filter projects by category or technology.

[View the repository](https://github.com/oli-dev0/django-projects).

[Read more about the project and live demo](https://oli-dev0.me/projects/django-projects/).

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

This is the Projects app from a larger Django website. It isn't a complete website that you can clone and run on its own.

The repository includes the models, Admin tools, image handling, migrations, public views, and tests. The main website still provides the Django settings, page templates, icons, login setup, and root URLs.

I kept that split because the Projects app owns the content and editing tools, while the website owns how the public pages look. If you want to use the code in your own project, you'll need to connect those parts to your own templates and site setup.

## Using it in another Django project

The basic process is:

1. Copy `projects/` into your project as `apps/projects/`.
2. Add `apps.projects.apps.ProjectsConfig` to `INSTALLED_APPS`.
3. Connect the included views to your URL configuration.
4. Add your own project list and detail templates.
5. Connect the small shared helpers imported from `apps.core` to the equivalent code in your project.
6. Configure media storage and run the migrations.

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

The full test suite needs the larger Django project because this repository doesn't include `manage.py`, settings, or the website templates.

Once the app is connected to a Django project, you can run its tests with:

```bash
DJANGO_SETTINGS_MODULE=config.settings.local uv run python manage.py test tests.projects
```

The Python and JavaScript files in this repository have also been checked separately for syntax errors.

## Security and privacy

Images are checked before they are processed, and Markdown is cleaned before it is shown on a public page. Drafts stay private, while Django permissions and CSRF protection cover the Admin actions.

If you use the app in production, you still need the normal Django security setup, HTTPS, private secrets, secure media storage, and sensible upload limits.

## License

Released under the [MIT License](LICENSE).
