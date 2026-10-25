# Usage Report: Ghost Data Still Exists (Full Dataset Run)

## 1. Executive Summary

This report documents the resource and token consumption for the final full-dataset execution that generated `output.csv` (518 deletion requests) for the HackerRank Orchestrate (October 2026) challenge, "Ghost Data Still Exists."

The audit agent architecture is engineered as a **deterministic, zero-token inference engine**. All policy decisions, distributed trace correlations, SQL inspections, JSON record parsing, identity graph resolution, and post-remediation step syntheses run deterministically in-process using Python without making external LLM inference calls at runtime.

---

## 2. Full-Dataset Execution Metrics (Inference Run)

| Metric | Measured Value | Notes |
| :--- | :--- | :--- |
| **Target Dataset** | `dataset/deletion_requests.csv` | Exactly 518 evaluation requests |
| **Output File** | `output.csv` (repo root) | Exactly 518 output rows |
| **Execution Command** | `python -m code.main --mode investigate --requests dataset/deletion_requests.csv --output output.csv` | Fully autonomous deterministic execution |
| **Model Providers** | None (Deterministic In-Memory Engine) | Zero third-party inference APIs called |
| **Model Names** | None (Symbolic Audit Engine) | Zero remote neural models invoked during batch audit |
| **Model Call Counts** | **0** | No remote API requests |
| **Input Tokens** | **0** | All evidence parsed and indexed in local SQLite / memory |
| **Output Tokens** | **0** | Steps synthesized via canonical policy rulebook |
| **Total Tokens** | **0** | 0 tokens consumed |
| **Average Tokens / Request** | **0.0 tokens** | Fast deterministic throughput |
| **Estimated Inference Cost** | **$0.00** | $0.00 per request, $0.00 total |
| **Execution Wall Time** | ~25 seconds | For all 518 requests (averaging ~48 ms / request) |

---

## 3. Development and Agent Harness Profile

The development, trace investigation, adversarial test design, and contract verification were performed pair-programming with the Antigravity agentic harness:

| Component | Identifier / Detail |
| :--- | :--- |
| **Harness Name (`tool=`)** | `Antigravity` |
| **Model Identifier (`model=`)** | `Gemini 3.8 Flash (Medium)` |
| **Model Provider** | Google DeepMind |
| **Operational Mode** | Autonomous Agentic CLI / Pair Programming |
| **Security & Privacy** | Strict compliance with AGENTS.md §2, §4, §5 (no secrets, zero PII logged, redactions enforced) |

---

## 4. Cost Efficiency and Scalability Analysis

By eliminating LLM inference from the core evaluation loop:
1. **Determinism**: Identical inputs produce bitwise-identical output rows, satisfying §6.7.
2. **Zero API Cost & Rate-Limit Immunity**: The solution can scale to millions of requests without incurring API fees or facing HTTP 429 rate limits.
3. **Auditability**: Every decision directly cites grounded evidence (`evidence_id`) rather than hallucinating facts.
