"""One-command end-to-end demo: fuzz both targets, shrink, show the story.

Runs fully offline on the fictional Helios Home schemas.
Each stage asserts what it expects, so the demo doubles as a smoke test:

  1. corpus for create_work_order @ seed 7 is byte-identical across generations
  2. the fragile target crashes (unexpected exceptions found + shrunk)
  3. the robust target never crashes -- every adversarial payload is either
     accepted or cleanly rejected (ArgumentError)
"""

from __future__ import annotations

from fuzzer import corpus_md5, generate_corpus
from runner import run_corpus
from schemas import get_schema
from targets import (fragile_create_work_order, robust_create_work_order)


def main() -> None:
    schema = get_schema("create_work_order")

    # 1. determinism: the corpus is a pure function of (schema, seed)
    corpus_a = generate_corpus(schema, 7)
    corpus_b = generate_corpus(schema, 7)
    md5_a, md5_b = corpus_md5(corpus_a), corpus_md5(corpus_b)
    assert md5_a == md5_b, (md5_a, md5_b)
    assert corpus_a[0]["mutation"] == "valid_baseline"
    print(f"corpus: {len(corpus_a)} payloads, md5={md5_a} "
          f"(byte-identical replay)")

    # 2. fragile target: crashes found, each with a minimal repro
    fragile = run_corpus(fragile_create_work_order, corpus_a,
                         schema_name="create_work_order", seed=7)
    assert fragile["unexpected_crashes"] > 0, "fragile target should crash"
    assert fragile["expected_rejections"] == 0
    print(f"\nfragile target: {fragile['unexpected_crashes']} unexpected "
          f"crashes, signatures={fragile['unique_signatures']}")
    for crash in fragile["crashes"][:6]:
        assert crash["minimal_size"] <= crash["original_size"]
        print(f"  [{crash['exc_class']}] {crash['mutation']} "
              f"({crash['path']}): {crash['original_size']}B -> "
              f"{crash['minimal_size']}B")

    # 3. robust target: zero unexpected crashes, clean rejections only
    robust = run_corpus(robust_create_work_order, corpus_a,
                        schema_name="create_work_order", seed=7)
    assert robust["unexpected_crashes"] == 0, robust["crashes"]
    assert robust["expected_rejections"] > 0
    print(f"\nrobust target: 0 unexpected crashes, "
          f"{robust['expected_rejections']} clean rejections "
          f"(every adversarial payload handled)")

    print("\ndemo OK: deterministic corpus, fragile crashes found+shrunk, "
          "robust target crash-free")


if __name__ == "__main__":
    main()
