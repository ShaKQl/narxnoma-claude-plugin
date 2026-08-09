# texnomart

## Product-type denylist (sweep-time crawl policy)

texnomart items carry **no category field** — verified against the recorded
fixture, unlike idea (`category_id`) and beemarket (a category endpoint).
The only usable signal is the product-type noun in the name, which is weaker
evidence, so the filter is a **denylist of things that are not phones** (see
`narxnoma/sources/not_a_phone.py`), never an allowlist of phone words: an
allowlist would silently drop any phone whose name lacks the expected noun,
and losing a real phone is worse than admitting an accessory the price fence
and the matcher still get a chance to reject.

Measured on 467 live offers (2026-08-02): **142 (30.4%) are not phones**, and
15 of them had already become canonical products — a tablet carries a brand,
a memory pair and a colour, so it forms a full key exactly as a phone does.
Two false-positive classes were caught and fixed before this rule shipped:

- `Черное стекло` — "стекло" is a screen protector AND a colour; only the
  qualified protector sense counts.
- `USB-адаптер` in a phone's marketing title — "Samsung Galaxy A37 5G: …
  USB-адаптер 8/128+ …" is a real phone with the charger in the box.
  "adapter" is therefore NOT in the denylist: a standalone charger carries
  no memory pair, cannot form a variant key, and can only ever land in
  unresolved_offer. (The previous doc's mitigation belonged to the
  target-driven matcher and does not apply at harvest time.)
