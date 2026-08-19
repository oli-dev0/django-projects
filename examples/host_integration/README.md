# Host Integration Reference

These snippets preserve the package and URL names expected by the extracted
Projects implementation and its reference frontend.

1. Copy `projects/` to `apps/projects/` and keep `site_frontend/` at the project
   root or another importable package location.
2. Add both app configs from `settings_example.py`.
3. Add the named routes from `urls.py` to a URLconf included with the
   `personal` namespace.
4. Connect `apps.core.sites` and `apps.core.image_processing` to the host's
   equivalent helpers.
5. Configure media storage, run migrations, and collect static files.

The three `personal` route names are part of the current view/template
contract; renaming them requires updating both `projects/views.py` and the
reference templates.
