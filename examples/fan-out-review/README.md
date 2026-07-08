# Fan-Out Code Review

This worked example sends the same review prompt to two bundled shims and compares the results. The reviewed file is `sample/rate_limiter.py`, a small token-bucket rate limiter with a few deliberately planted correctness bugs. The outputs below are real, lightly trimmed dispatches run with the bundled shims.

Run from the repository root:

```bash
bash scripts/opencode-shim.sh kimi-for-coding/k2p7 examples/fan-out-review/review-prompt.md > /tmp/osprep/ex-kimi.out 2>&1
bash scripts/codex-shim.sh examples/fan-out-review/review-prompt.md -c model_reasoning_effort=low > /tmp/osprep/ex-codex.out 2>&1
```

## Kimi Findings

```text
> default-build · k2p7
[...]
Findings:

- `examples/fan-out-review/sample/rate_limiter.py:70` — **High**: Refill amount uses wrong unit scale. `elapsed` is in nanoseconds (`time.monotonic_ns()`), but `elapsed * self.rate_per_second` is not divided by `1e9`, so each refill adds ~1 billion tokens per second instead of the configured rate.

- `examples/fan-out-review/sample/rate_limiter.py:70` — **High**: Bucket caps at `capacity - 1` instead of `capacity`. With `capacity=1`, `_tokens` can never refill above `0`, so no request can ever be allowed after the initial token is spent.

- `examples/fan-out-review/sample/rate_limiter.py:43-47` — **High**: `allow()` is not thread-safe. `_refill()` runs outside the lock, then `_tokens >= cost` is checked without the lock before a separate locked decrement. Two threads can both pass the check and decrement the same token, causing over-consumption.

SHIM-DONE exit=0
```

## Codex Findings

```text
OpenAI Codex v0.142.5
[...]
codex
- `examples/fan-out-review/sample/rate_limiter.py:70` - High - Refill uses nanoseconds as seconds: `elapsed = now_ns - self._updated_at_ns` is in ns, but `_tokens + elapsed * self.rate_per_second` multiplies it directly by a per-second rate. Evidence: `time.monotonic_ns()` at line 65 returns nanoseconds, so after even 1 ms at `rate_per_second=1`, this adds `1_000_000` tokens before clamping, causing requests to become allowed far too early.

- `examples/fan-out-review/sample/rate_limiter.py:70` - High - Refill clamps to `capacity - 1` instead of `capacity`: `min(float(self.capacity - 1), ...)`. Evidence: a bucket can never refill to full capacity after `_refill()` runs. With `capacity=1`, any positive elapsed time clamps `_tokens` to `0`, so `allow()` can deny the first request even though the bucket was initialized full at line 26.

- `examples/fan-out-review/sample/rate_limiter.py:43` - High - `allow()` performs `_refill()` and the availability check outside the lock, then subtracts under the lock. Evidence: two threads can both observe `_tokens >= cost` at line 44 and then both subtract at line 46, allowing more requests than available tokens and potentially driving `_tokens` negative. `_refill()` also mutates `_tokens` and `_updated_at_ns` without synchronization when called from `allow()`.

SHIM-DONE exit=0
```

## Comparing The Reviews

Both models found the same three real correctness bugs: nanoseconds treated as seconds, a refill cap of `capacity - 1`, and the check-then-act race in `allow()`. Kimi grouped the concurrency issue under `43-47`; Codex pointed at line `43` and added detail about `_updated_at_ns` being mutated without synchronization from that path.

## Revealed Bugs

- Line 70 mixes nanoseconds with a per-second refill rate.
- Line 70 clamps refill capacity to `capacity - 1`.
- Lines 43-47 perform refill/check/decrement as a race-prone check-then-act sequence.
