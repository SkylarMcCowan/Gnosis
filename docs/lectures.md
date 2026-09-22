# Long-form lectures

Enter `/lecture <topic>` in terminal or GUI chat, for example:

```
/lecture How stars form and evolve. Assume basic science knowledge and explain the physics with examples.
```

Gnosis plans six sections, runs a focused web search for each, and writes each
section in a separate model call using your selected model. It targets 600–900
words per section (roughly 3,600–5,400 words total); actual length depends on the
model. Include audience level and preferred focus after the topic.

The outline and the previous section's ending provide continuity without putting
the entire lecture into every model request. Sources are included in writing
context and collected at the end. Citations are model-generated and are not an
independent fact check. When a search fails or returns only offline fallback
results, the section is explicitly marked as relying on model knowledge.

Text streams into chat and is saved progressively to a unique Markdown file in
`lectures/` under the project data root. The draft path appears in progress and
the completed path appears at the end. GUI Stop or terminal interruption retains
the partial file, marked incomplete. Rerunning creates a new file rather than
resuming. Lectures research even when the ordinary web-search toggle is off.
