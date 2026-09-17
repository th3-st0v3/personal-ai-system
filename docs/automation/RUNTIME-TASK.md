# Runtime Tasking

The current automation objective is to implement conditional continuation prompting and then a live task queue.

Normal prompts after initial context should be compact continuation instructions to the same conversation. Do not repost full context unless recovery/new conversation/material project change requires it.

A task remains active until verified. After verified completion, commit/promote and then select the next substantial engineering task.