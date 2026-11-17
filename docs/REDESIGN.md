# Frontend redesign (steps 1-5)

Design system: `frontend/src/styles.css` (tokens at the top: navy #101B35, teal #0F766E, mint #D9F5EC, background #F6F8FB, Inter).

Shared UI: `components/ui/` - `NavButton` (the single component behind Shop, Alerts and Cart), `Icon` (inline SVG, no icon library),
`Brand`, `States` (empty / error / skeleton), `StatusPill`, `OrderTracker`, `Charts` (SVG bar chart and donut).

Pages by step: 1 navbar, footer, home, shop - 2 alerts, customer dashboard (`/dashboard`), orders, prescriptions -
3 pharmacist queue and review - 4 admin / manager dashboard - 5 inventory, fulfilment, delivery partner, status badges.

Rules kept: no backend or API changes; role routes unchanged (the server still enforces permissions); no new npm dependencies.
The cart link, Add to Cart and the product-page cart block are shown to customers only. That is a UI rule: the server's cart
endpoints accept any logged-in role.

Not verified in the build sandbox (npm is blocked there): run `npm run build` and click through each role before relying on it.

## Follow-up changes
- Navigation by role (`frontend/src/utils/roles.js`): only customers (and logged-out visitors) get Shop, Orders, Prescriptions, Cart and the Upload Prescription buttons.
  Staff accounts get their own work links in the top bar instead. UI only: server permissions are unchanged.
- Shop filters are one horizontal bar (Category, Prescription, Price, Sort by) above the product grid.
- Product pictures (`components/ProductImage.jsx`): the API has no image field, so each product gets its own pack illustration drawn from its name, type and category.
  If the API ever returns an `image_url` (https only) it is shown instead, and an illustration is the fallback if the photo fails to load.
  These are illustrations, not photographs. Real photos need an image field in the catalogue and rights to use the pictures.
