# Changelog

## [Unreleased] — feat/v1-pwa (stacked on feat/v1-frontend)

### Added
- **`public/sw.js`** — service worker with cache-first shell, network-first API reads, version-pruned activate handler.
- **Offline last-trip banner** — if a rider opens the app with no signal and has a saved trip in localStorage, an orange banner offers one-tap restore.
- **Real PDF download** — wires the existing button to `POST /api/pdf`, handles both JSON-signed-URL and inline streaming responses.
- **PWA icons** — `icon-192.png`, `icon-512.png` (maskable) rendered from `icon.svg`.
- **Social share card** — `og-default.png` (1200×630) rendered from `og-template.svg`. Branded headline + motorcycle silhouette + URL.
- Firebase Hosting `/sw.js` served with `no-cache` so service-worker updates propagate immediately.

### Depends on
- PR #3 (`feat/v1-pdf`) for the `POST /api/pdf` endpoint that the download button calls.
