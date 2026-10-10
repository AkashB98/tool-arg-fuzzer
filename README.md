# tool-arg-fuzzer

**Find the crash paths in your agent's tool handlers before your users do.**

An **agent** — an AI program that takes actions by calling tools — hands each tool a bag of arguments. Those arguments come from an LLM, which means they are creative in exactly the ways your code didn't expect: a string where a number should be, a 64 KB blob, nesting 25 levels deep, a `null` where a name was required. This project is a **seeded** — reproducible from a starting number — **property-based** — testing general properties ("never crashes") instead of hand-written examples — **fuzzer** — a program that throws weird inputs at code on purpose — for agent tool-call arguments. Give it a tool's **JSON Schema** — a standard for declaring the required shape of JSON data — and it generates a deterministic corpus of adversarial payloads, feeds them to your tool handler, classifies every crash, and shrinks each one to a minimal repro.

Where it sits in this portfolio's agent-shipping story: `structured-output-validator` makes tool-call outputs safe at **runtime** — while the agent is actually running; **this one finds the crash paths in CI** — continuous integration, the automated checks that run on every code change — *before* the validator ever sees them. Fuzz the args → harden the handler → the validator only ever sees clean rejections.

## What it does

1. **Corpus generator** (`fuzzer.py`) — `generate_corpus(schema, seed)` builds a deterministic payload list from a JSON Schema: one valid baseline (the control case) plus a fixed **mutation** — one deliberate corruption of an input — catalog per property, then global mutations. Same `(schema, seed)` → byte-identical corpus on any machine: full replay from the seed, no stored fixtures needed.
2. **Runner** (`runner.py`) — feeds every payload to a target function and classifies the outcome: clean, **expected rejection** — a declared, handled error like `ArgumentError`, not a crash — or **unexpected crash** — any other exception. Each crash records its **crash signature** — the exception class identifying the bug — the mutation that produced it, and a **minimal repro** — the smallest input that still triggers the same crash.
3. **Shrinker** (`shrink.py`) — **delta debugging** — an algorithm that deletes parts of a failing input until only the trigger remains — reduces each crashing payload to the smallest input that still crashes with the same exception class (e.g. a 10 KB `huge_array` payload → `{"title": null}`, 14 bytes).
4. **Demo targets** (`targets.py`) — a deliberately fragile `fragile_create_work_order` / `fragile_place_order` (straight-line code that assumes perfect input) and a validated `robust_create_work_order` that proves the point: the fuzzer finds 31 crashes in the fragile one and **zero** in the robust one — every adversarial payload is either accepted or cleanly rejected.
5. **CLI** (`cli.py`) — `fuzz` / `run` / `demo` / `serve`. `run` exits 0 = no unexpected crashes, 1 = crashes found, 2 = error, so a pipeline can gate on it as a **CI gate** — an automated check that blocks bad code from shipping. `serve` exposes a tiny JSON API (`POST /fuzz`) on localhost.
6. **One-command demo** (`demo.py`) — generates the corpus, fuzzes both targets, asserts the fragile one crashes (with shrunk repros) and the robust one doesn't. Asserts internally, so it doubles as a smoke test.

## Quickstart

```bash
# one-command end-to-end (deterministic corpus -> fragile crashes -> robust clean)
python3 demo.py

# CI gate: exit 0 = no unexpected crashes, 1 = crashes found, 2 = error
python3 cli.py run --schema create_work_order --target fragile_create_work_order --seed 7
python3 cli.py run --schema create_work_order --target robust_create_work_order --seed 7

# just generate the corpus (prints payload count + md5 fingerprint)
python3 cli.py fuzz --schema place_order --seed 7

# export the corpus as JSONL for the validator pipeline (each line's
# "payload" is a validator-ready arguments object)
python3 cli.py fuzz --schema create_work_order --seed 7 --corpus-out corpus.jsonl

# tiny JSON API on :8766 (localhost only)
python3 cli.py serve --port 8766
# POST /fuzz {"schema": "create_work_order", "seed": 7, "target": "fragile_create_work_order"}
# GET  /schemas
```

Stdlib only — no dependencies, no network at runtime (the test suite stubs sockets to prove it).

## How it works

```
schemas.py: create_work_order / place_order (fictional Helios Home tool args)
        │  fuzzer.py: generate_corpus(schema, seed)   [random.Random(seed) only]
        ▼
corpus: [valid_baseline, missing_required, null_required, type_swap_*,
         empty/giant/whitespace/unicode/control strings,
         below_minimum/above_maximum/huge_int/float_for_int,
         enum_outside/case_flipped, empty/huge/deep arrays,
         deep_nesting objects, extra properties, top-level non-objects, ...]
        │  runner.py: run_corpus(target, corpus)
        ▼
classification: clean | expected rejection (ArgumentError) | UNEXPECTED CRASH
        │  shrink.py: shrink(payload, still_crashes)   [delta debugging]
        ▼
report: crash signature, mutation, arg path, original + minimal repro (sha256)
        ▼
cli.py: run (exit 0/1/2) · fuzz · serve · demo
```

**Mutation catalog** (applied per property in sorted order, then global mutations in fixed order — the full list is pinned by `test_mutation_catalog_coverage`):

