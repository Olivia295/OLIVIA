"""Optional system reminders (next-phase B9, decision D5; PRD SOP 5's Sunday 20:30 reminder).

Off by default; ``olivia settings`` turns them on (:mod:`olivia.notify.settings`), which
installs one scheduled job per user (:mod:`olivia.notify.jobs`). Each evening the job runs
the hidden ``olivia notify-check`` (:mod:`olivia.notify.check`), which sends at most one
content-free notification. Turning them off, or ``olivia forget --all``, removes the job.
Everything that touches the OS goes through :class:`olivia.notify.system.Host`.
"""
