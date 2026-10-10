# Gestion Magasin AI Assistant

Status: tested local adapter, disabled by default pending shared-model acceptance. Application: `gestion_magasin`. Reuses the centralized Chat AI Assistant package and existing shared Colibri model.

## Setup and rollback

Install existing requirements including the reviewed vendored shared wheel. Preserve a private database restore file with the established operator procedure. Run `python manage.py migrate chat_ai`, then `python manage.py sync_ai_knowledge`. This additive migration creates assistant tables and does not alter business-model columns. Native startup does not apply migrations automatically.

Keep `CHAT_AI_ASSISTANT_ENABLED=False` until acceptance and activation authorization. Supply the existing shared service's model URL, identifier and key only through private runtime configuration. Do not expose raw inference or publish credentials. Defaults:120-second model timeout,512 output tokens,30-day history retention. Disable the flag to roll back; preserve tables and confirmed-action audit history. Never drop database volumes or reverse business writes as a software rollback.

Run `python manage.py purge_ai_history` through the existing private scheduler. Expired conversations/pending actions and old read audits are removed; confirmed-action audit metadata is retained. `sync_ai_knowledge` incrementally updates twelve approved bilingual workflow documents.

## Scope, tools and actions

Native JWT and fresh user flags, StoreMembership roles, staff module guards and object scope govern all `/api/ai/v1/` endpoints. The shared contract field `company_id` contains a native Store identifier in this adapter. Browser/model hints never grant store access. The UI follows the current native store tab or asks for a permitted store.

Endpoints provide capabilities, conversation CRUD, authenticated JSON/SSE messages, record selection, exact confirmation, feedback and protected documents. Wholesale PDF queries take `company_id` and `language` (`fr`/`en`); native printing restrictions remain enforced. There is no separate login.

Tools: `search_records`, `get_record`, `navigate`, `financial_summary`, `knowledge`, `previous_results`, `sale_document`, `prepare_change`. Fourteen real native resource bindings cover catalogue, stock, requests, sales/customers, expenses, purchases/transfers/inventories, promotions, attendance/employees, stores/users. Staff-only screens remain restricted; pointage-only and vendeur-only accounts keep their existing special modes. Expanded attendance list scope does not authorize hidden detail or mutation. Related customer/employee names and search matches cannot cross store boundaries through cards/history.

Financial outputs reuse native dashboard calculations and distinguish confirmed sales, received purchases, expenses, current stock value, today's paid amounts and dashboard balance. The latter is not accounting profit. Current stock value and today’s paid amounts require both date bounds to equal the trusted current date; other periods are rejected before querying. No invented conversion, shell, SQL or generic database tool exists.

Supported changes are product names/references/barcodes, customer contacts, expense notes/labels, attendance observations/responsible and sale notes. Supported deletion excludes sales and refuses dependent products/customers. Every operation requires an owned, unexpired exact-target confirmation; permissions/dependencies/fingerprint are revalidated under locks; native views write and native history plus assistant audit identify the instructing user. Quantities, amounts, relationships, statuses, permission changes, bulk actions and stock/sale workflow transitions are unsupported. Native forms can be opened under their own permissions.

## Validation and incomplete requirements

The local full PostgreSQL suite passed 448 tests, with the final focused assistant suite passing 56 after five additional intent/current-metric regressions. Forty focused frontend tests pass. Actual dummy browser checks cover scope switching, read-only denial, safe native navigation, native PDF, confirmed deletion and actor history, fresh history, EN/FR greetings and mobile/light/dark shared UI. Test data is synthetic and isolated.

Synthetic training data is prepared centrally; no Gestion Magasin fine-tuning or accuracy score exists yet. Model-driven natural-language acceptance, server resource/performance evaluation and activation remain incomplete. Application tests do not establish model accuracy. All app stages reuse one shared model and train serially on the approved server.
