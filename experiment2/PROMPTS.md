# Exact structural additions for experiment 2

`experiment2/protocol/prompts.json` is the sole machine-readable stimulus source.
Its `base` object is exactly the original `protocol/prompts.v1.json` data. It
retains the English system text, full card names and A–D cat labels, both feedback
branches, output schemas, and evaluation block unchanged. Research-only codes
never appear in card prompts, tables, or response enums.

Round 1 uses the original choose-two and choose-one text. Round 2 and Round 3
prepend only `Round 2.` or `Round 3.` and two newlines to the same choose-two text,
listing all four objects in the next frozen arrangement. Each round uses the
original two feedback branches and the same three evaluation questions.

All four measurements insert this exact sentence between feedback/disclosure
and the unchanged evaluation block:

```text
Answer the following questions about the round just completed.
```

Final disclosure for cards:

```text
Before your first tap in Round 1, {final_object} was fixed as the final card for all three rounds. At each step in every round, the group containing that card was kept. Each table shows all 12 valid choice paths for that round's starting arrangement.

{round_tables}
```

For cats replace `tap` with `pet` and `card` with `cat`, as encoded in the JSON.
`{round_tables}` contains `Round 1`, `Round 2`, and `Round 3` headings, each
followed by the original four-column 12-path table for that arrangement and the
same fixed target. Append the scope sentence and unchanged frame evaluation.

Measurement turns are 3, 6, 9, and 10. The last two both refer to Round 3, before
and after evidence. Turn 10 contains all three tables so the common forcing rule
is verifiable for every round. There are no extra model-generated explanations,
intensity modifiers, confidence responses, or future-disclosure hints.
