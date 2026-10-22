# tools/

Maintenance scripts for this repo. Read this when you need to regenerate generated
files or run a recurring repo chore. The engine's own commands live in
`narxnoma-crawler/narxnoma/cli.py`, not here.

| script | purpose | inputs | outputs | how to run | needs |
|---|---|---|---|---|---|
| `regen_digests.py` | rebuild the two gitingest digests so the repo reads as one document | the working tree; `.gitingestignore` | `llms-full.txt`, `llms-engine.txt` (UTF-8) | `python tools/regen_digests.py` · `--check` exits 1 if stale | `pip install gitingest` (0.3.x) |
