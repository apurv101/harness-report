You are looking at the source of an AI agent harness — a program that drives a language model through a loop of tool calls to get work done. The current directory is its repository.

Decide what this harness is FOR, so that the right benchmark tasks can be picked to test it. Read the README first, then whatever shows the tools it gives the model and the prompts it uses (system prompts, tool definitions, example configs). Do not run anything; read only.

Answer with:

- use_case: one plain sentence a user of this harness would recognise ("fixes failing tests in a Python repo from the terminal", "answers questions about a company's CRM data").
- domains: 1–4 from the allowed list, most central first. A general coding agent is `swe`; add `data-sql`, `devops-sre` etc. only when the harness has real support for that work (tools, prompts, docs), not because a user could ask it anything.
- languages: the programming languages it is built to write or edit. For a general coding agent, the ones its docs, tests or prompts actually mention.
- capabilities: from the allowed list, only what the code shows it can do.
- not_for: plain limits (e.g. "cannot run code", "no web access", "GUI only").
- evidence: the files and lines you based this on.

Be specific and conservative. If the repository is not an agent harness at all, say so in use_case and pick `other`.
