# How To Source More Material

Check [SOURCED.md](SOURCED.md) first — between `core/` and `extra/`,
essentially the entire OGC-declared 3.5 core SRD (PHB + DMG + MM) plus
Epic Level Handbook and Expanded Psionics Handbook content is already
here. Most future needs are "find the right existing file," not
"source something new." This doc is for the remaining case: a ticket
needs rules text or content that genuinely isn't in this corpus yet.

## What worked this session

**Cloning a GitHub repo that already did the RTF→text conversion**, e.g.:

```bash
git clone --depth 1 https://github.com/katekorsaro/dnd3.5e-srd.git
```

This is what `core/` and `extra/` came from — a repo whose whole purpose
is converting the original WotC-distributed SRD RTFs (mirrored at
[archive.org/details/dnd35srd](https://archive.org/details/dnd35srd)) to
clean text. GitHub raw files and `git clone` are not blocked the way
direct site scraping is (see below), and the conversion work is already
done. **This is the first thing to try for any new supplement**: search
GitHub for `<supplement name> SRD json OR markdown`, the same way this
one was found.

**WebSearch for verifying a specific short passage.** Search result
snippets from Google-style search often surface exact quoted rules text
in the AI-generated summary, which is good enough to *cross-check* a
passage pulled from a primary source (that's how the Cleric/Paladin
wording was double-checked against the katekorsaro repo's text during
GC-041). Not reliable as a sole source — snippets can be paraphrased —
and unworkable for bulk import; use it for spot-checks, not sourcing.

## What did not work

All blocked in this environment — don't burn time retrying these first:

- `d20srd.org` (any path) — 403 Forbidden, bot-blocked.
- `dandwiki.com` — 403 Forbidden.
- `dungeons.fandom.com` and other Fandom wikis — 402 Payment Required
  (Fandom's bot-paywall).
- `web.archive.org` — the fetch tool refuses this host outright,
  regardless of the target page.

If a future session has different tool access (a browser-driving MCP
tool, an authenticated fetch tool, etc.) these might become viable again
— but assume they're blocked until proven otherwise, and go straight to
the GitHub-clone approach.

## Sourcing something not covered yet

For material outside the core three books (Monster Manual II–V,
Complete series, Draconomicon, Unearthed Arcana, etc.) — these are each
individually licensed. A book's own OGL Section 15 declares what part of
*that specific book* is Open Game Content; there's no single document
aggregating "everything OGC across every 3.5 book" the way the core SRD
aggregates PHB+DMG+MM. Concretely:

1. Check [SOURCED.md](SOURCED.md) — confirm it's actually missing.
2. Search for a fan-maintained conversion repo the same way the core
   corpus was found (`github <book name> srd markdown/json`). Several
   individual splatbooks have these; quality and completeness vary far
   more than the core SRD did, so check the repo's own README for scope
   before trusting it's complete.
3. If no repo exists, the source is the book itself — find its own OGL
   Section 15 / Open Game Content declaration page (usually near the
   back) and treat only what's explicitly declared there as usable;
   everything else in that book is closed content by default, unlike
   the core SRD where entire chapters are OGC.
4. Verify anything short/critical (an exact rule, a triggering
   condition) against a second independent source before encoding it
   into a data file — the same discipline GC-041 used for the alignment
   rules, and the same reason [gnosis_crawler_alignment.md §1a](../gnosis_crawler_alignment.md#1a-exact-srd-wording-ticket-gc-041-done)
   exists as a written record rather than "I'm pretty sure it says X."
5. Copy the result into `docs/srd_reference/` — a new subfolder per
   supplement (e.g. `docs/srd_reference/mm2/`) if its OGL declaration
   differs from the core SRD's, rather than dropping it into `extra/`
   and blurring which license terms apply to what.
6. Include that supplement's own license/copyright text alongside it,
   the same way `LICENSE.md` and `extra/Legal.md` do for the core SRD —
   don't rely on the top-level `LICENSE.md` to cover content it didn't
   originally ship with.
7. Add a row to [SOURCED.md](SOURCED.md) so the next ticket finds it
   without repeating this process.
8. Update `data/srd_sources/` citations (per
   [gnosis_crawler_alignment.md §1a](../gnosis_crawler_alignment.md#1a-exact-srd-wording-ticket-gc-041-done)'s
   pattern) to point at the new file, not a live URL.

## Legal reminders (apply to everything, not just new sourcing)

- Mechanics (numbers, rules, procedures) are OGC and fair game.
- Names, and setting/story elements, are frequently Product Identity —
  check the relevant book's PI list (`extra/Legal.md` for the core SRD)
  before using a name verbatim in this project's own content. See
  [SOURCED.md](SOURCED.md#monster-manual-material--extra)'s caution
  about specific monster names for a worked example.
- Every distribution of OGC must carry the license (Section 10 of the
  OGL) — that's why `LICENSE.md` sits at the top of this folder and why
  a new supplement folder needs its own copy rather than assuming the
  existing one covers it.
