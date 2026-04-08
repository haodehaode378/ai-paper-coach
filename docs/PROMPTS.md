# Prompt Set (v1)

## draft_qwen.txt
- Generates full first-pass JSON report.
- Must keep evidence refs and avoid fabricated metrics.

## review_minimax.txt
- Reviews draft only, no full rewrite.
- Returns patch suggestions with `path/instruction/value`.

## patch_qwen.txt
- Applies justified patches to draft.
- Preserves schema and writes change_log.

## arbitration.txt
- Optional strict mode tie-breaker.
