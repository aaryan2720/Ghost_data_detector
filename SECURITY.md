# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

## Security and Privacy Model

**Host Data Detector** audits personal data deletion compliance across distributed systems. Given the domain, the project is designed with the following security considerations:

1. **Synthetic and Anonymized Evidence**:
   - The test suites and example fixtures use purely synthetic and fictional identifiers.
   - Do not commit production databases, live logs containing real customer PII, or unredacted credentials to this repository.

2. **Secrets Handling**:
   - The audit pipeline does not require or store remote API keys, access tokens, or database passwords in source code.
   - Any sensitive configurations should be supplied via environment variables or uncommitted `.env` files.

3. **Read-Only Evidence Consumption**:
   - The audit engine executes read-only evaluations of snapshots, SQLite replicas, logs, and exports.
   - It does not mutate or drop upstream tables directly; it generates safe, ordered remediation plans for operators to execute.

## Reporting a Vulnerability

If you discover a security vulnerability or sensitive data leak in this repository, please report it privately:

- **Email**: Open an issue requesting private security contact or contact the repository maintainer directly.
- Please include a detailed description of the vulnerability, steps to reproduce, and potential impact.
- Do not open a public issue disclosing unresolved vulnerabilities.
