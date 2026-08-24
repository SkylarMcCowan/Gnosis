# Historian

`/historian` cleans, categorizes, and consolidates everything Gnosis has
stored on disk: the flat `knowledge_base/` dump, saved conversation
transcripts in `conversations/`, and each agent's `agent_memory/*.json` file.
`/historian preview` runs the same three passes in dry-run mode and reports
what would change without touching anything.

## Why it exists

Before this implementation, `/historian` was a stub that just grepped
filenames for five hardcoded keywords (`dog`, `fire`, `war`, `economy`,
`politics`). Everything else — `record_to_knowledge_base` writes, saved
conversations, and `save_agent_memory` entries — just accumulated indefinitely
as an unsorted flat dump with no cleanup path. `historian_msg` in
`sys_msgs.py` had already described the intended job ("organize the contents
of the knowledge base by categorizing entries based on topics and removing
duplicates") well before there was code behind it.

## The three passes

`historian(dry_run=False)` in `webagent.py` runs these in order and prints a
summary. Each pass is also its own function, callable independently.

### 1. `historian_clean_knowledge_base`

- **Dedupe by content hash.** Walks the whole `knowledge_base/` tree (except
  `web_evidence/`, which is deduped separately — see below), hashes every
  file, and for any hash shared by more than one file, keeps the oldest by
  mtime and deletes the rest. This catches both exact-duplicate flat files and
  duplicates against files a previous Historian run already sorted away.
- **Topic-sort unsorted files.** Only files sitting directly at the top level
  of `knowledge_base/` are sorted — anything already filed into a subfolder is
  left alone, so repeat runs stay cheap and idempotent. Sorting tries an LLM
  batch classification first (see below) and falls back to a keyword
  heuristic per file when that doesn't produce an answer.
- **Dedupe `web_evidence/` by URL.** Records in `knowledge_base/web_evidence/`
  keep their flat, id-keyed layout (other code path-joins directly to that
  directory), but when the same URL was captured more than once across
  separate research sessions, only the most recently captured record is kept.

### 2. `historian_merge_conversations`

Reads every saved file in `conversations/` (only files already persisted via
`save_conversation`/`new_conversation` — the live, unsaved `assistant_convo`
is never touched), extracts ordered user/assistant exchange pairs via
`_historian_conversation_pairs` (system messages are noise here and are
skipped), and writes each conversation as a topic-sorted Markdown file under
`knowledge_base/<bucket>/conversation_<original filename>.md`.

The source JSON is only deleted **after** the merged file is written
successfully — a disk error during the write leaves the original conversation
in place instead of silently losing it. A conversation with no user/assistant
exchanges (e.g. an empty save) is deleted without being merged and counted
under `skipped_empty`.

### 3. `historian_clean_agent_memory`

For each `agent_memory/<agent>_memory.json`:

- Drops exact-duplicate `summary` entries.
- Re-derives each entry's `topics` list via `_clean_memory_topics`. The
  original `extract_topics_from_summary` (still used by `save_agent_memory`
  when a new entry is first written) split on whitespace only, so summaries
  written as `"User: ... Response: ..."` polluted every topic list with
  literal `user:` / `response:` tokens. The cleaner strips those prefixes
  before tagging.
- Sorts entries chronologically by `date`.

This pass doesn't move anything between files or delete an agent's memory —
it only cleans up what's already in each agent's own file.

## How topic sorting actually works

Getting from "flat dump of ~280 arbitrarily-named files" to something
resembling real topic grouping took two layers, because the obvious
single-file heuristic doesn't cluster related entries on its own:

1. **`_historian_topic_bucket`** (fallback, no model call): pulls
   stopword-filtered keywords from a file's name and leading content via the
   shared `_keyword_tags` helper (also used by web-evidence tagging), then
   picks the *longest* word among the first six surviving candidates. Longest
   tends to be the actual topic noun ("watermelon", "hinduism") rather than a
   short verb or a common word that slipped past the filter. This runs
   per-file, so unrelated questions almost never land in the same bucket —
   it's a reasonable label, not real clustering.

2. **`_historian_classify_topics`** (primary path, needs Ollama): batches
   titles in groups of `_HISTORIAN_CLASSIFY_CHUNK` (10) and asks a model to
   assign each one a category, explicitly telling it to reuse a category
   across related items rather than inventing a new one-off category per
   item. This is what actually produces clusters like `finance`, `history`,
   `science`, `technology` instead of one bucket per file.

   Two things came out of testing this against the models actually installed
   locally (small, non-frontier models — this assistant runs fully local):

   - The general chat model (`MODELS["main"]`, `yi:6b` in this setup) does not
     reliably follow the instruction — in testing it echoed the input list
     back verbatim instead of classifying it. `_historian_classify_topics`
     therefore always uses `MODELS["coding"]` for this call regardless of
     which chat mode is currently active, since a coding-tuned model turned
     out far more reliable at returning well-formed JSON.
   - Even the coding model occasionally returns an array that's the wrong
     length for the batch size. Larger batches (30 items) failed noticeably
     more often than small ones; `_HISTORIAN_CLASSIFY_CHUNK = 10` combined
     with `_HISTORIAN_CLASSIFY_ATTEMPTS = 2` (one retry) was the point where
     failures became infrequent enough to be worth it. When a chunk still
     fails after retrying, every item in it falls back to
     `_historian_topic_bucket` individually — the whole pass degrades
     gracefully per-chunk rather than failing the whole run.
   - Category name spelling still drifts slightly between chunks classified
     independently (`current-events` vs. `current_events`). Separator
     characters are normalized before use (`re.sub(r"[\s-]+", "_", ...)`), but
     semantically-equivalent names with different wording (`tech` vs.
     `technology`) are not merged. This is a known limitation of running
     classification per-chunk with a small local model rather than a single
     global pass; treat it as "mostly clustered," not perfectly deduped.

`historian_merge_conversations` reuses the exact same
`_historian_classify_topics` function (its own batch, since conversations and
knowledge_base files are classified separately) so a merged conversation and
a knowledge_base file about the same subject are reasonably likely to land in
the same bucket, though it's not guaranteed across the two separate batches.

## A bug worth knowing about if you touch the sort logic

A topic bucket name can collide with an existing **flat file** of the same
name at the top level of `knowledge_base/` — for example, a legacy file
literally named `help` and a bucket the classifier also calls `help`.
`os.makedirs(path, exist_ok=True)` still raises `FileExistsError` in that
case, because `exist_ok` only tolerates the target already being a
*directory*, not a file.

This was caught by actually running the real (non-dry-run) path against a
sandboxed copy of production data, not just the dry-run preview — dry-run
never calls `os.makedirs` at all, so it can't surface this class of bug. Two
defenses now handle it:

- `historian_clean_knowledge_base` stages every file to be sorted into a
  temporary `.historian_staging/` directory first, then fans them out into
  their bucket directories. This avoids the collision in the common case,
  since by the time buckets are created, no top-level files are still in the
  way (they're all in staging).
- `_historian_ensure_bucket_dir` is a defensive fallback used everywhere a
  bucket directory gets created (including in conversation merging): if the
  target path exists and is not a directory, it appends a numeric suffix
  until it finds one that's either free or already a directory.

If you add a third call site that creates a bucket directory, use
`_historian_ensure_bucket_dir`, not a bare `os.makedirs`.

## Operational notes

- `/historian` mutates and deletes files for real; `/historian preview` (or
  `/historian --dry-run`) runs every pass with all filesystem writes and
  deletes skipped, so you can see projected `buckets` counts and merge/dedupe
  totals first.
- All three passes are individually safe to call from Python directly
  (`historian_clean_knowledge_base()`, `historian_merge_conversations()`,
  `historian_clean_agent_memory()`), each returning its own stats dict, if
  you want to run just one.
- Classification calls Ollama and therefore does real local-model inference —
  a first run over a large unsorted backlog (dozens of chunked calls, each
  with up to one retry) takes real wall-clock time. Once the backlog is
  sorted, later runs only classify newly-added top-level files, so the
  ongoing cost is small.
- If Ollama is unavailable, `_historian_classify_topics` returns `None` for
  every title and both sorting passes fall back entirely to the keyword
  heuristic — Historian still dedupes and files everything away, just with
  less thematic clustering.
