---
description: Use when creating git commits, writing commit messages, or when about to run git commit -- enforces structured commit message format with imperative mood, capitalized subjects, 72-char wrapping, and atomic commits
mode: subagent
model: nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b
---

Every commit message follows a consistent format. The subject line completes the sentence: **"If applied, this commit will _\<your subject line\>_"**. When present, the body explains **why**, not what.

Follow existing instructions for commits if present in the repository. Check `git log --oneline -20` to see recent patterns and match the existing style.

**Project convention always wins.** The rules below are the default when no convention is detected.
