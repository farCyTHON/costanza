# Releasing

Nothing is pushed, tagged, or published until the author says the project is finished. That includes this checklist. The files it names are in the repository so a later release has a procedure. Creating them does not start a release.

This clone has no git remote. Do not add one, do not push, and do not create a hosting project as part of ordinary work.

## Before a release the author has asked for

1. `pytest` exits 0.
2. `ruff check` exits 0. The CI workflow runs `ruff check src tests`.
3. `mypy src` exits 0.
4. `python -m build` writes `dist/`.
5. `twine check dist/*` passes.
6. Install that wheel into a clean virtual environment. `costanza --help` and `costanza init` succeed there.
7. `CHANGELOG.md` matches the version in `pyproject.toml`.
8. `pyproject.toml` `[project.urls] Homepage` is `https://github.com/costanza-dev/costanza`. This clone has no remote, so that URL is a placeholder. Replace it with the real project URL before publishing.
9. Confirm the PyPI name again. On 2026-10-24, `https://pypi.org/pypi/costanza/json` returned HTTP 404, so no project of that name was registered then. Do not register the name until the author says to publish.
10. On PyPI, a pending trusted publisher for the real GitHub repository, the workflow file `.github/workflows/publish-pypi.yml`, and the GitHub environment `pypi`. The packaging guide checked on 2026-10-24 says to require manual approval on that environment. The guide's page is `Publishing package distribution releases using GitHub Actions CI/CD workflows`.
11. Tag, from a clean tree, only when the author has said to publish. The workflow triggers on a tag that looks like `v1.2.3`. Do not push the tag until that same yes.

The workflow builds the distributions in one job and publishes them in another, which is what that guide requires. It publishes to PyPI only, and only on a version tag. It does not publish on an ordinary push. It is not a substitute for the author saying the project is finished.

## Out of scope until the author says otherwise

- `git push`
- adding a remote
- creating a hosted repository
- `git tag`
- `twine upload`
- registering the PyPI project
- triggering `.github/workflows/publish-pypi.yml`
