# The gate: when is a replacement safe?

A Hex replacement is a literal, case-insensitive, whole-word find-and-replace that runs on every
transcript, with no context. So the question for each pair is about precision: of all the times
the heard form shows up, what share were mishearings? A replacement with 90% precision corrupts
one real use in ten.

## Counting

The skill reads Hex's own history (`history.json`, `raw_text`, before replacements run) and
finds every entry containing the heard form. Claude labels each one `error`, `literal` or
`unclear` by reading it in context.

Occurrences are counted **once per calendar day**. One dictation session about one topic repeats
the same word, and those repeats aren't independent evidence. A day counts as literal if any
occurrence that day was literal, and otherwise as an error if any was.

## The bound

If every one of n days was an error, the one-sided lower confidence bound on precision is

```
  pₗ = α^{1/n}
```

- pₗ: the lowest precision still consistent with the data
- α: the allowed chance the bound is wrong, here 0.05
- n: the number of days, all of them errors

**Why this shape.** If the true precision were p, the chance that all n days come out as errors
is pⁿ. The lowest p that still gives that outcome at least an α chance solves pⁿ = α, so
p = α^(1/n). This is the exact Clopper-Pearson bound when there are no failures, the same logic
as the "rule of three". With failures, `gate.py` computes the general Clopper-Pearson bound by
bisection.

To clear a target precision pₜ with no failures, you need

```
       ln α
  n ≥ ───────
       ln pₜ
```

With α = 0.05 and pₜ = 0.9 that's ln 0.05 / ln 0.9 = −2.996 / −0.105 = 28.4, so **29 clean days**.
Values for smaller n: n=2 gives 0.224, n=3 gives 0.368, n=5 gives 0.549, n=10 gives 0.741.

## Two tiers

Pure statistics would almost never approve a replacement from a few weeks of dictation, so the
gate uses prior knowledge about the word:

| Tier | Test | Rule |
|---|---|---|
| Rare form | a multi-word phrase, or a single word missing from the bundled Webster's 2nd list (`skills/hex-upsert/data/words.txt.gz`, the `/usr/share/dict/words` macOS ships) | ≥ 2 error days and no literal day |
| Common word | a single dictionary word | no literal day and pₗ ≥ 0.9 |
| Any | at least one literal day | in-context only, never a replacement |

A rare form is unlikely to be meant literally to begin with, and the prior does the work the
sample can't. A Bayesian version would make that explicit: a beta prior on precision whose
strength depends on dictionary status.

## Assumptions, and what happens when they fail

- **Hex history is the whole population.** Words you type, rather than dictate, never enter the
  count. A word you often type literally but rarely dictate can look safe when it isn't. The
  report should say so for each approved pair.
- **Claude's labels are right.** Labelling is an LLM-as-judge step, and judges flip. The skill
  re-reads 5 labels cold and re-checks a whole pair if any of them change.
- **History retention is long enough.** Hex defaults to keeping 7 days. Set it to 30 days or
  Forever, or no common word can ever reach 29 days.

## Why the first approach failed

The first mining run (2026-11-15) used the ratio of corrections to occurrences. Claude flags a
mishearing once per session, not every time, so that ratio badly understates errors. One name
scored 0.016 on it and its hand-checked error rate was 66 of 66. Counting labelled occurrences
in Hex history fixes this.
