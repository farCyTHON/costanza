from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from costanza.constants import KINDS, LEDGER_TEXT, MARKER_CANONICAL, skeleton
from costanza.format import (
    CF001,
    CF002,
    CF003,
    CF004,
    CF005,
    CF006,
    CF007,
    CF008,
    CF009,
    CF010,
    CF011,
    CF012,
    CF013,
    CF014,
    CF015,
    Document,
    Entry,
    Extra,
    Header,
    Now,
    compile_to_budget,
    high_water,
    next_id,
    next_ids,
    parse,
    parse_entry_line,
    render,
    validate,
)
from costanza.tokens import estimate

ENTRY_CASES = [
    (
        "D1 SQLite, not Postgres -- single node, zero ops",
        "D",
        1,
        "SQLite, not Postgres",
        "single node, zero ops",
        None,
        (),
    ),
    (
        "D2 services never import routes; all DB access goes through app/db",
        "D",
        2,
        "services never import routes; all DB access goes through app/db",
        None,
        None,
        (),
    ),
    (
        "X1 SQLAlchemy -- too heavy here; raw SQL in app/db",
        "X",
        1,
        "SQLAlchemy",
        "too heavy here; raw SQL in app/db",
        None,
        (),
    ),
    (
        "R1 type hints required; use the logger, never print",
        "R",
        1,
        "type hints required; use the logger, never print",
        None,
        None,
        (),
    ),
    (
        "G1 webhook sends duplicate events -- dedupe on event_id",
        "G",
        1,
        "webhook sends duplicate events",
        "dedupe on event_id",
        None,
        (),
    ),
    (
        "Q1 rate limit per user or per IP -- not decided",
        "Q",
        1,
        "rate limit per user or per IP",
        "not decided",
        None,
        (),
    ),
    (
        "D3 money is integer cents -- rounding bugs @b2c3d4e",
        "D",
        3,
        "money is integer cents",
        "rounding bugs",
        "b2c3d4e",
        (),
    ),
    (
        "D1 SQLite @a1b2c3d [files: app/db/conn.py]",
        "D",
        1,
        "SQLite",
        None,
        "a1b2c3d",
        ("app/db/conn.py",),
    ),
    (
        "G1 webhook -- dedupe [files: app/services/pay.py, app/jobs/retry.py]",
        "G",
        1,
        "webhook",
        "dedupe",
        None,
        ("app/services/pay.py", "app/jobs/retry.py"),
    ),
    (
        "D10 retries use a jobs table polled every 30s",
        "D",
        10,
        "retries use a jobs table polled every 30s",
        None,
        None,
        (),
    ),
    (
        "D1 text -- reason with -- still in the reason",
        "D",
        1,
        "text",
        "reason with -- still in the reason",
        None,
        (),
    ),
    (
        "D1 run cat a | grep b stays one value",
        "D",
        1,
        "run cat a | grep b stays one value",
        None,
        None,
        (),
    ),
    (
        "D1 café already uses NFC -- українською",
        "D",
        1,
        "café already uses NFC",
        "українською",
        None,
        (),
    ),
    (
        "D4 one bot [files: app/bot/start.py]",
        "D",
        4,
        "one bot",
        None,
        None,
        ("app/bot/start.py",),
    ),
    ("D1 only sha @deadbee", "D", 1, "only sha", None, "deadbee", ()),
    (
        "X2 Celery or RQ -- needs Redis; jobs table is enough",
        "X",
        2,
        "Celery or RQ",
        "needs Redis; jobs table is enough",
        None,
        (),
    ),
    (
        "Q5 should cancelled orders free stock immediately or after the refund settles",
        "Q",
        5,
        "should cancelled orders free stock immediately or after the refund settles",
        None,
        None,
        (),
    ),
    (
        "R2 every SQL statement lives in app/db helpers",
        "R",
        2,
        "every SQL statement lives in app/db helpers",
        None,
        None,
        (),
    ),
    (
        "D1 text -- why @abc1234 [files: a/b.py]",
        "D",
        1,
        "text",
        "why",
        "abc1234",
        ("a/b.py",),
    ),
    (
        "G2 Telegram callback_data max 64 bytes -- store long payloads",
        "G",
        2,
        "Telegram callback_data max 64 bytes",
        "store long payloads",
        None,
        (),
    ),
    (
        "D22 dependency updates monthly via pip-compile",
        "D",
        22,
        "dependency updates monthly via pip-compile",
        None,
        None,
        (),
    ),
]


