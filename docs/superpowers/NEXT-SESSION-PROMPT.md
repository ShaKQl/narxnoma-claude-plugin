# Handoff prompt — Plan 3, Tasks 2 onward

Copy everything inside the fence into a fresh Claude Code session started in
`D:\ASUS\Desktop\narxnoma`.

---

```
Continue building Narxnoma, an electronics price-comparison platform for Uzbekistan.
Work in D:\ASUS\Desktop\narxnoma. You are resuming mid-project — read before acting.

FIRST, in this order:

1. Read .superpowers/sdd/progress.md end to end. It is the ledger: every task done,
   every defect found, every item deliberately deferred, and why. Trust it and `git log`
   over any assumption. Do not re-do work it marks complete.
2. Read docs/superpowers/plans/2026-08-01-narxnoma-clustering.md — the plan you are
   executing. Plan 3 Task 1 is DONE; you start at Task 2.
3. Read docs/superpowers/specs/2026-07-27-narxnoma-design.md for why the platform exists.

STATE
- Branch feat/clustering, at commit e00bb70, working tree clean.
- Plans 1 (matching engine) and 2 (seven retailer clients + harvest to Postgres) are
  merged to main. Plan 3 Task 1 (variant / variant_price / unresolved_offer schema) is
  committed on this branch.
- 286 tests pass, 8 deselected.

BEFORE RUNNING ANY TEST — start the local PostgreSQL, which does not survive a reboot or
a session ending:

    .local/pgsql/bin/pg_ctl.exe -D D:/ASUS/Desktop/narxnoma/.local/pgdata \
      -l D:/ASUS/Desktop/narxnoma/.local/pg.log -o "-p 55432" start

Do NOT add -w; it blocks under Git Bash. Confirm with:

    .local/pgsql/bin/pg_isready.exe -h 127.0.0.1 -p 55432

Then, from narxnoma-crawler/:

    export NARXNOMA_TEST_DSN="postgresql://narxnoma@127.0.0.1:55432/narxnoma_test"
    python -m pytest tests/ -q

NARXNOMA_TEST_DSN is the TEST variable. NARXNOMA_DSN is the PRODUCTION one and must
never be used for tests — the db fixture truncates its database on every db-marked test,
and doing that on the server would destroy live crawler data. A guard refuses any
database whose name lacks "test". Details in docs/deployment/local-postgres.md.
A green run with NARXNOMA_TEST_DSN unset proves nothing: the db tests silently skip.

HOW TO WORK
Use the superpowers:subagent-driven-development skill and follow it properly:
- Pre-flight the plan first. Every pre-flight so far has found real defects in the plan
  itself — a test that asserted nothing, a NOT NULL that could not hold, offers parked
  forever with no retry. Scan Tasks 2-8 for the same before dispatching anything.
- One implementer subagent per task, then a reviewer subagent, then fix, then re-review.
- Generate each task brief with:
    bash "C:/Users/ASUS/.claude/plugins/cache/claude-plugins-official/superpowers/6.1.1/skills/subagent-driven-development/scripts/task-brief" \
      "docs/superpowers/plans/2026-08-01-narxnoma-clustering.md" <N>
- Generate each review package with the sibling script review-package BASE HEAD.
- Append one line per completed task to .superpowers/sdd/progress.md, and record every
  open finding there. Conversation memory does not survive; that file does.
- Verify claims yourself with small throwaway scripts against the real corpus and the
  real database. Nearly every serious bug in this project was found that way, not by
  reading. Delete the scripts afterwards.

THE TWO TASKS THAT MATTER MOST

Task 2 — _SKU_MIN_LEN. narxnoma/matching/features.py drops mixed letter+digit tokens of
length >= 5 as SKU codes, so "reno15" (7 chars) is discarded and every OPPO Reno yields
empty model_tokens: unkeyable, and score_match(Reno15, Reno14) = 45, above the accept
threshold of 30. MEASURE candidate boundaries against the 14,860-row golden corpus at
narxnoma-crawler/tests/fixtures/golden/ and report the table BEFORE choosing a value.
Do not pick a number and justify it afterwards. This comes before clustering on purpose:
clustering writes permanent canonical identities, so a model token wrongly discarded then
becomes a permanently wrong catalogue rather than a transient error.

Task 4 — clustering. This is where the platform's entire competitive claim becomes code.
The incumbent (uzprice.uz) pools colour variants, so on 23% of its multi-store pages the
headline price belongs to a different colour than the page title — worst measured case
9.3% understated. Our answer is: never guess. An offer whose partial key matches two
canonical variants goes to unresolved_offer with a reason; it does not get attached.
Getting that refusal right matters more than coverage.

RULES THAT ARE NOT NEGOTIABLE
- Colour is a hard identity field. Unknown colour never equals any colour.
- RAM is identity only for brands that publish it; Apple does not.
- Never guess an ambiguous offer. Park it with a reason and count it.
- docs/parsers/ is the source of truth for retailer behaviour. If code and doc disagree,
  verify live, then fix BOTH in the same commit.
- Every price is an integer in SUM, inside 100,000-100,000,000.
- Do not weaken a test to make it pass. Do not lower a floor to silence an alert.

Start by reading the ledger, then pre-flight the plan, then begin Task 2.
```

---

## Why the ledger matters more than this prompt

`.superpowers/sdd/progress.md` is ~370 lines and records not just what was built but what
was *found* — including the defects that a green test suite could not see. Some of those
are still open and will bite the next person who touches that area:

- `_SKU_MIN_LEN` making OPPO Reno models unkeyable (Task 2 fixes this).
- `brand_queries.py` doubles as the crawl frontier for three sources, so a brand missing
  from it means zero offers, not one degraded name.
- texnomart has no category filter at all, so any accessory over 100,000 SUM enters
  `offer` as a phone.
- The same pagination shape is duplicated across six clients; six `TODO(plan-3)` markers
  point at hoisting it.
- Recorded fixtures are single snapshots — they cannot catch category renumbering or a
  pagination-semantics change. The `live` contract tests are the counterweight and are
  currently unscheduled.

Before the first unattended full sweep: record an Apple-query uzum fixture, schedule the
`live` tests weekly, and add a `pg_try_advisory_lock` single-instance guard.
