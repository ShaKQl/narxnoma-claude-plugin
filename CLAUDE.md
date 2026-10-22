# CLAUDE.md

Working on this repo (not just using the plugin)? Load the project skill
`.claude/skills/narxnoma-maintain/SKILL.md` first, then read the **Latest state** at
the top of `docs/CHANGELOG.md`.

- `docs/parsers/` is canonical for how each store is fetched; `docs/folder-map.md`
  says where everything lives.
- This repository is **public**: no secrets, no private catalogues, no retailer's
  internal data.
- Maintenance rule: every session that changes the repo ends with a CHANGELOG entry,
  updated docs/skills, regenerated digests (`python tools/regen_digests.py`) and a commit.