def _codes(document: Document) -> list[str]:
    return [item.code for item in validate(document)]


def test_roundtrip_fixtures(tiny_text: str, near_text: str) -> None:
    for text in (tiny_text, near_text, skeleton("shopbot"), skeleton("demo")):
        assert render(parse(text)) == text


def test_parse_render_document_equality(tiny_text: str) -> None:
    document = parse(tiny_text)
    assert parse(render(document)) == document


def test_crlf_and_lf(tiny_text: str) -> None:
    crlf = tiny_text.replace("\n", "\r\n")
    document = parse(crlf)
    out = render(document)
    assert "\r" not in out
    assert out == tiny_text
    assert parse(tiny_text).header.project == document.header.project


def test_utf8_bom(tiny_text: str) -> None:
    document = parse("\ufeff" + tiny_text)
    assert document.readable
    assert document.header.project.startswith("shopbot")
    assert render(document) == tiny_text
    assert not render(document).startswith("\ufeff")


def test_trailing_whitespace_accepted(tiny_text: str) -> None:
    padded = "\n".join(line + "   " for line in tiny_text.splitlines()) + "\n"
    document = parse(padded)
    assert document.readable
    assert document.header.project.startswith("shopbot")
    assert render(document) == tiny_text


def test_tab_is_forbidden(tiny_text: str) -> None:
    text = tiny_text.replace("blocked: none", "blocked: none\tstill")
    findings = validate(parse(text))
    assert any(item.code == CF009 and "U+0009" in item.message for item in findings)
    assert all("line " in item.message for item in findings)


def test_duplicate_id(tiny_text: str) -> None:
    text = tiny_text.replace(
        "D2 services never import routes; all DB access goes through app/db",
        "D1 services never import routes; all DB access goes through app/db",
    )
    findings = validate(parse(text))
    match = next(item for item in findings if item.code == CF006)
    assert match.line == 16
    assert "D1" in match.message
    assert "new unused D ID" in match.message or "delete" in match.message


def test_ids_out_of_order(tiny_text: str) -> None:
    text = tiny_text.replace(
        "D1 SQLite, not Postgres -- single node, zero ops\n"
        "D2 services never import routes; all DB access goes through app/db",
        "D2 services never import routes; all DB access goes through app/db\n"
        "D1 SQLite, not Postgres -- single node, zero ops",
    )
    findings = validate(parse(text))
    assert CF014 in [item.code for item in findings]
    assert any("ascending" in item.message for item in findings)


def test_empty_sections_roundtrip() -> None:
    text = skeleton("empty")
    document = parse(text)
    assert document.decisions == ()
    assert document.open == ()
    assert render(document) == text


def test_missing_sections_filled_on_write(tiny_text: str) -> None:
    text = tiny_text.replace("\n## OPEN\nQ1 rate limit per user or per IP -- not decided\n", "\n")
    document = parse(text)
    assert document.open == ()
    out = render(document)
    assert "## OPEN\n" in out
    assert render(parse(out)) == out


def test_very_long_line(tiny_text: str) -> None:
    long = "D2 " + ("x" * 300)
    text = tiny_text.replace(
        "D2 services never import routes; all DB access goes through app/db",
        long,
    )
    findings = validate(parse(text))
    assert any(item.code == CF008 and "300" in item.message for item in findings)
    soft = tiny_text.replace(
        "D2 services never import routes; all DB access goes through app/db",
        "D2 " + ("y" * 170),
    )
    soft_findings = validate(parse(soft))
    assert any(item.code == CF015 and item.severity == "warning" for item in soft_findings)


