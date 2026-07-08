# Review Task

Review `examples/fan-out-review/sample/rate_limiter.py` for correctness bugs.

Focus on real runtime behavior: token accounting, refill logic, boundaries, and concurrency. Report only issues that could cause incorrect rate-limiter decisions in production.

Output requirements:

- List findings only.
- For each finding, include `file:line`, severity, and evidence from the code.
- Do not edit files.
- Do not include private environment details or absolute paths.
