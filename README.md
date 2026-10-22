# narxnoma — price-fetch engine for Uzbekistan's electronics retailers

Eleven verified retailer clients, one `Listing` contract, and a Claude Code
plugin whose skills tell an agent exactly how each store is fetched: the
endpoint, the auth, which field is the price and in what unit, how to build a
URL that opens, and the traps that silently produce wrong numbers.

Aggregator only — it reads public catalogues; it never sells.

> The price we show belongs to the exact product you are looking at, and we
> can show you which listing it came from.

## Sources

| slug | site | kind | auth | sweep | search |
|---|---|---|---|---|---|
| uzum | uzum.uz | GraphQL, multi-seller, per-SKU | anonymous self-minted token | yes | yes |
| alifshop | alifshop.uz | REST POST, multi-seller, price in tiyin | none | yes | yes |
| beemarket | market.beeline.uz | REST GET, category endpoint | none | yes | yes |
| idea | idea.uz | REST GET, brand queries, no pagination | none | yes | yes |
| mediapark | mediapark.uz | REST GET autocomplete, ~10 hits | none | **no** | yes |
| olcha | olcha.uz | REST GET, full catalogue | none | yes | client-side |
| texnomart | texnomart.uz | REST GET, broad query | none | yes | yes |
| asaxiy | asaxiy.uz | server-rendered HTML | none | yes | no |
| radius | radius.uz | Saleor GraphQL, one row per variant | none | yes | yes |
| glotr | glotr.uz | server-rendered HTML classifieds | none — **robots.txt disallows; permission required** | yes | no |
| openshop | openshop.uz | REST POST, full catalogue in ~120 requests | none | yes | yes (fuzzy) |

Categories: smartphones, televisions, laptops, acs, fridges, washers, ovens.

## Quick start — prices in one command, no database

```bash
git clone https://github.com/ShaKQl/narxnoma-claude-plugin
cd narxnoma-claude-plugin
pip install -e narxnoma-crawler            # Python >= 3.11; requests + psycopg
cd narxnoma-crawler

python -m narxnoma.cli fetch --source olcha --limit 20
python -m narxnoma.cli fetch --source uzum --category laptops > uzum_laptops.jsonl
python -m narxnoma.cli fetch --source mediapark --query "iphone 16"      # search-only source
python -m narxnoma.cli fetch --source texnomart --raw                     # keep the retailer payload
```

Output is JSON lines, one listing per line:

```json
{"store_slug": "texnomart", "source_key": "359853", "name_raw": "Vivo V70 FE 8/256GB Blue Smartfoni",
 "price": 6111000, "url": "https://texnomart.uz/product/detail/359853/", "availability": "UNKNOWN",
 "image_url": "https://mini-io-api.texnomart.uz/...", "category": "smartphones"}
```

`price` is an integer in UZS. Every value is what the retailer stated; nothing
is inferred at this layer.

## Use it as a Claude Code plugin

```
/plugin marketplace add ShaKQl/narxnoma-claude-plugin
/plugin install narxnoma@narxnoma
```

Then ask Claude for prices from any of the stores, or to add a new one. Skills:

| skill | when it loads |
|---|---|
| `narxnoma-fetch` | any request for Uzbek retailer prices; running or debugging the engine |
| `fetch-uzum` … `fetch-openshop` | one per store: endpoint, headers, price field and unit, URL rule, traps, fixture and tests |
| `adding-a-narxnoma-source` | adding a retailer; a site that looks unscrapable |

The skills are operational cards. `docs/parsers/` is the rebuild-grade source
of truth they point to; every client here was re-implemented from those notes
alone and asserted live.

## Full pipeline (with PostgreSQL)

`harvest → cluster → aggregate → report`, turning per-store listings into
canonical products with a robust price per variant and an audit trail for
every attachment.

```bash
export NARXNOMA_DSN=postgresql://narxnoma:narxnoma@localhost:5432/narxnoma
python -m narxnoma.cli cycle          # all stages, isolated; non-zero if any source is suspicious
python -m narxnoma.cli report         # coverage and freshness per source
```

Local Postgres setup: `docs/deployment/local-postgres.md`.

## Layout

| Path | What it is |
|---|---|
| `skills/` | Claude Code skills — one per store, one umbrella, one for adding a store |
| `.claude-plugin/` | plugin and marketplace manifests |
| `docs/parsers/` | canonical notes per retailer + the shared matching engine |
| `narxnoma-crawler/` | the engine: `sources/`, `matching/`, `pipeline/`, `cli.py`, fixture-backed tests |
| `narxnoma-seed/` | pre-production matcher + 14,860-row golden corpus (reference data) |
| `narxnoma-web/` | optional Next.js frontend over the Postgres catalogue |
| `docs/superpowers/` | design specs and implementation plans |
| `docs/CHANGELOG.md` | what changed, newest first, with the current state and open items |
| `docs/folder-map.md` | where everything lives and the naming conventions |
| `tools/` | maintenance scripts (digest regeneration) |
| `CLAUDE.md`, `.claude/skills/narxnoma-maintain/` | start here when *working on* the repo with an agent |

## Tests

```bash
cd narxnoma-crawler
python -m pytest -q                                     # offline, fixture-backed
python -m pytest -q -m live tests/sources/test_contract_live.py   # hits the retailers
```

## Working rules

1. `docs/parsers/` is canonical. If implementation and doc disagree, verify
   live, then fix both in the same commit.
2. Never sacrifice precision for recall. Colour is a hard identity field;
   unknown colour never equals any colour.
3. Every rejection must be explainable. Nothing is inferred that cannot later
   be audited.
4. A transport check cannot validate a matcher, and aggregate metrics cannot
   see a substitution. Diff against an independent copy of the same fact.
5. Be polite: sequential requests, 0.3–0.6 s between them, a real
   `User-Agent`, the `Origin`/`Referer` the site's own app sends. Respect
   `robots.txt`; where it forbids crawling, get permission or stop.

## For AI agents and LLM tools

- `llms.txt` — index of what to read first, per the llmstxt convention.
- `llms-engine.txt` — gitingest digest of docs/parsers, skills and the engine source (~140k tokens).
- `llms-full.txt` — gitingest digest of the whole repo minus recorded fixtures and the golden corpus (~300k tokens).
- Regenerate after changes: `pip install gitingest && python -m gitingest . -o llms-full.txt` (`.gitingestignore` is honoured), or paste the repo URL into https://gitingest.com.

## License

MIT — see `LICENSE`.