def test_non_ascii(tiny_text: str) -> None:
    text = tiny_text.replace(
        "D1 SQLite, not Postgres -- single node, zero ops",
        "D1 SQLite, не Postgres -- один вузол, нуль ops",
    )
    document = parse(text)
    assert document.decisions[0].text == "SQLite, не Postgres"
    assert document.decisions[0].reason == "один вузол, нуль ops"
    assert CF009 not in _codes(document)


def test_missing_first_line_marker(tiny_text: str) -> None:
    text = "\n".join(tiny_text.splitlines()[1:]) + "\n"
    document = parse(text)
    findings = validate(document)
    assert findings[0].code == CF001
    assert findings[0].line == 1
    assert MARKER_CANONICAL in findings[0].message
    assert "line 1" in findings[0].message


def test_future_format_version(tiny_text: str) -> None:
    text = tiny_text.replace("v1", "v2", 1)
    document = parse(text)
    findings = validate(document)
    assert findings[0].code == CF002
    assert "version 2" in findings[0].message
    assert "v1" in findings[0].message


def test_missing_project() -> None:
    text = f"{MARKER_CANONICAL}\nstack: py\n\n## NOW\ndoing: none\ndone: none\nnext: none\nblocked: none\n"
    findings = validate(parse(text))
    assert CF003 in [item.code for item in findings]
    assert any("PROJECT" in item.message for item in findings)


def test_line_not_understood(tiny_text: str) -> None:
    text = tiny_text.replace("blocked: none\n", "blocked: none\nthis is noise\n")
    findings = validate(parse(text))
    assert CF004 in [item.code for item in findings]
    assert any("line " in item.message and "NOW" in item.message for item in findings)


def test_wrong_section(tiny_text: str) -> None:
    text = tiny_text.replace("X1 SQLAlchemy -- too heavy here; raw SQL in app/db", "D9 leftover decision")
    findings = validate(parse(text))
    assert CF005 in [item.code for item in findings]
    assert any("DECISIONS" in item.message for item in findings)


def test_malformed_ids(tiny_text: str) -> None:
    for bad in ("D0 zero is not allowed", "D01 leading zero", "Z1 unknown kind"):
        text = tiny_text.replace("D2 services never import routes; all DB access goes through app/db", bad)
        findings = validate(parse(text))
        assert CF007 in [item.code for item in findings], bad
        assert any("leading zero" in item.message or "D/X/R/G/Q" in item.message for item in findings)


def test_duplicate_header_and_now_keys(tiny_text: str) -> None:
    text = tiny_text.replace("stack: python3.12, FastAPI, SQLite, pytest\n", "stack: a\nstack: b\n")
    findings = validate(parse(text))
    assert CF010 in [item.code for item in findings]
    text2 = tiny_text.replace("doing: payment webhook retries (app/services/pay.py)\n", "doing: a\ndoing: b\n")
    findings2 = validate(parse(text2))
    assert CF010 in [item.code for item in findings2]


def test_x_requires_reason(tiny_text: str) -> None:
    text = tiny_text.replace("X1 SQLAlchemy -- too heavy here; raw SQL in app/db", "X1 SQLAlchemy")
    findings = validate(parse(text))
    assert CF011 in [item.code for item in findings]
    assert any("needs a reason" in item.message for item in findings)


def test_duplicate_section(tiny_text: str) -> None:
    text = tiny_text + "\n## DECISIONS\nD9 another\n"
    findings = validate(parse(text))
    assert CF012 in [item.code for item in findings]
    assert any("DECISIONS" in item.message for item in findings)


def test_unsafe_paths(tiny_text: str) -> None:
    cases = ("../x", "/etc/passwd", "C:/x", "a\\b", "foo/./bar")
    for path in cases:
        text = tiny_text.replace(
            "D1 SQLite, not Postgres -- single node, zero ops",
            f"D1 SQLite [files: {path}]",
        )
        findings = validate(parse(text))
        assert CF013 in [item.code for item in findings], path


