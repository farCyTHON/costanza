from __future__ import annotations

from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from costanza.paste import parse_item_line, parse_paste
from tests.helpers import InvokeFn

VALID_TYPES = ("decide", "reject", "rule", "gotcha", "ask")


def _init(invoke: InvokeFn, root: Path) -> None:
    result = invoke(["--root", str(root), "init", "--agents", "none"])
    assert result.exit_code == 0, result.output


def test_two_blocks_in_order(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    text = """\
Sure, here is the update.

```costanza
decide: use SQLite -- single node
now doing: webhooks
```

and more chat

~~~costanza
reject: SQLAlchemy -- too heavy
rule: type hints required
~~~
"""
    result = invoke(["--root", str(tmp_path), "paste"], input=text)
    assert result.exit_code == 0, result.output
    listed = invoke(["--root", str(tmp_path), "list", "--json"])
    assert listed.exit_code == 0
    assert '"source":"paste"' in listed.stdout
    assert listed.stdout.count('"kind":"D"') == 1
    assert listed.stdout.count('"kind":"X"') == 1
    assert listed.stdout.count('"kind":"R"') == 1
    now = invoke(["--root", str(tmp_path), "now", "--json"])
    assert '"doing":"webhooks"' in now.stdout


def test_malformed_writes_nothing(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    text = """\
```costanza
decide: ok -- why
decision: bad
reject: no reason
```
"""
    before = (tmp_path / ".costanza" / "inbox.jsonl")
    result = invoke(["--root", str(tmp_path), "paste"], input=text)
    assert result.exit_code == 2
    assert "line 3:" in result.stderr
    assert "line 4:" in result.stderr
    assert "nothing was written" in result.stderr
    assert not before.exists() or before.read_text(encoding="utf-8") == ""


def test_partial_applies_good_lines(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    text = """\
```costanza
decide: keep me -- because
decision: bad
```
"""
    result = invoke(["--root", str(tmp_path), "paste", "--partial"], input=text)
    assert result.exit_code == 2
    listed = invoke(["--root", str(tmp_path), "list"])
    assert "keep me" in listed.stdout


def test_unfenced_body_only_when_every_line_parses() -> None:
    items, issues = parse_paste("decide: a -- b\nrule: r\n")
    assert issues == []
    assert [item.kind for item in items] == ["D", "R"]
    items, issues = parse_paste("decide: a -- b\nthanks!\n")
    assert any("no costanza block found" in issue.message for issue in issues)


def test_lenient_bullets_smart_quotes_and_open_fence() -> None:
    text = """\
```costanza
- DECIDE: SQLite — single node
* reject: ORM -- too heavy
now doing: retries
"""
    items, issues = parse_paste(text)
    assert issues == []
    assert items[0].kind == "D"
    assert items[0].text == "SQLite"
    assert items[0].why == "single node"
    assert items[1].kind == "X"
    assert items[2].now_key == "doing"


def test_sha_and_unknown_now_are_reported() -> None:
    text = """\
```costanza
decide: x -- y @abc1234
now later: nope
```
"""
    _items, issues = parse_paste(text)
    messages = " ".join(issue.message for issue in issues)
    assert "commit refs" in messages
    assert "now key must be" in messages
    assert any(issue.line == 2 for issue in issues)
    assert any(issue.line == 3 for issue in issues)


def test_duplicate_now_key() -> None:
    _items, issues = parse_paste("```costanza\nnow doing: a\nnow doing: b\n```\n")
    assert any("appears twice" in issue.message for issue in issues)


def test_text_after_closing_fence_is_ignored(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    text = """\
Here is the update.

```costanza
decide: keep sqlite -- one file
```

Thanks, that is all. Please ignore this decide: not a real line
"""
    result = invoke(["--root", str(tmp_path), "paste"], input=text)
    assert result.exit_code == 0, result.output
    listed = invoke(["--root", str(tmp_path), "list"])
    assert "keep sqlite" in listed.stdout
    assert "not a real line" not in listed.stdout


def test_file_option(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    paste_file = tmp_path / "reply.txt"
    paste_file.write_text("```costanza\nask: per user or per IP?\n```\n", encoding="utf-8")
    result = invoke(["--root", str(tmp_path), "paste", "--file", str(paste_file)])
    assert result.exit_code == 0, result.output
    listed = invoke(["--root", str(tmp_path), "list"])
    assert "per user" in listed.stdout


def test_dry_run_writes_nothing(invoke: InvokeFn, tmp_path: Path) -> None:
    _init(invoke, tmp_path)
    result = invoke(
        ["--root", str(tmp_path), "paste", "--dry-run"],
        input="```costanza\ndecide: a -- b\n```\n",
    )
    assert result.exit_code == 0, result.output
    inbox = tmp_path / ".costanza" / "inbox.jsonl"
    assert not inbox.exists() or inbox.read_text(encoding="utf-8") == ""


_word = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters=" -_"),
    min_size=1,
    max_size=24,
).filter(lambda value: value.strip() and not value.strip().startswith("#"))


@given(
    kind=st.sampled_from(VALID_TYPES),
    body=_word,
    why=_word,
    bullet=st.sampled_from(["", "- ", "* ", "• "]),
    quotes=st.booleans(),
    fence=st.sampled_from(["```", "~~~"]),
    close=st.booleans(),
    chatter=st.sampled_from(["", "ok\n", "Thanks!\n\n"]),
)
@settings(max_examples=80, deadline=None)
def test_fuzz_messy_chat(
    kind: str,
    body: str,
    why: str,
    bullet: str,
    quotes: bool,
    fence: str,
    close: bool,
    chatter: str,
) -> None:
    reason = f" -- {why}" if kind == "reject" or why.strip() else ""
    payload = f"{kind}: {body}{reason}"
    if quotes:
        payload = payload.replace(" -- ", " — ")
    block = f"{chatter}{fence}costanza\n{bullet}{payload}\n"
    if close:
        block += f"{fence}\n"
    items, issues = parse_paste(block)
    if issues:
        assert all(issue.line >= 1 for issue in issues)
        return
    assert items
    assert items[0].kind in {"D", "X", "R", "G", "Q"}


def test_parse_item_line_spaces_around_colon() -> None:
    item, issue, ignored = parse_item_line("  decide :  hello -- why  ", 1)
    assert not ignored
    assert issue is None
    assert item is not None
    assert item.text == "hello"
    assert item.why == "why"
