"""cron.* tools: wrapping webagent.py's existing, well-tested
cron_list_entries/cron_add/cron_edit/cron_remove/run_cron_task_now as
`cron.list`/`cron.add`/`cron.edit`/`cron.remove`/`cron.run`
(list.py/add.py/edit.py/remove.py/run.py). Registered in webagent.py's
`_register_tools()` - `cron.list` is SAFE (read-only), `cron.add`/
`cron.edit`/`cron.remove` are REQUIRES_APPROVAL since they mutate the real
system crontab, and `cron.run` (executing a task immediately) is
RESTRICTED.
"""
