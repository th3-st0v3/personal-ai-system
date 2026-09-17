# PASI Automation Instructions

The unattended engineering runner should operate on substantial engineering problems by default.

Use `difficult-engineering-project-mode.md` as the workload policy and `difficult-engineering-project-prompt.md` as the task-prefix prompt.

For a one-off project, the runner accepts a task string through `--task`. Example:

```bash
./scripts/start_pasi_168h.sh --task "Build and verify ..."
```

For larger project instructions, keep the full specification in a text/Markdown file and pass its contents to `--task`; do not put credentials, tokens, cookies, or other secrets in the task.