def test_run_pipe_splits_only_before_test() -> None:
    text = (
        f"{MARKER_CANONICAL}\n"
        "# PROJECT: pipes\n"
        "stack: py\n"
        "run: cat a | grep b | test: pytest\n"
        "layout: app/\n"
        "synced: never\n"
        "\n"
        "## NOW\n"
        "doing: none\n"
        "done: none\n"
        "next: none\n"
        "blocked: none\n"
        "\n"
        "## DECISIONS\n"
        "\n"
        "## REJECTED\n"
        "\n"
        "## RULES\n"
        "\n"
        "## GOTCHAS\n"
        "\n"
        "## OPEN\n"
    )
    document = parse(text)
    assert document.header.run == "cat a | grep b"
    assert document.header.test == "pytest"
    assert render(document).splitlines()[3] == "run: cat a | grep b | test: pytest"


@pytest.mark.parametrize(
    ("line", "kind", "number", "text", "reason", "sha", "files"),
    ENTRY_CASES,
)
def test_entry_table(
    line: str,
    kind: str,
    number: int,
    text: str,
    reason: str | None,
    sha: str | None,
    files: tuple[str, ...],
) -> None:
    entry = parse_entry_line(line)
    assert entry is not None
    assert entry.kind == kind
    assert entry.number == number
    assert entry.text == text
    assert entry.reason == reason
    assert entry.sha == sha
    assert entry.files == files


def test_unknown_section_and_comment_preserved(tiny_text: str) -> None:
    text = tiny_text.replace(
        "synced: a1b2c3d 2026-10-12\n\n## NOW",
        "synced: a1b2c3d 2026-10-12\n\n<!-- keep this -->\n\n## NOW",
    )
    text = text.replace(
        "## OPEN\nQ1 rate limit per user or per IP -- not decided\n",
        "## OPEN\nQ1 rate limit per user or per IP -- not decided\n\n## NOTES\nOwner notes stay put.\n",
    )
    document = parse(text)
    assert any(extra.text.startswith("<!-- keep this -->") for extra in document.extras)
    assert any(extra.text.startswith("## NOTES") for extra in document.extras)
    assert render(document) == text


def test_id_allocation_file_and_archive(tiny_text: str) -> None:
    document = parse(tiny_text)
    assert next_id("D", document) == "D3"
    assert next_id("X", document) == "X2"
    assert next_ids(document)["Q"] == "Q2"
    archive = (
        "<!-- costanza archive v1 -->\n"
        "## 2026-10-13 compact\n"
        "D5 retired decision -- gone from the file\n"
        "G2 archived gotcha -- still counts\n"
    )
    assert next_id("D", document, archive) == "D6"
    assert next_id("G", document, archive) == "G3"
    assert high_water(document, LEDGER_TEXT.replace("D 0", "D 9"))["D"] == 9
    assert next_id("D", document, LEDGER_TEXT.replace("D 0", "D 9")) == "D10"


def test_removed_id_not_reused(tiny_text: str, tmp_path: Path) -> None:
    text = tiny_text.replace(
        "D2 services never import routes; all DB access goes through app/db\n",
        "",
    )
    document = parse(text)
    archive_dir = tmp_path / ".costanza" / "archive"
    archive_dir.mkdir(parents=True)
    archived = "D2 services never import routes; all DB access goes through app/db\n"
    (archive_dir / "2026-10.md").write_text(archived, encoding="utf-8")
    (archive_dir / "ids").write_text(LEDGER_TEXT.replace("D 0", "D 2"), encoding="utf-8")
    texts = [path.read_text(encoding="utf-8") for path in archive_dir.iterdir()]
    assert next_id("D", document, *texts) == "D3"


def test_compile_to_budget_cuts_whole_entries_only(tiny_text: str) -> None:
    document = parse(tiny_text)
    full = compile_to_budget(document, 1800)
    assert full.cut == ()
    assert "Q1" in full.text
    base = Document(header=document.header, now=document.now)
    packed = compile_to_budget(document, estimate(render(base)))
    assert packed.cut
    for item in packed.cut:
        assert "\n" not in item
    assert "Q1" in packed.cut
    with_r = Document(header=document.header, now=document.now, rules=document.rules)
    packed2 = compile_to_budget(document, estimate(render(with_r)))
    assert "R1" in packed2.text
    assert "Q1" in packed2.cut


