# Contributing

Thanks for helping. A few rules keep Postcrew small and trustworthy:

- **Standard library first.** The only runtime dependency is Pillow. Please do not add frameworks.
- **Accuracy over cleverness.** Any change that lets unverified facts, numbers or links reach a post needs a
  very good reason and a test.
- **Tests run offline.** `python3 -m unittest discover -s tests` fakes the LLM, the web and LinkedIn. New
  agents and checks need tests that use those fakes (`tests/helpers.py`).
- **Every agent has `run` and `validate`.** Validation should be deterministic wherever possible; use the LLM
  for judgment, not for checks a program can do.
- **No personal data in the repo.** Examples use placeholder names and `example.com`.
- Keep prompts in `postcrew/prompts/*.md`, not in code.

Pull requests: describe what changes for a user, include tests, keep the diff focused.

New here? Issues labelled [good first issue](https://github.com/sudip1205/social-postcrew/labels/good%20first%20issue)
are small and self-contained; [help wanted](https://github.com/sudip1205/social-postcrew/labels/help%20wanted) are
bigger. Questions go to [Discussions](https://github.com/sudip1205/social-postcrew/discussions). `postcrew demo`
gives you a full run to test against without any account.
