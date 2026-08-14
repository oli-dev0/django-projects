# Projects API

No DRF or JSON API exists.

The current public interface is server-rendered HTML:

- `GET /projects/` lists published Projects.
- `GET /projects/<category>/` lists published Projects in one fixed category.
- `GET /projects/<slug>/` renders a published Project or returns `404`.

Admin preview and state-transition routes are authenticated Django Admin
surfaces, not public client APIs. Project media records, drafts, processing
errors, and editorial state are not exposed through a machine-readable public
contract.
