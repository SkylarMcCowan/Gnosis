# Daytime background tasks

Daytime work runs only while the Gnosis GUI is open. It does not install a new
service or change the existing overnight LaunchAgent. Restart the GUI to load it.

The application owns three reusable worker threads and a priority queue capped
at 24 waiting tasks. Duplicate job keys share one future. Tasks can be cancelled;
errors are returned through futures without killing the worker pool.

Default jobs:

| Job | First check | Interval |
| --- | --- | --- |
| Discover knowledge gaps | 30 seconds after opening | 5 minutes |
| Refresh knowledge catalog and passage index | 1 minute | 15 minutes |
| Research one queued topic | 2 minutes | 30 minutes |

Research shares the existing three-topic daily budget with nightly research and
uses the previously approved SearxNG endpoint. It does not increase the daily
allowance. It leaves code modification, destructive cleanup, and broader study
to the overnight workflow. Research and indexing acquire the existing overnight
cycle lock, so they skip rather than overlap with maintenance already running.

Long jobs run in bounded child processes supervised by the worker threads. Each
has a six-minute limit. Closing the window or pressing **Pause background** cancels
queued jobs and terminates active background job process groups. The status bar
shows active task count and pause/resume controls; its tooltip includes recent
outcomes. Logs and results are under `knowledge_state/background_logs/` and
`knowledge_state/background_results/`.

## Chat and voice priority

New scheduled jobs defer while a reply or voice session is active. Local model
requests additionally share a cross-process inference lock with research, study,
and embedding calls. Foreground markers reserve priority for a whole chat turn
or voice session. Waiting background model calls cannot jump ahead. File locks
release automatically on process exit, so a crashed session cannot leave a
permanent foreground reservation.

Only one cooperating local inference request runs at a time. This reduces
competition for RAM and model compute; three worker threads do not mean three
simultaneous model generations. An already-running Ollama request is not forcibly
preempted, so a new chat may still wait for that request's response or timeout.
Streaming releases its slot on normal completion, cancellation, and generator
close. Cloud model requests do not take the local inference lock.

Model prewarming uses the same bounded pool instead of creating a new QThread for
every mode change. Pending warmups for older selections are cancelled. GUI updates
remain on the Qt main thread; existing chat, microphone and speech workers retain
their streaming and cancellation behavior. No background task receives the live
conversation context or invokes `chat_response` on a parallel thread.

## Adding a small task

Submit a short, independent function receiving a cancellation token:

```python
future = pool.submit("unique-job-key", lambda token: refresh_something(token), priority=10)
```

Use `token.check()` between operations or `token.wait(seconds)` for cancellable
waits. Do not touch Qt widgets from this function; consume its future from a GUI
timer or signal. Use an isolated subprocess for untrusted or potentially blocking
work, following `background_tasks.process_job`. Model callers should use
`core.models.chat` to participate in inference scheduling.
