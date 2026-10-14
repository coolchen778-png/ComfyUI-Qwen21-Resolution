# Simplified Chinese Skill Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify and localize the existing Skill prompt node while adding safe automatic discovery of GGUF, mmproj, and Transformers models under ComfyUI `models/llm`.

**Architecture:** Add a focused local-model catalog that discovers and resolves only catalogued paths. Keep the existing backend adapters, translate the new two-mode UI into their internal backend names, and use the frontend extension only for presentation, visibility, and Skill management.

**Tech Stack:** Python 3.12, ComfyUI node API, browser JavaScript, pytest, Node.js syntax/tests

**Spec:** `docs/superpowers/specs/2026-10-14-simplified-chinese-skill-node-design.md`

## Global Constraints

- Keep one visible node and preserve `QwenMultiSkillPromptGenerator`.
- Scan both GGUF files and Transformers directories recursively under every registered `llm` root.
- Keep main model and mmproj as separate selectors.
- Preserve unlimited ordered Skills and the five-image maximum.
- Do not store API secrets in workflows.

## Review Focus

- A stale or forged model selection must not escape configured `llm` roots.
- `mmproj` files must not appear in the main-model selector.
- Duplicate registered roots must not duplicate choices.
- Legacy backend values must still dispatch to their former adapters.
- Failure of the rich Skill DOM widget must not remove the upload entry point.

---

### Task 1: Local model catalog

**Files:**
- Create: `skill_prompt/models.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Produces: `LocalModelCatalog.discover(roots)`, `main_choices()`, `mmproj_choices()`, `resolve_main()`, and `resolve_mmproj()`.

- [ ] Write tests for recursive discovery, classification, de-duplication, and rejection of unknown selections.
- [ ] Run the new tests and verify they fail because the catalog is absent.
- [ ] Implement the minimal catalog and ComfyUI `llm` root discovery.
- [ ] Run the model catalog tests and the full Python suite.

### Task 2: One-node local/API dispatch

**Files:**
- Modify: `skill_prompt/node.py`
- Modify: `tests/test_node.py`

**Interfaces:**
- Consumes: the catalog interface from Task 1.
- Produces: localized two-mode inputs that dispatch to `gguf`, `transformers`, or `online_api`.

- [ ] Write failing tests for Chinese mode choices, GGUF/mmproj dispatch, Transformers dispatch, online API dispatch, and legacy values.
- [ ] Run the focused tests and confirm the expected failures.
- [ ] Implement model selection and backend translation while retaining legacy keyword defaults.
- [ ] Run the focused tests and full Python suite.

### Task 3: Chinese adaptive frontend and documentation

**Files:**
- Modify: `web/js/qwen_skill_prompt.js`
- Create: `web/js/qwen_skill_prompt_ui.mjs`
- Create: `tests/test_skill_ui.mjs`
- Modify: `nodes.py`
- Modify: `README.md`

**Interfaces:**
- Produces: Chinese labels, local/API visibility state, an always-visible upload fallback, and updated installation/use instructions.

- [ ] Write failing Node.js tests for visibility rules and legacy mode normalization.
- [ ] Implement the pure UI state helpers and make the ComfyUI extension consume them.
- [ ] Replace garbled UI strings and document `models/llm`, main model/mmproj, API mode, Skill upload, and restart/refresh steps.
- [ ] Run Node.js tests, JavaScript syntax checks, and the full Python suite.
