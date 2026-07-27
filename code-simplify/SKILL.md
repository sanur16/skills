---
name: code-simplify
description: "Simplify only the code changed by the current task while preserving behaviour, public contracts, and repository conventions. Use only when explicitly invoked by $code-review as its simplification child."
---

# Code Simplify

Work only inside the caller's frozen change scope. Do not commit, push, open a
PR, deploy, or broaden the task.

Respect the parent review's requested edit mode. When it requests a read-only
pass, make no edits and return only scoped simplification suggestions.

1. Read applicable repository instructions and the full changed files.
2. Identify needless indirection, duplicated changed logic, redundant state,
   confusing control flow, dead changed code, and abstractions that add no value.
3. Prefer existing local helpers and established patterns.
4. Apply only changes that clearly preserve behaviour and public contracts.
5. Keep useful boundaries for security, validation, transactions, retries,
   concurrency, and test seams.
6. Do not rewrite stable adjacent code, perform cosmetic churn, add speculative
   abstractions, or change generated output independently of its source.
7. Run the smallest relevant safe validation after editing when available.
8. Return the files changed, why each simplification is behaviour-preserving,
   validation performed, and any opportunity deliberately rejected.

If simplification would require a product or architectural choice, make no edit
and report that boundary to the parent review.
