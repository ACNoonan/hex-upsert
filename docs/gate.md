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

## Five types of pair

Precision depends on two things. Can the heard form be said on purpose? Does that sound always
mean the same target? A dictionary test on the heard words answers only the first, and badly for
phrases. So the gate sorts each pair into a type first, and the type picks the evidence rule.

It looks at the words that differ, once the words both sides share at the start and end are set
aside. `free our non-signed-in users` → `free or non-signed-in users` is `our` → `or`.

| Type | What happened | Example | Evidence rule |
|---|---|---|---|
| non-word | the heard form isn't an ordinary word | `Superbase` → `Supabase` | term |
| term-as-words | a term came out as ordinary words | `clawed code` → `Claude Code`, `sequel` → `SQL` | term if the heard form is a phrase, bound if it's one word |
| written-form | right words, wrong case or spacing | `Agent Mine` → `agentmine`, `spit` → `SPIT` | term if a phrase, bound if one word |
| word-swap | an ordinary word for an ordinary word | `air` → `error`, `our` → `or` | bound |
| dropped-word | words added, dropped, cut short or negated | `don't` → `do`, `his` → `history` | never |

This follows the split spelling correction has used since Kukich (1992): a non-word error can be
fixed by lookup, and a real-word error needs the sentence. Word swaps are the confusion sets of
Golding and Roth (1999), which they correct with a classifier that reads the context. A
context-free replacement can't do that, so those stay with Claude.

The three evidence rules:

| Rule | A pair becomes a replacement when |
|---|---|
| term | it has no literal day, at least 1 error day of its own, and its target has ≥ 2 error days across all its heard forms |
| bound | it has no literal day and pₗ ≥ 0.9, which takes 29 clean days |
| never | never. Nothing is being substituted, so no amount of evidence makes it a replacement |
| any | at least one literal day means in-context only |

### What counts as an ordinary word

A word is ordinary if people say it at least once per million words. The count comes from the
bundled list of the 50,000 most frequent words in film and TV subtitles
(`skills/hex-upsert/data/words.txt.gz`, source and licence in `NOTICE.md` beside it). Once per
million is Zipf 3, the usual line between low-frequency and high-frequency words (van Heuven
et al. 2014). About 21,500 words clear it. A word also counts if it clears the line once a
contraction or a regular ending (`-s`, `-ed`, `-ing`) is removed, or if it's hyphenated and each
part is ordinary. A number is ordinary.

The first version used Webster's 2nd, a 1934 dictionary. It has no "website", "email", "okay" or
"paid", so it called those rare, and it has "Jason" and "Helge" only by accident of being a
dictionary. Subtitles are speech, which is what dictation is, and the counts let the line sit
at "said often" and not at "exists".

A correction is a term if it has a word that isn't ordinary, or a capital the heard form didn't
have (`clawed code` → `Claude Code`). When a phrase starts with a capital on both sides, that
capital is only the start of a sentence.

### Evidence is counted per target

One term scatters across several heard forms: Vercel shows up as "Verselle" and "verse cell".
Counted separately, each form has one day and none passes. So under the term rule the days are
pooled across every heard form of the same target, and each form still needs one error day of
its own and no literal day.

A heard form shares the pool only if it is spelled like the target:

```
               d
  s = 1 − ───────────
           max(m, n)
```

- s: the similarity, from 0 to 1. A form shares the pool when s ≥ 0.5
- d: the edit distance, the fewest single-letter insertions, deletions and substitutions that
  turn the heard form into the target, with case, spaces and punctuation removed
- m, n: the letter counts of the heard form and the target

**Why this shape.** Dividing by the longer length puts short and long terms on one scale: s is
the share of the longer string that didn't have to change. The pool assumes the forms are
attempts at the same sound, and spelling is the cheapest stand-in for sound.

**Worked numbers.** "Verselle" → "Vercel": substitute s → c, delete l, delete e, so d = 3,
max(8, 6) = 8 and s = 1 − 3/8 = 0.625. It shares. "relu" → "Locke": d = 4, max(4, 5) = 5 and
s = 0.2. It doesn't, so it needs 2 error days of its own.

**What it assumes, and where it fails.** Spelling tracks sound only roughly. A truncation
(`cell` → `Vercel`: d = 4, s = 1 − 4/6 = 0.33) or a spoken form (`Dottie MB` → `.env`) is a real
mishearing that doesn't share the pool. The cost is a slower approval, never a wrong one. A
phonetic distance over a pronouncing dictionary would be more accurate, and it would add a
dependency and miss the invented spellings that have no dictionary entry.

### Vocabulary first

For a term Hex doesn't know, the standard fix in speech recognition is to tell the recogniser
the term (contextual biasing). Hex's Vocabulary does that, and one entry covers every heard
form, including ones not seen yet. So the gate proposes one vocabulary entry per target that
looks like a name or term, and the replacements are the backstop for forms that keep coming.

A "sounds like" spelling is something Hex may show instead of the term. Only heard forms nobody
says on purpose go in: a phrase, or a single word that isn't ordinary, with no literal day.
`sequel` is never a spelling for SQL.

The term rule leans on the prior, as the two-tier version did: a form nobody says on purpose is
unlikely to be meant literally, and that prior does the work the sample can't. A Bayesian
version would make it explicit: a beta prior on precision whose strength depends on the type.

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
