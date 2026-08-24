# Commands

Generated from `/help`'s real output - do not hand-edit; run `python3 scripts/generate_docs.py` instead.

```text
Commands:
/archives [topic] - Search knowledge base for [topic]
/askwiki [query] - Query Wikipedia and interpret the information
/new - Save current conversation and start a new one
/conversations - List saved conversations
/loadconv <filename|index> - Load a saved conversation by name or list index
/clear - Reset conversation
/coding - Toggle coding mode (nous-hermes2:10.7b)
/cron - Show cron help (add/edit/list/remove/run scheduled tasks; see docs/cron.md)
/cron list - List every crontab entry, numbered
/cron add <min> <hour> <day> <month> <weekday> prompt|feature|alarm: <text> - Schedule a task
/cron edit <n> <min> <hour> <day> <month> <weekday> prompt|feature|alarm: <text> - Change entry #n in place
/cron alarm <time description> message: <text> - Set an alarm/timer from natural time phrasing
/cron remove <n> - Remove crontab entry #n (asks to confirm)
/cron run <n> - Run a Gnosis-managed crontab entry #n right now
/delpath [topic] - Delete the learning path for the given topic
/exit - Save and exit
/historian - Dedupe/sort knowledge_base, merge saved conversations into it, clean agent_memory
/historian preview - Same as /historian but only reports what would change
/help - Show help
/job [agent] - Switch to specialized agent persona (research, philosophy, space, ethics, creative, scheduler, ...)
/news - Fetch latest news headlines
/password [-N] - Generate N (default 5) complex passwords, each 20 characters
/profile - Show current user profile
/profile persona <value> - Set a profile persona tone
/persona <value> - Shortcut to set persona tone
/deepthink - Toggle evidence-led, structured web research
/reason - Toggle reasoning mode (deepseek-r1:14b)
/reindexevidence - Add or refresh sortable metadata on saved web evidence
/showpath [topic] - Show the learning path for the given topic
/tarot - Perform a single-deck Tree of Life Tarot reading
/tutor [topic] - Create a learning path for the given topic
/tts - Toggle TTS mode (read responses aloud)
/unfiltered - Toggle unfiltered mode (r1-1776:70b)
/selfimprove - Propose, apply, test, and validate one small repo fix (reverts on failure, never auto-commits)
/selfimprove preview (or --dry-run) - Same as above, but never touches the live repo - reports the verified diff instead
/learning - Report recent self-improve success rate, failure patterns, and lessons learned
/generate - Design, generate, and sandbox-test a new tool for a recurring capability gap (proposal only, never auto-registered)
/report - Observability report: task completion, search quality, tool usage, self-improve/tool-generation performance
/overnight - Run the overnight learning cycle now (self-improve + tool generation + a combined report) - same as the nightly cron trigger
/voice - Toggle voice mode (for live input)
/websearch - Toggle web search (ON by default; the model decides per message whether to search)
/ytdl <url> - Download YouTube video in highest quality to ~/Downloads

💡 Pro Tip: Use @keyword@ tags in any message to search for current info!
   Example: 'When are @midterm elections@ happening?'
```
