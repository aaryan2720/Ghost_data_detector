# Contributing to Host Data Detector

Thank you for your interest in contributing to **Host Data Detector**.

## Development Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/aaryan2720/Ghost_data_detector.git
   cd Ghost_data_detector
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux / macOS:
   source .venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Run the regression test suite:
   ```bash
   pytest code/tests/ -v
   ```

## Contribution Guidelines

- **Determinism**: The core investigation pipeline must remain deterministic. Avoid unseeded randomization or unpredictable dictionary/set iterations when writing serialization logic.
- **Evidence-Grounded**: Decisions must be grounded in participant-visible evidence. Never assume or synthesize unobservable database records or activity traces.
- **Contract Adherence**: Any changes must comply with the competition contract rules:
  - Valid phases: `FINDING` -> `REMEDIATION` -> `VERIFICATION`.
  - 1-indexed consecutive step numbers.
  - Strict step operations and states (see [`docs/architecture.md`](docs/architecture.md)).
  - Correct `evidence_id` usage: non-empty for `FINDING` and complete-case `VERIFICATION`, empty for proposed `REMEDIATION` and incomplete-case `VERIFICATION`.
- **Testing**: Every bug fix or feature addition must include a corresponding test under `code/tests/`. All tests must pass before submitting a pull request.
- **Clean Commits**: Write clear, descriptive commit messages. Never commit raw secrets, private tokens, or unverified binary blobs.
