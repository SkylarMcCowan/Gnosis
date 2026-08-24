# Model-Directed Web Research

Research mode is **on by default** in both the terminal application and the
GUI's `chat_response` path — the model decides per message whether a search
is actually worth running (see "How it works" below), so there's nothing to
turn on first. `/websearch` in the terminal (and the GUI's **Web Search**
toggle) flips it off if you want to force answers from the model's own
knowledge only, and back on again afterward.

`/deepthink` enables an evidence-led deep dive and turns web research on. In the
GUI, use the **🔬 Think** toggle. It asks the planner to investigate multiple
angles and produces a brief with: Direct answer, Evidence and source assessment,
Analysis, Alternative explanations or disagreements, Confidence and limitations,
and Sources. It is separate from `/reason`, which only selects the reasoning
model.

## How it works

1. Gnosis asks the selected local model for one research action: either answer
   or a precise SearxNG query.
2. A requested query is sent to SearxNG (with DuckDuckGo as a fallback when
   available). The result text and provenance are stored locally.
3. The model receives the strongest collected evidence and can issue another,
   narrower query. There is no artificial search-count limit for a user-run
   SearxNG service.
4. The model stops only when it returns `answer`; a repeated query also ends
   the loop to prevent an accidental cycle.

For current or disputed information—such as officeholders, election and sports
results, prices, schedules, news, or a user correction—Gnosis requires at
least one live search. If the local model fails to produce the research JSON,
Gnosis searches the user's question directly instead of silently answering from
its potentially stale training data. The first search is also anchored to the
user's question so a model does not chase a side remark. Before accepting an
early answer for one of these requests, it also asks for an official-source
refinement when the first pass has no strong source or only one source domain.

### Deep Think's research floor

Left to a single small local model deciding search-vs-answer one step at a
time, Deep Think would settle for one or two searches — that model tends to
declare the evidence sufficient well before a thorough dive would. Deep Think
therefore does not rely solely on that turn-by-turn judgment:

- Before the adaptive loop starts, it asks the model for a short **research
  plan**: 4–5 distinct, non-overlapping queries covering background,
  recent developments, data/statistics, expert or official analysis, and
  controversy or disagreement. All of those queries run up front. If planning
  fails, it falls back to one query anchored to the user's request.
- It enforces a **minimum of `DEEP_THINK_MIN_SEARCHES` (4)** searches. If the
  model tries to answer before that floor is reached, Gnosis forces another
  search using an angle it hasn't tried yet, so a lazy "answer" doesn't cut
  research short.
- It enforces a **maximum of `DEEP_THINK_MAX_SEARCHES` (10)** searches so a
  runaway local model cannot loop indefinitely.
- The final synthesis draws on up to 12 pieces of collected evidence (vs. 3
  for standard web search mode), since a multi-angle dive produces far more
  material worth citing.

These constants live next to `model_directed_web_research` in `webagent.py`.

## Evidence records

Every real search result is written to `knowledge_base/web_evidence/<id>.json`.
The records contain:

- `query`, `captured_at`, `title`, `url`, `search_provider`, and extracted
  `content`.
- `published_at` when the search provider supplied a usable date.
- `truthfulness_confidence` and `source_quality_confidence` (0–100), based on
  the URL scheme, domain class, readable-content length, and provider.
- `recency_confidence` (0–100), based on the supplied publication date. An
  unknown date is scored conservatively at 35.
- `scoring_note`, which explains that these are heuristics.

Each record also has a `metadata` object designed for filtering and future
Historian sanitation:

- `topic_categories` (for example `government_politics`, `sports`, or
  `technology`) and `keyword_tags`.
- `source_type` (`official`, `academic_research`, `journalism`, `reference`,
  or `web_publisher`) and a combined `sort_key`.
- `quality_band`, `freshness_band`, `verification_status`,
  `sanitization_status`, and `revalidation_priority`.

Use `/reindexevidence` to add or refresh this metadata on evidence captured
before the taxonomy was introduced.

`truthfulness_confidence` is a source-quality proxy, not proof that every claim
on a page is true. Claim-level truth requires corroborating sources and is not
yet implemented. The answer prompt therefore tells the model to cite source
URLs, avoid prior unverified chat claims, and say when collected evidence does
not establish an answer.

## Operational notes

- Web research is optional for stable, non-current questions. For example,
  `1 + 1` should not spend a search request.
- The loop has no numeric cap. If a local model keeps asking new, unnecessary
  queries, interrupt the response and improve the model or planner prompt.
- A search result is only as good as its extracted page text. Prefer official
  sources for government, elections, health, finance, and other high-stakes
  facts.
- The existing `/websearch` service status check confirms that SearxNG is
  reachable; it does not validate the factual quality of individual results.
