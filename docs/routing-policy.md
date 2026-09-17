# PASI Routing Policy

## Default behavior

1. Keep ChatGPT Thinking/reasoning enabled for every PASI task.
2. Reuse the current ChatGPT conversation until it is actually context-exhausted.
3. Treat the public PASI GitHub repository as the default repository context source:
   `https://github.com/th3-st0v3/personal-ai-system`
4. Do not attach the ChatGPT GitHub app just because a task mentions code, repositories, branches, commits, or GitHub.
5. Use the GitHub app only through the explicit `--github fallback` mode.

## Context and reasoning are independent

Repository context does not determine reasoning mode. A task may use public GitHub context and Thinking simultaneously.

An explicit GitHub-app fallback also does not disable Thinking.

## Compatibility

The `public` mode is the canonical default. The legacy `auto` and `always` command values remain accepted for compatibility but no longer cause automatic GitHub-app attachment. They resolve to the public-repository path.

## Conversation rollover

A new ChatGPT conversation is created only when the existing conversation is reported as context-exhausted. Account/model usage-limit messages do not themselves justify opening a replacement conversation.
