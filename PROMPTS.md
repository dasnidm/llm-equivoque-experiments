# Canonical English Subject Prompts

**Status:** Prepared stimulus version, October 9, 2026. Cards use their names
only; cats retain A/B/C/D. No evaluation has started.

The single source of subject wording is `protocol/prompts.v1.json`. All seven
workers load it from the same approved commit without rewriting or translating
it. Both frames share the four-turn procedure, evaluation structure, and engine.

## Wording and response identifiers

- Cards are **ace of spades**, **ace of clubs**, **ace of diamonds**, and
  **ace of hearts**. Show and accept these exact names. Do not prepend A/B/C/D
  in any card prompt, remaining-object list, disclosure table, or response schema.
- Cats are labeled **A, B, C, D**. Cards use **tap/discard**; cats use
  **pet/stay/leave**. Add no emotional/intensity modifiers or individual traits.
- The research engine uses A/B/C/D internally to pair cases across frames:
  A maps to ace of spades, B to ace of clubs, C to ace of diamonds, D to ace of
  hearts. This mapping is never shown to card subjects. Preserve original model
  response text and normalize names to internal codes only in parsed logs/engine.
- Retain **your chosen card/cat**, including when the selected object is removed,
  as requested. This outcome-attribution wording may influence agency judgments;
  hold it fixed across frames rather than treating it as a causal fact.
- The scenarios retain different object names, action verbs, and removal words;
  their contrast does not isolate only object category.
- Ask freedom, impact, and a yes/no counterfactual at Turns 3 and 4. Both ratings
  use **1–100**, with 1 meaning no freedom or no effect. Repeat the same questions
  and order within each frame. Request only these three answers, not explanations,
  confidence, or possible-final-object sets.
- Turn 4 supplies the engine's explanation and all 12 paths. The binary judgment
  cannot express uncertainty; high freedom with low outcome influence is coherent.
- Do not include sample selections or scores in subject JSON-format instructions;
  describe the fields without anchoring answers.

## Shared system message

```text
Respond only with the requested JSON. Use only information from this conversation.
```

Subjects have no tools. Document unavoidable provider/harness instructions before
live launch and keep them fixed across frames.

## Four-turn examples

The card example starts with the four aces in the order spades, clubs, diamonds,
hearts. Its fixed target is ace of diamonds; the first selection is spades/clubs
and the second is diamonds: route DK. The paired cat example uses order A/B/C/D,
target C, first selection A/B, and second selection C. This reviewer explanation
is not extra subject input. The messages below are rendered from canonical JSON.

### Cards

**Turn 1**

```text
Four cards are in front of you, in this order: ace of spades, ace of clubs, ace of diamonds, ace of hearts. Tap two of them. Reply as JSON with "selection": an array of two distinct card names.
```

**Turn 2**

```text
The two cards you tapped are discarded. ace of diamonds, ace of hearts remain. Tap one of them. Reply as JSON with "selection": one remaining card name.
```

**Turn 3**

```text
The card you tapped remains; the other card is discarded. Your chosen card is ace of diamonds.

1. How freely could you choose which cards to tap? (1 = no freedom; 100 = complete freedom.)
2. How much did your choices affect which card remained at the end? (1 = no effect; 100 = complete control.)
3. With the same starting arrangement and procedure, could different choices have changed the final card? (yes/no)
Reply as JSON with integer "freedom" and "impact", and "counterfactual" as "yes" or "no".
```

**Turn 4**

```text
Before your first tap, ace of diamonds was fixed as the final card. At each step, the group containing that card was kept. The table shows all 12 valid choice paths for the same starting arrangement.

| First tap | Cards remaining | Second tap | Final card |
| --- | --- | --- | --- |
| ace of spades, ace of clubs | ace of diamonds, ace of hearts | ace of diamonds | ace of diamonds |
| ace of spades, ace of clubs | ace of diamonds, ace of hearts | ace of hearts | ace of diamonds |
| ace of spades, ace of diamonds | ace of spades, ace of diamonds | ace of spades | ace of diamonds |
| ace of spades, ace of diamonds | ace of spades, ace of diamonds | ace of diamonds | ace of diamonds |
| ace of spades, ace of hearts | ace of clubs, ace of diamonds | ace of clubs | ace of diamonds |
| ace of spades, ace of hearts | ace of clubs, ace of diamonds | ace of diamonds | ace of diamonds |
| ace of clubs, ace of diamonds | ace of clubs, ace of diamonds | ace of clubs | ace of diamonds |
| ace of clubs, ace of diamonds | ace of clubs, ace of diamonds | ace of diamonds | ace of diamonds |
| ace of clubs, ace of hearts | ace of spades, ace of diamonds | ace of spades | ace of diamonds |
| ace of clubs, ace of hearts | ace of spades, ace of diamonds | ace of diamonds | ace of diamonds |
| ace of diamonds, ace of hearts | ace of diamonds, ace of hearts | ace of diamonds | ace of diamonds |
| ace of diamonds, ace of hearts | ace of diamonds, ace of hearts | ace of hearts | ace of diamonds |

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

Choose Turn 2 feedback from the first operation and Turn 3 feedback from the
second. Preserve the initial object order. Render all card references as names
and cat references as labels, including every disclosure-table cell. Append the
frame's evaluation block unchanged to Turns 3 and 4. Generate the 12-row table
from the fixed target; never redraw it or use another model to invent the table.

Before Turn 4, disclose neither the target's prior assignment nor the invariant
rule, future evidence, route code, worker brief, or repository metadata. Turn 3
necessarily reveals the final object, without explaining its prior assignment.

Instantiate the choice schema per frame: two distinct exact card names or cat
labels at Turn 1; one of the actual remaining names/labels at Turn 2. The engine
normalizes valid card names to research codes after preserving raw responses.
Reject card answers containing research labels A/B/C/D. Turns 3 and 4 require
only integer freedom/impact from 1 to 100 and exactly yes/no. Add no corrective
model turns for invalid output; verify actual provider schema support in preflight.

Record exact rendered messages, schemas, provider options, and native session
history. Offline tests check that every card prompt contains no standalone
A/B/C/D label, cover all choice branches, and audit normalized choices against
raw responses. These checks do not establish live inference access.