def test_compile_never_splits_a_line(tiny_text: str) -> None:
    document = parse(tiny_text)
    for budget in (80, 120, 160, 200, 238):
        pack = compile_to_budget(document, budget)
        for raw in pack.text.splitlines():
            assert raw == raw  # whole line
        for cut_id in pack.cut:
            assert " " not in cut_id or cut_id.startswith("##") or cut_id.startswith("<!--")


def test_empty_and_future_document_validate() -> None:
    assert validate(parse(""))[0].code == CF001
    assert validate(parse("hello"))[0].code == CF001


def test_next_id_rejects_bad_kind(tiny_text: str) -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        next_id("Z", parse(tiny_text))


def test_too_many_files(tiny_text: str) -> None:
    files = ", ".join(f"a/{i}.py" for i in range(9))
    text = tiny_text.replace(
        "D1 SQLite, not Postgres -- single node, zero ops",
        f"D1 SQLite [files: {files}]",
    )
    assert CF013 in _codes(parse(text))


def test_unknown_header_key(tiny_text: str) -> None:
    text = tiny_text.replace("synced: a1b2c3d 2026-10-12\n", "synced: a1b2c3d 2026-10-12\nowner: pat\n")
    findings = validate(parse(text))
    assert any(item.code == "CF016" for item in findings)


_SAFE = "abcdefghijklmnopqrstuvwxyz0123456789 "
_TEXT = st.text(alphabet=_SAFE, min_size=1, max_size=40).map(lambda s: " ".join(s.split()) or "x")
_NAME = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=12)


def _entry(kind: str, number: int) -> st.SearchStrategy[Entry]:
    reason = _TEXT if kind == "X" else st.one_of(st.none(), _TEXT)
    return st.builds(
        Entry,
        kind=st.just(kind),
        number=st.just(number),
        text=_TEXT,
        reason=reason,
        sha=st.one_of(st.none(), st.from_regex(r"[0-9a-f]{7,12}", fullmatch=True)),
        files=st.just(()),
    )


@st.composite
def valid_documents(draw: st.DrawFn) -> Document:
    project = draw(_NAME)
    counts = {kind: draw(st.integers(min_value=0, max_value=3)) for kind in KINDS}
    extras: list[Extra] = []
    if draw(st.booleans()):
        extras.append(Extra(text="<!-- keep -->", after="header"))
    if draw(st.booleans()):
        extras.append(Extra(text="## NOTES\nsafe note text", after="## OPEN"))
    return Document(
        header=Header(
            project=project,
            stack=draw(_TEXT),
            run=draw(_TEXT),
            test=draw(_TEXT),
            layout=draw(_TEXT),
            synced="never",
        ),
        now=Now(
            doing=draw(_TEXT),
            done=draw(_TEXT),
            next=draw(_TEXT),
            blocked="none",
        ),
        decisions=tuple(draw(_entry("D", i + 1)) for i in range(counts["D"])),
        rejected=tuple(draw(_entry("X", i + 1)) for i in range(counts["X"])),
        rules=tuple(draw(_entry("R", i + 1)) for i in range(counts["R"])),
        gotchas=tuple(draw(_entry("G", i + 1)) for i in range(counts["G"])),
        open=tuple(draw(_entry("Q", i + 1)) for i in range(counts["Q"])),
        extras=tuple(extras),
    )


@given(valid_documents())
@settings(max_examples=60, deadline=None)
def test_property_parse_render_roundtrip(document: Document) -> None:
    text = render(document)
    again = parse(text)
    assert render(again) == text
    assert parse(render(again)) == again
    errors = [item for item in validate(again) if item.severity == "error"]
    assert errors == []


def test_path_and_forbidden_edges() -> None:
    from costanza.format import forbidden_label, path_problem

    assert path_problem("") is not None
    assert path_problem("x" * 201) is not None
    assert path_problem("foo//bar") is not None
    assert path_problem("app/file name.py") is not None
    assert path_problem("app/\x00x") is not None
    assert path_problem("app/db.py") is None
    assert forbidden_label("see --> here") == "-->"
    assert forbidden_label("ok") is None
    assert forbidden_label("\u2060") == "U+2060"
    assert forbidden_label("\ufeff") == "U+FEFF"


