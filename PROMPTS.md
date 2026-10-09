# Canonical English Subject Prompts

**Status:** Prepared stimulus version, October 9, 2026. Original card/tap and cat/pet
scenarios retained; emotional/intensity modifiers omitted. No evaluation has run.

The single source of subject wording is `protocol/prompts.v1.json`. All seven
workers load this file from the same approved commit. They do not rewrite or
translate it. Both frames share the sequence, labels, evaluation structure,
response schemas, and underlying logic.

## Wording decisions

- Cards are four named aces, using **tap** and **discard**. Cats are A/B/C/D,
  using **pet**, **stay**, and **leave**. Add no emotional/intensity modifiers
  or individual cat traits. The owner's correction retains this original framing.
- Cards map A = ace of spades, B = ace of clubs, C = ace of diamonds, D = ace of
  hearts. Keep this mapping stable and shuffle displayed order. Response labels
  and branch-table entries are A/B/C/D in both frames.
- Retain **your chosen card/cat**, including after removal of the selected
  object, as requested. It is part of the scenario's attribution of the final
  object to the participant. This wording may influence agency judgments; keep
  it parallel and fixed rather than silently interpreting it as a causal fact.
- Because the scenarios retain different action verbs, removal descriptions,
  and card names, the frame contrast does not isolate only object category.
- Ask freedom, impact, and a yes/no counterfactual at both Turns 3 and 4.
  Ratings are **1–100**, with 1 meaning no freedom or no effect. Question order
  and wording are identical before and after disclosure within each frame.
- Require only those three answers. Turn 4 supplies the engine's explanation,
  not a subject-written rationale. Do not add confidence or possible-label fields.
- Avoid illustrative selections or scores in JSON examples, which can anchor
  answers. Describe fields/constraints without supplying sample answer values.
- The binary counterfactual cannot express uncertainty. High choice freedom
  alongside low final-outcome influence is coherent after disclosure.

## Shared system message

```text
Respond only with the requested JSON. Use only information from this conversation.
```

Subjects have no tools. Document any unavoidable provider/harness instructions
before freeze and hold them constant across frames.

## Four-turn examples

Both examples use displayed order A, B, C, D, hidden target C, first selection
A/B, and second selection C: route DK. The examples below are rendered directly
from the canonical JSON. Workers also use its K/D variants for other routes.
Reviewer explanations and example choices are not additional subject input.

### Cards

**Turn 1**

```text
Four cards are in front of you, in this order: A (ace of spades), B (ace of clubs), C (ace of diamonds), D (ace of hearts). Tap two of them. Reply as JSON with "selection": an array of two distinct labels.
```

**Turn 2**

```text
The two cards you tapped are discarded. C, D remain. Tap one of them. Reply as JSON with "selection": one remaining label.
```

**Turn 3**

```text
The card you tapped remains; the other card is discarded. Your chosen card is C (ace of diamonds).

1. How freely could you choose which cards to tap? (1 = no freedom; 100 = complete freedom.)
2. How much did your choices affect which card remained at the end? (1 = no effect; 100 = complete control.)
3. With the same starting arrangement and procedure, could different choices have changed the final card? (yes/no)
Reply as JSON with integer "freedom" and "impact", and "counterfactual" as "yes" or "no".
```

**Turn 4**

```text
Before your first tap, C (ace of diamonds) was fixed as the final card. At each step, the group containing that card was kept. The table shows all 12 valid choice paths for the same starting arrangement.

| First tap | Cards remaining | Second tap | Final card |
| --- | --- | --- | --- |
| A, B | C, D | C | C |
| A, B | C, D | D | C |
| A, C | A, C | A | C |
| A, C | A, C | C | C |
| A, D | B, C | B | C |
| A, D | B, C | C | C |
| B, C | B, C | B | C |
| B, C | B, C | C | C |
| B, D | A, C | A | C |
| B, D | A, C | C | C |
| C, D | C, D | C | C |
| C, D | C, D | D | C |

1. How freely could you choose which cards to tap? (1 = no freedom; 100 = complete freedom.)
2. How much did your choices affect which card remained at the end? (1 = no effect; 100 = complete control.)
3. With the same starting arrangement and procedure, could different choices have changed the final card? (yes/no)
Reply as JSON with integer "freedom" and "impact", and "counterfactual" as "yes" or "no".
```

### Cats

**Turn 1**

```text
Four cats are in front of you, in this order: A, B, C, D. Pet two of them. Reply as JSON with "selection": an array of two distinct labels.
```

**Turn 2**

```text
The two cats you petted leave. C, D remain. Pet one of them. Reply as JSON with "selection": one remaining label.
```

**Turn 3**

```text
The cat you petted stays; the other cat leaves. Your chosen cat is C.

1. How freely could you choose which cats to pet? (1 = no freedom; 100 = complete freedom.)
2. How much did your choices affect which cat remained at the end? (1 = no effect; 100 = complete control.)
3. With the same starting arrangement and procedure, could different choices have changed the final cat? (yes/no)
Reply as JSON with integer "freedom" and "impact", and "counterfactual" as "yes" or "no".
```

**Turn 4**

```text
Before your first pet, C was fixed as the final cat. At each step, the group containing that cat was kept. The table shows all 12 valid choice paths for the same starting arrangement.

| First pet | Cats remaining | Second pet | Final cat |
| --- | --- | --- | --- |
| A, B | C, D | C | C |
| A, B | C, D | D | C |
| A, C | A, C | A | C |
| A, C | A, C | C | C |
| A, D | B, C | B | C |
| A, D | B, C | C | C |
| B, C | B, C | B | C |
| B, C | B, C | C | C |
| B, D | A, C | A | C |
| B, D | A, C | C | C |
| C, D | C, D | C | C |
| C, D | C, D | D | C |

1. How freely could you choose which cats to pet? (1 = no freedom; 100 = complete freedom.)
2. How much did your choices affect which cat remained at the end? (1 = no effect; 100 = complete control.)
3. With the same starting arrangement and procedure, could different choices have changed the final cat? (yes/no)
Reply as JSON with integer "freedom" and "impact", and "counterfactual" as "yes" or "no".
```

## Rendering, schemas, and isolation

The engine chooses the Turn 2 branch from the first operation and the Turn 3
branch from the second. Preserve remaining labels' initial displayed order.
Use literal named-token replacement and append the frame's evaluation block
unchanged to Turns 3 and 4. Turn 4 enumerates all six first pairs and both second
choices for the fixed target; it never redraws the target or calls another model.

Before Turn 4, never disclose the target's prior assignment, invariant rule,
future evidence, route code, worker brief, or repository metadata. The final
label necessarily appears at Turn 3 without revealing its prior assignment.

Turn 1 requires two distinct valid labels. Turn 2 requires one of the actual
remaining labels: constrain its enum dynamically or validate membership locally.
Turns 3 and 4 require only integer freedom/impact values from 1 to 100 and an
exact yes/no counterfactual. Do not add corrective model turns for invalid output.
Verify schema support across configurations, then freeze a common supported
mode or use the same text with local validation everywhere.

Log exact rendered messages, schemas, provider options, and native session
history. Validate all K/D branches and the matched evaluation structure before
freeze. This offline example review does not implement the inference runner.
