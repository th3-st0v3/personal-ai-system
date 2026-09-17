# Runtime implementation next

Implement, test, and integrate conditional continuation prompting. Do not resend the entire project context on every ChatGPT turn. Use the same valid conversation, send a compact `Continue working...` prompt while the active task remains unfinished, and reconstruct context only when continuity is lost or a project/task changes materially.

After the active task passes verification, commit/promote the increment and start the next substantial task from the ordered engineering roadmap.