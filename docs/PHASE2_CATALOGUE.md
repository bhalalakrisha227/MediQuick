# Phase 2: Product Catalogue

## New commands (from `backend`, venv active)

```powershell
python manage.py test                 # includes the new catalogue tests
python manage.py create_indexes       # now also creates catalogue indexes
python manage.py seed_demo_catalogue  # loads labelled DEMO categories/products (safe to repeat)
python manage.py runserver
```

Then run the frontend (`npm run dev`) and open http://localhost:5173 . The old setup-check page moved to `/status`.

## Public API (no login needed to browse)

| Method | Path | Purpose |
|---|---|---|
| GET | `categories/` | Active categories |
| GET | `products/` | Search/filter/sort/paginate (see below) |
| GET | `products/<slug>/` | One active product (404 if missing or deactivated) |

Query parameters for `products/`: `q` (max 60 chars; matches name, generic name, brand, case-insensitive), `category` (slug), `rx` (`otc` or `prescription`), `min_price` / `max_price` (integer paise), `sort` (`name`, `price_asc`, `price_desc`, `newest`), `page`, `page_size` (max 50). Invalid values return 400 with a `fields` object.

## Manager API (roles `pharmacy_manager` or `admin`, enforced on the backend)

| Method | Path | Purpose |
|---|---|---|
| POST | `manage/categories/` | Create a category |
| POST | `manage/products/` | Create a product |
| PATCH | `manage/products/<id>/` | Update fields |
| DELETE | `manage/products/<id>/` | Deactivate (soft delete, so order history stays valid later) |

There is no manager screen yet; use the API (the admin dashboard phase adds UI). Anonymous requests get 401, other roles get 403.

## Design decisions

- **Prices are integer paise** everywhere (no floating point). The frontend formats them as INR. Price cannot exceed MRP.
- **The prescription flag is derived, never client-supplied:** `requires_prescription = schedule != "OTC"`. Sending `requires_prescription` in a request is ignored.
- **Schedule X is blocked from online ordering** (`purchasable_online = false`) as a conservative placeholder. These rules live in `apps/catalogue/rules.py` in one place and are **not verified legal rules**. Confirm with a qualified Indian pharmacy lawyer (see `COMPLIANCE_CHECKLIST.md`).
- **Availability** was `null` in Phase 2 (nothing pretended to be in stock). From Phase 3 it comes from real inventory batches; see `PHASE3_INVENTORY.md`.
- **Search** uses an escaped, case-insensitive partial match (user text is never interpreted as a regular expression). That is simple and fine for a small catalogue; a MongoDB Atlas Search index would be the upgrade for large catalogues or typo tolerance.
- **Demo data:** every seeded product has `is_demo: true`, shows a "Demo data" badge, uses generic names, a fictional manufacturer and invented prices. It is not real product information.
- **No Add to cart button** exists, because the cart is Phase 4. Prescription products show a notice that ordering is not available yet.

## Known limits

- Category and product images are not implemented yet.
- Manager endpoints have no UI and no audit log yet (audit logging is planned for the hardening phase).
- Sorting by `newest` and by name relies on stored `name_lower` / `created_at`; products created outside the service must include them.
- The price filter inputs on the shop page apply when you leave the field.