| Family | Examples |
|---|---|
| Required-ness | `missing_required`, `null_required` |
| **Boundary values** — inputs at the exact edge of what's allowed | `below_minimum`, `above_maximum`, `below_min_length`, `above_max_length`, `empty_array`, `above_max_items` |
| **Type swaps** — a value of the wrong type in the right field | `type_swap_string_to_int`, `float_for_integer`, `string_for_boolean`, `numeric_string_for_number` |
| Strings | `empty_string`, `giant_string` (64 KB), `whitespace_only`, `unicode_invisible` (zero-width chars), `unicode_rtl_override`, `control_chars` (`\x00`), `unicode_bomb` (2k emoji) |
| Numbers | `huge_integer` (2⁶³), `huge_float` (1e308), `nan_string_for_number` ("NaN") |
| Enums | `enum_outside_value`, `enum_case_flipped`, `enum_empty_string` |
| Arrays | `huge_array` (5,000 items), `deep_nesting_array` (20 levels), `wrong_item_types` |
| Objects | `deep_nesting_object`, `deep_nesting_extra_property`, `extra_property_*` |
| Top-level | `empty_object`, `top_level_list/string/number/null`, `deep_nesting_top` (25 levels) |

## Composing with structured-output-validator

The fuzzer and the validator are two halves of one workflow: **fuzz the args → validator hardens**. The seed schema `create_work_order` is intentionally the same schema that repo ships, and `fuzz --corpus-out` writes **JSONL** — JSON Lines, one JSON object per line — where each line's `"payload"` is a ready-made `arguments` object for that validator's `validate` command:

```bash
# 1. fuzz: generate this seed's adversarial arguments
python3 cli.py fuzz --schema create_work_order --seed 7 --corpus-out corpus.jsonl
# 2. validate: feed them to the structured-output-validator as regression inputs
#    (in that repo) python3 cli.py validate --schema create_work_order --file <each payload>
```

Payloads the fuzzer crashes on but the validator *accepts* are the interesting ones — they become the validator's **regression corpus** — a saved set of tricky inputs that must keep passing — and payloads the validator *rejects* confirm the runtime safety net holds.

## Evals

`python3 evals/run_evals.py` runs 5 hand-verified golden fuzz runs: two seeds of `fragile_create_work_order` (each pins corpus size 68, exactly 31 crashes, the 7-signature set, and the sha256 of every shrunk minimal repro), one `robust_create_work_order` run (pins **zero** unexpected crashes, 62 clean rejections), and two seeds of `fragile_place_order` (81 payloads, 40 crashes, 6 signatures incl. `ZeroDivisionError`). The suite runs twice in-process and the reports must be identical; `evals/eval_report.json` is committed with byte-stable output (sorted keys, no timestamps).

**Evals: 5/5 pass; report md5 byte-identical across runs** (see Verification below).

## Dev loop: what the tests caught

The tests genuinely found and fixed real bugs during this build (not after-the-fact polish):

1. **The "robust" target wasn't.** `robust_create_work_order` used `args.get("tags", ["-"])[0]` — but `.get()`'s default only covers a *missing* key, and the fuzzer's `empty_array` mutation passes `tags: []` explicitly (valid per the schema — no `minItems`). `[][0]` → `IndexError`: an unexpected crash in the target that was supposed to prove crash-freedom. Fixed with `(args.get("tags") or ["-"])[0]`. Caught by `test_robust_rejects_with_argument_error_only`.
2. **The seed didn't actually seed anything.** The first version threaded `random.Random(seed)` through the baseline builder but never called it — seeds 7 and 42 produced byte-identical corpora, so "seeded" was a lie. Fixed: the baseline now draws in-bounds values from the seeded RNG (enum pick, string length/content, int/float ranges), so different seeds explore different valid neighborhoods while the same seed replays exactly. Caught by `test_different_seed_differs`.
3. **argparse swallowed the exit-2 path.** `--schema`/`--target` used argparse `choices=`, which rejects unknown names via `sys.exit(2)` *before* the CLI's own error handling — untestable and inconsistent with the documented "2 = error" contract. Fixed: the choices hint moved into help text; unknown names flow through `get_schema`/`_target` into the `EXIT_ERROR` path. Caught by `test_unknown_schema_exit_2`.
4. **Shrink tests asserted the wrong thing, twice.** The shrinker correctly reduced `{"title": "x"*65536, ...}` by halving — which bottoms out at 128 chars, not the 101 the test guessed — and two predicates treated a *missing* key as a crash (`{}.get("title") is None`), so `{}` was the "correct" minimal repro of a sloppy predicate. Fixed the tests to pin the real halving behavior and to require the key's presence. (The shrinker was right; the tests were wrong — exactly what a **hermetic** — fully self-contained, no network, no external state — suite is for.)

Also verified: crash outcomes are seed-stable — seeds 7 and 42 find the *same* 31 crashes (the adversarial mutations are fixed strings; only the valid baseline varies), while the corpus md5 differs. Deterministic where it matters.

## Verification

- **53/53 hermetic unit tests pass** (stdlib `unittest`; independently re-run twice).
- **5/5 golden evals pass**; `evals/eval_report.json` committed, md5 `a74364ce785cc554b617c294dccc0677` byte-identical across 3 runs.
- `demo.py` + `cli.py fuzz/run/demo/serve` smoke-tested live (serve hit over localhost, then shut down).
- Secret sweep clean (see below); stdlib only; no network at runtime.
- One clean commit; working tree clean; no remotes.

### Secret sweep

Ran over all `.py` / `.json` / `.md` files for `sk-…` keys, `api_key`/`password` assignments, and email addresses: **zero hits**. The corpus contains deliberately adversarial strings (including `"__NOT_A_VALUE__"` enum probes and zero-width unicode) — all synthetic, all fictional. No secrets, no personal data — all sample data is the fictional Helios Home store.

## Sample data

All schemas and targets describe the fictional **Helios Home** smart-home store (`create_work_order`, `place_order`). The `create_work_order` schema is shared with the `structured-output-validator` repo so the two tools compose. Zero personal data, zero real credentials.
