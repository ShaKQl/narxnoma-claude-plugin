# Narxnoma

Electronics price comparison for Uzbekistan. **Aggregator only** — we never sell.

The promise the whole architecture exists to keep:

> The price we show belongs to the exact phone you are looking at, and we can show you
> which listing it came from.

## Layout

| Path | What it is |
|---|---|
| `docs/superpowers/specs/` | Design specs. Start with `2026-07-27-narxnoma-design.md`. |
| `docs/superpowers/plans/` | Implementation plans, executed task-by-task. |
| `docs/parsers/` | **Source of truth** for every retailer client — exact request, response shape, price field and unit, URL construction, and the traps. |
| `narxnoma-seed/` | Verified pre-production matcher + 14,860-row golden corpus captured live 2026-07-26. Reference data; the production library supersedes `matcher.py`. |
| `narxnoma-crawler/` | Python crawler (Plans 1–3). |
| `narxnoma-web/` | Next.js frontend (Plan 4). |

## Sources

uzum · alifshop · beemarket · idea · mediapark · olcha · texnomart

Six of seven are sweepable; mediapark is autocomplete-only and must be queried per
variant. Our own storefront and warehouse are deliberately excluded — see
`docs/parsers/README.md`.

## Working rules

1. `docs/parsers/` is canonical. If implementation and doc disagree, verify live, then fix
   **both in the same commit**.
2. Never sacrifice precision for recall. Colour is a hard identity field; unknown colour
   never equals any colour.
3. Every rejection must be explainable. Nothing is inferred that cannot later be audited.
4. A transport check cannot validate a matcher — wrong matches look exactly like right
   ones until diffed against an independent source.
