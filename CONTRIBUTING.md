# Contributing

## Local Validation

Run the repository baseline validator before opening a pull request:

```powershell
C:\Users\Owner\bin\python.cmd tools\validate_repo.py
```

The validator is stdlib-only. It checks required root policy files, local Markdown links, and Python source syntax under `src/`.

## Pull Request Expectations

- Keep CLP terminology aligned with the repository's current extraction status.
- Mark planned or not-yet-extracted surfaces explicitly instead of implying they already exist.
- Do not add third-party runtime dependencies without a documented reason in the PR.
- Include the validation command output in PR evidence.
