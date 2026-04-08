# AI Paper Coach - Project Playbook

## 1. Product Goal
Build a student-first paper reading agent that accepts paper URL or PDF upload and outputs:
1. 3-minute summary
2. Explain-like-I-am-your-classmate version
3. Reproduction guide

The system uses Qwen + MiniMax in a collaborative loop instead of strict task splitting.

## 2. Core Modes
- Fast mode: Qwen only
- Deep mode (default): Qwen draft -> MiniMax review -> Qwen patch
- Strict mode: add conflict arbitration pass when models disagree

## 3. High-Level Architecture
- Frontend: input (URL/upload), progress status, result tabs
- Backend API: ingest, parse, draft, review, patch, export
- Parser: PDF text extraction + section chunking
- Model router: Qwen/MiniMax orchestration
- Storage: task records, prompt versions, outputs, cache

## 4. Suggested Project Structure
```text
ai-paper-coach/
  README.md
  .env.example
  docs/
    PROJECT_PLAYBOOK.md
    PROMPTS.md
  apps/
    web/                      # Next.js UI
      src/
        app/
        components/
        lib/
  services/
    api/                      # FastAPI or Node API
      app/
        main.py
        routers/
          ingest.py
          analyze.py
          export.py
        core/
          parser.py
          chunker.py
          orchestrator.py
          model_router.py
          schemas.py
          cache.py
        prompts/
          draft_qwen.txt
          review_minimax.txt
          patch_qwen.txt
          arbitration.txt
  data/
    uploads/
    cache/
  scripts/
    smoke_test.py
```

## 5. End-to-End Workflow
1. Ingest
- Input type: arXiv URL / PDF URL / local PDF upload
- Normalize to one `paper_id`

2. Parse
- Extract full text, detect title/abstract/sections
- Chunk by section + token limit

3. Draft (Qwen)
- Generate initial structured output in JSON

4. Review (MiniMax)
- Detect missing points, unclear terms, risky claims
- Return patch suggestions only (no full rewrite)

5. Patch (Qwen)
- Apply review suggestions to targeted sections
- Output final report + change log

6. Optional Arbitration
- If conflict score exceeds threshold, run short evidence-based tie-breaker

7. Export
- Markdown / JSON / copy-ready text

## 6. Output Contract (JSON)
```json
{
  "paper_meta": {
    "title": "",
    "authors": [],
    "year": "",
    "source_type": "url|upload"
  },
  "three_minute_summary": {
    "problem": "",
    "method_points": [],
    "key_results": [],
    "limitations": [],
    "who_should_read": ""
  },
  "teach_classmate": {
    "elevator_30s": "",
    "classroom_3min": "",
    "analogy": "",
    "qa": [
      {"q": "", "a": ""}
    ]
  },
  "reproduction_guide": {
    "environment": "",
    "dataset": "",
    "commands": [],
    "key_hyperparams": [],
    "expected_range": "",
    "common_errors": []
  },
  "evidence_refs": [
    {"claim": "", "section": ""}
  ],
  "change_log": []
}
```

## 7. Prompt Templates (v1)

### 7.1 Qwen Draft Prompt
```text
You are a paper reading assistant for undergraduate students.
Given paper chunks, produce a JSON report with keys:
paper_meta, three_minute_summary, teach_classmate, reproduction_guide, evidence_refs.
Rules:
- Keep explanations accurate but easy for a second-year CS student.
- Do not invent experiments or numbers.
- Mark uncertain items as "Not explicitly stated in paper".
- Each major claim must include a section reference in evidence_refs.
- Output valid JSON only.
```

### 7.2 MiniMax Review Prompt
```text
You are a strict reviewer. Do NOT rewrite the full report.
Input includes: draft JSON + source excerpts.
Return JSON with:
- missing_points: list of specific missing technical points
- unclear_terms: list of terms needing simpler explanation
- risky_claims: claims that are unsupported/overstated
- patch_suggestions: targeted edits as {path, instruction}
Rules:
- Be evidence-based.
- Prefer concise patch instructions.
- Output valid JSON only.
```

### 7.3 Qwen Patch Prompt
```text
You receive:
1) original draft JSON
2) MiniMax review JSON
Apply only justified patch_suggestions.
Rules:
- Preserve original structure.
- Do not modify unaffected fields.
- Add a change_log entry for each applied patch.
- Keep output as valid JSON only.
```

### 7.4 Arbitration Prompt (Optional)
```text
You are an evidence arbiter.
Given conflicting claims from two model outputs and source excerpts,
choose the better-supported version and explain in <= 3 lines with section evidence.
Return JSON: {decision, reason, evidence_section}
```

## 8. Model Collaboration Strategy
- Default: Qwen draft -> MiniMax review -> Qwen patch
- Trigger arbitration when:
  - MiniMax flags >= 3 risky_claims
  - or claim conflict found on metrics/method details

## 9. API Plan
- `POST /ingest` -> create paper_id from URL/upload
- `POST /analyze` -> run parse + draft
- `POST /review` -> run MiniMax review
- `POST /finalize` -> patch + optional arbitration
- `GET /report/{paper_id}` -> fetch final report
- `GET /export/{paper_id}.md` -> markdown export

## 10. Data Schema (minimal)
- papers(id, source_type, source_name, title, created_at)
- parses(id, paper_id, parse_status, section_index_json)
- runs(id, paper_id, mode, status, started_at, finished_at)
- outputs(id, run_id, draft_json, review_json, final_json, changelog_json)
- metrics(id, run_id, model, latency_ms, input_tokens, output_tokens, cost_est)

## 11. Reliability Rules
- If parse fails, return summary-only fallback with explicit warning.
- If MiniMax fails, keep Qwen draft and flag `review_skipped=true`.
- Always save intermediate artifacts for debugging.
- Cache by `(paper_hash, prompt_version, mode)`.

## 12. Engineering Conventions
- Prompt versioning required: `draft_v1`, `review_v1`, etc.
- Every response must be machine-parseable JSON before rendering.
- Keep deterministic formatting in final markdown export.
- Add smoke tests for one known paper.

## 13. MVP Scope (2 weeks)
1. URL + PDF upload ingestion
2. PDF parse + chunk
3. Deep mode orchestration
4. JSON result + markdown export
5. History list page

## 14. Next Milestones
- OCR fallback for scanned PDFs
- Citation-level evidence mapping (paragraph index)
- Multi-paper comparison mode
- Personal knowledge base integration
