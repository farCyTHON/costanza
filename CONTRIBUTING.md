# Contributing

Costanza is a local Python tool. Python 3.10 through 3.13.

```
python -m pip install -e ".[dev]"
pytest
ruff check
mypy src
```

CI runs `ruff check src tests` and `mypy src` on Windows, macOS, and Linux, on Python 3.10, 3.11, 3.12, and 3.13.

Write tests with the change and run them. Do not claim a check passed without its output.

Do not add a dependency unless the change cannot be done with the standard library or the packages already in `pyproject.toml`.

Core code stays cross-platform: `pathlib`, explicit UTF-8, no shell-specific behavior.

`docs/SPEC.md` is the behavior spec. If a command and the spec disagree, trust the command you ran, and say so. Do not add a command or a flag this repository does not already have.

Proposals that belong in `COSTANZA.md` go through `costanza decide`, `reject`, `rule`, `gotcha`, or `ask`. Do not edit the decision sections by hand to sneak a line in. Accepting needs a person at a terminal.

Do not run `git push`, add a remote, create a hosted repository, tag a release, or publish a package. `docs/RELEASING.md` is the checklist for when the author says the project is finished. Until then, none of that happens.

Nothing in a pull request should contain a secret. `costanza check` looks for a few token shapes in `COSTANZA.md`. It does not scan the rest of the tree.
