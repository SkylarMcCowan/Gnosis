# Nightly learning and maintenance

Gnosis learns between sessions by organizing stored sources and writing local-model
study notes. This is retrieval-backed memory development, not model-weight training.
Generated notes remain explicitly unverified and retain their source path, source
hash, and exact supporting quotations. They are never used as input for more notes.

## Installed macOS schedule

`com.gnosis.nightly` is a per-user LaunchAgent running the project's virtualenv
Python. It targets 2 AM local time and checks every 15 minutes for a missed run.
It starts only after 15 minutes of keyboard/mouse inactivity. A maintenance day
starts at 2 AM, so a catch-up after midnight belongs to the preceding night.

The user must be logged in and the machine awake to execute work. A calendar event
missed during sleep is delivered on wake; the idle gate then defers work until the
next quiet period. This does not wake or power on the Mac. Inactivity is checked
at startup; a running stage may finish after the user returns.

The installer preserves other cron jobs, backs up the old crontab and task manifest,
and removes only the previous Gnosis overnight entry after verifying launchd loaded
the replacement. The other alarms and morning prompt retain their original schedules.

Install or reinstall:

```sh
./venv/bin/python -B scripts/install_nightly.py
```

## Work performed

1. **Knowledge catalog:** recursively reads text, including legacy filenames with
   unusual extensions; excludes hidden files, symlinks, binary data, operational
   reports, and unsupported JSON containers. Stores normalized-content fingerprints,
   stable content-derived topics, keywords, extractive summaries, duplicate groups,
   and source metadata. Source bytes are preserved. The catalog groups old folders
   as well as new sources without breaking their paths.
2. **Historian:** sorts loose files, merges saved conversations, and cleans agent
   memory. Originals are archived before destructive cleanup. Web captures are only
   deduplicated when both URL and content match; changed historical versions survive.
3. **Study:** refreshes the catalog after cleanup and asks the installed local coding
   model to study up to eight sources. Requires 1–3 exact source quotations per note.
   Invalid responses are reported; older unprocessed sources get priority over recent
   failed attempts. Source hashes prevent reprocessing unchanged material. Changed or
   missing sources invalidate their notes. No downloads or cloud calls in this stage.
4. **Retrieval index:** persists passages and their metadata for subsequent sessions.
   Search still detects newly changed/deleted sources immediately. Source topics,
   keywords, and summaries are carried in passage metadata. Optional semantic search
   still uses the configured local embedding model; nightly maintenance does not
   require one or automatically install one.
5. **Code improvement and tool proposals:** run separately after knowledge work.
   Code improvement still requires a clean checkout; uncommitted work is never
   silently overwritten. Generated tools remain proposals requiring review.

A filesystem lock prevents overlapping overnight cycles. Scheduled stages run in
separate subprocesses with 10–20 minute limits, including process-group termination
on timeout. Failures are recorded and later stages still run. Failed stages retry
at most three times per maintenance day, at least an hour apart; successful stages
are not repeated on retry (except the final index refresh).

The interactive `/overnight` command uses the same maintenance functions and lock,
but runs them in-process. Use the scheduled runner below when process time limits
are needed. `/selfimprove` by itself remains the code-repair command.

## Inspect or run

```sh
./venv/bin/python -B nightly.py --status
./venv/bin/python -B nightly.py --force
launchctl print gui/$(id -u)/com.gnosis.nightly
```

`--force` deliberately bypasses daily and idle gates; it retains the overlap lock.
The normal scheduled command takes no flags. If Ollama is unavailable, basic catalog
and retrieval work can still complete; model-dependent stages report failure and retry.

- `knowledge_state/nightly.json`: stage status, attempts, timestamps, log paths.
- `knowledge_state/catalog.json`: source catalog and topic membership.
- `knowledge_state/passages.json`: persistent retrieval cache.
- `knowledge_state/learning.json`: studied sources and validation failures.
- `knowledge_state/archive/`: recoverable originals, grouped by content hash and path.
- `knowledge_base/learned_notes/`: unverified model interpretations with quotations.
- `knowledge_base/overnight_reports/nightly_YYYY-MM-DD.md`: morning report.
- `cron/logs/nightly-*.log`: per-stage and launchd logs.

To restore an archived original, locate its relative path below the hash directory
and copy it back into the project. Archives are retained; there is no automatic purge.

## Gap-driven autonomous research

The nightly `research` stage now runs between Historian and study. It detects
uncertain answers, missing or weak evidence in new chats, zero-result searches,
knowledge-related task failures, and explicitly unverified fact checks. A bounded
history scan seeds the queue from existing logs; repeated scans do not create
repeat observations. This is heuristic gap detection, not a claim that every
uncertainty or incorrect answer can be recognized.

The persistent queue ranks recurring gaps ahead of one-off questions. The local
coding model converts each gap to a generic public query; queries containing
obvious private identifiers, paths, credentials, or personal pronouns are rejected.
A local preview makes proposed disclosures reviewable. No raw conversation transcript
is sent to the search service. Generalization and the privacy filter are imperfect,
so external research requires an explicit endpoint opt-in.

The default pace is three topic attempts per UTC day, including retries and manual
runs, with at most two searches and five retained snippets per topic. An attempted
gap backs off for 1, then 2, then 4 days; after three unsuccessful attempts it is
marked exhausted for review. A worker lock prevents overlapping research. The
five-minute soft budget stops new work; the nightly subprocess has a ten-minute
hard timeout. Existing HTTP and local-model calls have their own timeouts.

Research uses genuine SearxNG results, never offline fallback text. It saves
content-addressed evidence with URLs, capture times, and the originating gap.
Assessment checks exact quotations, support from at least two distinct hosts,
absence of a model-reported contradiction, and whether the new sources can be
retrieved for the original question. `supported` means those checks passed; it
is not independent factual verification. Search snippets are explicitly labeled
as snippets. Unresolved or contradictory evidence leaves the gap open.

A supported answer may propose one related follow-up at a maximum depth of one.
Fresh research sources take priority in the subsequent study pass. Findings stay
in the research audit store; model-generated assessments do not become independent
evidence. Source snippets and source-backed study notes are available to normal
knowledge retrieval.

```sh
./venv/bin/python -B nightly.py --research-status
./venv/bin/python -B nightly.py --research-preview  # local Ollama only
./venv/bin/python -B nightly.py --stage research   # respects endpoint approval and budget
```

State and reports:

- `knowledge_state/research_queue.json`: reasons, priorities, attempts, cooldowns,
  results, and per-day budget accounting.
- `knowledge_state/research_preview.json`: generic query preview and destination.
- `knowledge_state/research_report.json`: attempted topics, sources, outcomes, errors.
- `knowledge_state/research_findings/`: citations and before/after retrieval results.

Configure `knowledge_state/research_settings.json` after approving the search
service and disclosure of generalized queries:

```json
{
  "enabled": true,
  "topics_per_night": 3,
  "allow_external_search": true,
  "approved_search_endpoint": "https://search.lozdev.com/search"
}
```

Outbound search defaults to disabled. Changing `SEARXNG_URL` requires a matching
approved endpoint. `enabled: false` disables the research stage entirely without
stopping local study or knowledge maintenance. The installed LaunchAgent loads the
updated stage list automatically; reinstalling it is unnecessary.
