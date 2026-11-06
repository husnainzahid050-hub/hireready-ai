---
competency: git_collaboration
title: Git and Collaboration
levels: [junior, mid]
---

# Git and Collaboration

## What interviewers evaluate

- Everyday Git: commits, branches, merges, resolving conflicts.
- Pull request workflow and code review etiquette.
- Writing clear commit messages and keeping changes small.
- Recovering from mistakes safely.
- For mid level: rebase vs merge tradeoffs, branching strategies, CI integration.

## Question bank

### Junior

#### Walk me through how you contribute a feature using Git.

**Strong answer includes:** pull latest main, create a feature branch, make small focused commits with
clear messages, push and open a pull request, respond to review, keep the branch updated, merge
after CI passes, delete the branch.

**Common weak answers:** "I commit to main and push."

**Red flags:** has never used branches or pull requests.

#### How do you resolve a merge conflict?

**Strong answer includes:** Git marks conflicting hunks; read both sides and understand the intent of
each change, edit to the correct combined result, remove markers, run the tests, then commit;
talk to the other author if unsure.

**Common weak answers:** "I accept my changes."

**Red flags:** deletes the other person's work without checking.

#### What makes a good commit message?

**Strong answer includes:** a short imperative summary ("Add CV upload validation"), optional body
explaining why; one logical change per commit; conventions like Conventional Commits (`feat:`,
`fix:`).

**Common weak answers:** "update", "fix stuff".

**Red flags:** commits secrets or huge unrelated changes together.

### Mid

#### When would you rebase instead of merge?

**Strong answer includes:** rebase replays your commits on top of the latest main for a linear
history, good for local feature branches before opening a PR; merge preserves the true history and
is safer for shared branches; never rebase commits others have already pulled.

**Common weak answers:** "Rebase is better."

**Red flags:** force-pushes to shared branches casually.

#### You accidentally committed an API key. What do you do?

**Strong answer includes:** treat the key as compromised and rotate it immediately at the provider,
because removing it from Git does not un-leak it; then remove it from history if needed, add the
file to `.gitignore`, load secrets from environment variables, and consider secret scanning in CI.

**Common weak answers:** "Delete it in the next commit."

**Red flags:** does not rotate the key.

## Scoring anchors

Example question: "How do you give useful feedback in a code review?"

### Score 1/5

"I approve it if it runs." No review practice.

### Score 3/5

"I check for bugs and style issues and leave comments." Generic.

### Score 5/5

"I first understand the goal of the PR, then check correctness, edge cases, tests, and security.
I separate blocking issues from optional suggestions, explain the why, suggest concrete
alternatives, and keep the tone about the code, not the person. I also call out things done well."
Structured, kind, and specific.

## Resources

- [Pro Git book](https://git-scm.com/book/en/v2): the free official Git book.
- [GitHub Docs: Pull requests](https://docs.github.com/en/pull-requests): official PR workflow docs.
- [Atlassian: Comparing Git workflows](https://www.atlassian.com/git/tutorials/comparing-workflows): branching strategies explained.
