# POS Data Follow-Up — Request Fresh Export from Yassir

## Why this doc exists

The `popularity` field on every item in `order_engine.MENU` comes from the
06-Apr-2026 POS sales export that was merged in commit
`a425220` ("3a: merge 197 menu items into MENU dict").

That export is **incomplete**. It is missing entire SKUs for
universally-ordered drinks:

| Item           | MENU `popularity` in source data | Reality                         |
|----------------|----------------------------------|---------------------------------|
| `teh tarik`    | 0                                | THE signature mamak drink       |
| `milo panas`   | 0                                | Breakfast staple                |
| `kopi panas`   | 0                                | Breakfast staple                |
| `sirap panas`  | 0                                | Common                          |
| `bandung`      | 0                                | Common                          |
| `bandung ais`  | 0                                | Common                          |
| `bandung panas`| 0                                | Common                          |
| `air kosong`   | 0                                | Free refill request             |
| `cincau`       | 0                                | Common                          |
| `longan`       | 0                                | Common                          |

Root cause: Yassir's POS aggregates default preparations under a single
base SKU. For example, every teh tarik sale is rung up as plain "Teh"
because tarik is the default preparation at the counter. The variant
never appears as its own row in the export.

## Temporary mitigation (in-tree)

`order_engine.ICONIC_DRINKS_FLOOR` + `apply_popularity_floor()` apply a
conservative, industry-estimate floor to these items so that downstream
consumers — fuzzy-match tie-break in `menu_validator.py` and the top-30
best-sellers injected into the DeepSeek prompt in `main.py` — don't
silently demote them to zero.

**The floor values are estimates, not sales data.** They exist only to
keep the items non-zero. Replace them with real POS numbers as soon as
a fresh export is available.

## What we need from Yassir

A POS export that satisfies **all** of the following:

1. **Itemizes every variant as a distinct SKU**, specifically:
   - Hot vs iced: `teh panas` vs `teh ais`, `milo panas` vs `milo ais`,
     `kopi panas` vs `kopi ais`, `bandung panas` vs `bandung ais`, etc.
   - Tarik vs plain: `teh tarik` must be a separate row from `teh`.
   - Size variants: `jumbo`, `besar` etc. as their own rows (already
     partially the case).

2. **Window**: last 30 days of sales, minimum. Longer is better — more
   signal, less weekday/weekend noise.

3. **Format**: CSV with at least these columns:
   - `item_name` — raw POS name, verbatim (not cleaned up)
   - `quantity_sold` — integer count over the window
   - `date_range` — start/end date of the export window

4. **Completeness**: include every SKU that was sold at least once
   during the window. Do not filter out low-volume items — we need the
   long tail for fuzzy matching.

## Once the new export arrives

1. Re-run the merge pipeline that produced
   `logs/step2_modifier_extraction.md` and `logs/step3_summary.txt`
   against the new export, updating `order_engine.MENU` popularity
   values.
2. Remove or zero-out `order_engine.ICONIC_DRINKS_FLOOR` — real data
   should always win. `tests/test_popularity_floor.py` will need to be
   removed or rewritten accordingly.
3. Regenerate the top-30 best-sellers block in the DeepSeek system
   prompt (see commit `dd29336`).
4. Re-check `menu_validator.PINNED_ITEMS` — some of those pins may
   become unnecessary once real popularity is present.

## Related code pointers

- Floor definition: `order_engine.py` — `ICONIC_DRINKS_FLOOR`,
  `apply_popularity_floor`
- Fuzzy-match tie-break consumer: `menu_validator.py:384–394`
- Whisper-prompt pin workaround: `menu_validator.py:56–76`
  (`PINNED_ITEMS`)
- DeepSeek top-30 block: `main.py` (added in commit `dd29336`)
- Tests: `tests/test_popularity_floor.py`
