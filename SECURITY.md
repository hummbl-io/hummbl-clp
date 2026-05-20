# Security Policy

## Reporting

Report suspected security issues privately to Reuben Bowlby at `reuben@hummbl.io`.

Do not open public issues for secrets, exploit details, or sensitive operational findings.

## Scope

This repository currently contains stdlib-only Python source plus extraction scaffolding from founder-mode. The baseline security posture is:

- no secrets in repository content;
- stdlib-only validation tooling;
- local validation before pull request merge;
- Gitea CI for repository baseline checks.

## Response

Security reports should include:

- affected file or workflow;
- observed impact;
- reproduction steps, if safe to share;
- whether any secret, credential, or private operator data was exposed.
