# Versioned updates

Gestion Magasin uses reconstructed product milestone versions. The first audited
release is 1.0.0 (4 June 2026); wholesale sales starts 2.0.0 (27 June 2026).
This release is 2.9.0 (9 October 2026). Development dates do not establish deployment
dates. See `changelog-history-sources.json` for 136 unique repository commits,
full hashes, subjects, bodies, changed files and the dated classifications.
The initial import contains 26 bilingual entries and preserves existing admin edits.

The authenticated read-only endpoint is `/api/ws/changelog/`. Only published entries
whose date has arrived are returned. Edit both French and English in Django admin;
one change per line. French navigation calls this page **Nouveautés**.

For subsequent releases:

1. Update the frontend package version and prepare the bilingual changelog entry.
2. Run frontend tests, TypeScript, lint/build and backend websocket/changelog tests.
3. Deploy the backend, then apply migrations and run Django checks. The current
   production push hook rebuilds containers but does **not** apply migrations.
4. Deploy the frontend and verify `/api/app-version` plus container health.
5. Publish the changelog entry and save the maintenance state with the healthy
   frontend version. Use the normal model/admin save so the post-commit websocket
   announcement runs; do not use `QuerySet.update` to announce a release.

The bundled frontend version and announced server version are separate. The modal
allows deferral and checks frontend availability before reloading the current route.
Existing tabs predating this feature need one normal refresh. Seed migrations never
announce a version. The `0.1.0` fallback is a compatibility floor only.

Dark mode uses a host-only `app-theme` cookie and the server-rendered HTML attribute.
The nested MUI providers retain Poppins and component styles while sharing the
Design Workflow dark palette. Keep printed documents and product/logo images intact.

Validation for this release uses `gestion_magasin_backend.settings_test` (SQLite),
never production data, and a separate temporary SQLite database for browser checks.
