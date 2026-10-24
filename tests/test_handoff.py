from __future__ import annotations

from pathlib import Path

from costanza.constants import HANDOFF_PREAMBLE, PASTE_PROMPT, PROMPT_BOOTSTRAP
from costanza.format import compile_to_budget, parse
from costanza.handoff import build_handoff
from costanza.tokens import estimate
from tests.helpers import InvokeFn


def _write(root: Path, text: str) -> None:
    (root / ".costanza").mkdir(exist_ok=True)
    (root / "COSTANZA.md").write_text(text, encoding="utf-8", newline="\n")


def test_prompt_is_one_sentence_bootstrap(invoke: InvokeFn, tmp_path: Path) -> None:
    _write(tmp_path, "# PROJECT: t\n")
    result = invoke(["--root", str(tmp_path), "prompt"])
    assert result.exit_code == 0
    assert result.stdout == PROMPT_BOOTSTRAP + "\n"
    assert result.stdout.strip().count(".") >= 1
    assert "COSTANZA.md" in result.stdout


def test_handoff_pack_stays_within_budget(
    tmp_path: Path, tiny_text: str, near_text: str
) -> None:
    for source in (tiny_text, near_text):
        _write(tmp_path, source)
        document = parse(source)
        floor = compile_to_budget(document, 1).tokens
        full = compile_to_budget(document, 10**9)
        previous = 0
        for budget in (200, 400, 800, 1200, 1800):
            packed = build_handoff(budget=budget, explicit=tmp_path)
            assert packed.file_tokens <= max(budget, floor)
            assert packed.file_tokens <= full.tokens
            if budget >= estimate(source):
                assert packed.cut == ()
            assert packed.file_tokens >= previous
            previous = packed.file_tokens


def test_handoff_for_chat_has_preamble_and_paste_prompt(
    invoke: InvokeFn, tmp_path: Path, tiny_text: str
) -> None:
    _write(tmp_path, tiny_text)
    result = invoke(["--root", str(tmp_path), "handoff", "--for", "chat", "--budget", "1800"])
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith(HANDOFF_PREAMBLE)
    assert "ask the author" in result.stdout
    assert "never search outside the project folder" in result.stdout
    assert "Format only. This is not project data." in result.stdout
    assert "now doing: <one line>" in result.stdout
    assert "payment webhook" not in HANDOFF_PREAMBLE
    assert PASTE_PROMPT.strip() in result.stdout
    assert "```costanza" in result.stdout
    assert "handoff" in result.stderr
    assert result.stderr.count("\n") == 1 or result.stderr.strip().count("\n") == 0


def test_handoff_default_is_compiled_pack(
    invoke: InvokeFn, tmp_path: Path, tiny_text: str
) -> None:
    _write(tmp_path, tiny_text)
    result = invoke(["--root", str(tmp_path), "handoff", "--budget", "1800"])
    assert result.exit_code == 0, result.output
    assert not result.stdout.startswith("You are continuing")
    assert "# PROJECT:" in result.stdout
    assert "```costanza" not in result.stdout


def test_handoff_out_and_with_inbox(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    _write(tmp_path, tiny_text)
    invoke(["--root", str(tmp_path), "decide", "handoff covers inbox -- so we can see it"])
    dest = tmp_path / "packet.txt"
    result = invoke(
        [
            "--root",
            str(tmp_path),
            "handoff",
            "--for",
            "chat",
            "--with-inbox",
            "--out",
            str(dest),
        ]
    )
    assert result.exit_code == 0, result.output
    text = dest.read_text(encoding="utf-8")
    assert "PENDING (proposed, not ratified):" in text
    assert "handoff covers inbox" in text


def test_handoff_no_prompt_omits_fence(invoke: InvokeFn, tmp_path: Path, tiny_text: str) -> None:
    _write(tmp_path, tiny_text)
    result = invoke(
        ["--root", str(tmp_path), "handoff", "--for", "chat", "--no-prompt"]
    )
    assert result.exit_code == 0
    assert result.stdout.startswith(HANDOFF_PREAMBLE)
    assert "now doing: <one line>" in result.stdout
    assert "reject: <one line>" not in result.stdout


def test_handoff_copy_without_backend_prints_stdout(
    invoke: InvokeFn, tmp_path: Path, tiny_text: str, monkeypatch: object
) -> None:
    from costanza import clipboard
    from costanza.exceptions import ClipboardUnavailable

    _write(tmp_path, tiny_text)

    def boom(_text: str) -> object:
        raise ClipboardUnavailable(
            "no clipboard tool found; printed to stdout instead",
            "cz handoff --out handoff.txt",
        )

    monkeypatch.setattr(clipboard, "copy", boom)
    result = invoke(["--root", str(tmp_path), "handoff", "--copy", "--for", "chat"])
    assert result.exit_code == 1
    assert "# PROJECT:" in result.stdout
    assert "no clipboard tool found" in result.stderr
    assert "cz handoff --out handoff.txt" in result.stderr