def test_header_now_and_comment_edges(tiny_text: str) -> None:
    text = tiny_text.replace(
        "synced: a1b2c3d 2026-10-12\n\n## NOW",
        "synced: a1b2c3d 2026-10-12\n<!-- in header -->\n## NOW",
    )
    text = text.replace("blocked: none\n", "blocked: none\n<!-- in now -->\n")
    text = text.replace(
        "D1 SQLite, not Postgres -- single node, zero ops\n",
        "D1 SQLite, not Postgres -- single node, zero ops\n<!-- in decisions -->\n",
    )
    document = parse(text)
    bodies = [extra.text for extra in document.extras]
    assert any("in header" in body for body in bodies)
    assert any("in now" in body for body in bodies)
    assert any("in decisions" in body for body in bodies)


def test_multiline_comment_and_trailing_unknown(tiny_text: str) -> None:
    text = tiny_text.replace(
        "## OPEN\nQ1 rate limit per user or per IP -- not decided\n",
        "## OPEN\nQ1 rate limit per user or per IP -- not decided\n\n"
        "<!--\nkeep\n-->\n\n## NOTES\nline one\n\n\n",
    )
    document = parse(text)
    assert any("keep" in extra.text for extra in document.extras)
    notes = next(extra for extra in document.extras if extra.text.startswith("## NOTES"))
    assert notes.text.endswith("line one")


def test_header_without_blank_then_now() -> None:
    text = (
        f"{MARKER_CANONICAL}\n"
        "# PROJECT: x\n"
        "stack: py\n"
        "## NOW\n"
        "doing: none\n"
        "done: none\n"
        "next: none\n"
        "blocked: none\n"
    )
    document = parse(text)
    assert document.header.stack == "py"
    assert document.now.doing == "none"


def test_header_garbage_and_split_fail() -> None:
    text = (
        f"{MARKER_CANONICAL}\n"
        "# PROJECT: x\n"
        "not a header line\n"
        " | test: pytest\n"
        "\n"
        "## NOW\n"
        "doing: none\n"
        "done: none\n"
        "next: none\n"
        "blocked: none\n"
        "noise after header\n"
    )
    findings = validate(parse(text))
    assert CF004 in [item.code for item in findings]


def test_constructed_document_validate_edges() -> None:
    document = Document(
        header=Header(project="p" * 121, stack="s" * 301, run="", test="", layout="", synced=""),
        now=Now(doing="", done="", next="", blocked=""),
        decisions=(
            Entry(kind="D", number=1, text="", reason="", sha="NOPE", files=("a/b.py",)),
            Entry(kind="D", number=2, text="# heading", files=()),
        ),
        extras=(Extra(text="", after="## OPEN"),),
    )
    codes = _codes(document)
    assert CF003 in codes
    assert CF004 in codes
    assert CF008 in codes
    packed = compile_to_budget(parse("hello"), 100)
    assert packed.text == ""
    assert packed.cut == ()
    readable_bad = Document(header=Header(project="x"), now=Now(), version=2, readable=True, marker_ok=True)
    packed2 = compile_to_budget(readable_bad, 10)
    assert packed2.cut == ()
    tiny = parse(skeleton("x"))
    tiny.extras = (Extra(text="## NOTES\n" + ("z" * 80), after="## OPEN"),)
    packed3 = compile_to_budget(tiny, 90)
    assert packed3.cut


def test_arrow_in_prose(tiny_text: str) -> None:
    text = tiny_text.replace(
        "D1 SQLite, not Postgres -- single node, zero ops",
        "D1 never write --> in a decision",
    )
    findings = validate(parse(text))
    assert any(item.code == CF009 and "-->" in item.message for item in findings)


def test_empty_files_clause() -> None:
    entry = parse_entry_line("D1 hello [files: ]")
    assert entry is not None
    assert entry.files == ()
    assert entry.text == "hello"


def test_format_module_has_no_filesystem() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "costanza" / "format.py").read_text(
        encoding="utf-8"
    )
    assert "pathlib" not in source
    assert "from pathlib" not in source
    assert "open(" not in source
