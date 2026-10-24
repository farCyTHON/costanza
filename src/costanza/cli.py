"""Typer command shell. Parse arguments, call the library, print via ui."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from costanza import __version__, ui
from costanza import init as init_mod
from costanza import status as status_mod
from costanza.constants import COMMAND_STEPS
from costanza.exceptions import CostanzaError

app = typer.Typer(
    name="costanza",
    help="Keep a small, ratified handoff file any model can continue from.",
    no_args_is_help=False,
    add_completion=False,
    pretty_exceptions_enable=False,
    pretty_exceptions_show_locals=False,
)

agents_app = typer.Typer(
    name="agents",
    help="Install or remove agent instruction blocks.",
    no_args_is_help=False,
    add_completion=False,
    pretty_exceptions_enable=False,
)
hook_app = typer.Typer(
    name="hook",
    help="Install or remove the git post-commit hook.",
    no_args_is_help=False,
    add_completion=False,
    pretty_exceptions_enable=False,
)


@dataclass
class Globals:
    root: Path | None = None
    quiet: bool = False
    no_color: bool | None = None


RootOpt = Annotated[
    Path | None,
    typer.Option(
        "--root",
        help="Project root; skips discovery.",
        show_default=False,
        rich_help_panel="Global options",
    ),
]
QuietOpt = Annotated[
    bool | None,
    typer.Option(
        "--quiet",
        "-q",
        help="Only errors and requested data.",
        rich_help_panel="Global options",
    ),
]
NoColorOpt = Annotated[
    bool | None,
    typer.Option(
        "--no-color",
        help="Disable colour.",
        rich_help_panel="Global options",
    ),
]


def merge(
    state: Globals,
    root: Path | None,
    quiet: bool | None,
    no_color: bool | None,
) -> Globals:
    if root is not None:
        state.root = root
    if quiet is not None:
        state.quiet = quiet
    if no_color is not None:
        state.no_color = no_color
    return state


def _version(value: bool) -> None:
    if value:
        ui.write_line(f"costanza {__version__}")
        raise typer.Exit()


def _prepare(
    ctx: typer.Context,
    root: Path | None,
    quiet: bool | None,
    no_color: bool | None,
) -> Globals:
    state = ctx.ensure_object(Globals)
    merged = merge(state, root, quiet, no_color)
    ui.configure(no_color=merged.no_color, quiet=merged.quiet)
    from costanza.gate import install

    install(ui.ask_yes_no)
    return merged


def _handle_domain(exc: BaseException) -> None:
    if os.environ.get("COSTANZA_DEBUG") == "1":
        ui.debug_traceback(exc)
    if isinstance(exc, CostanzaError):
        ui.error_panel(exc.message, exc.hint)
        raise typer.Exit(exc.exit_code) from None
    ui.error_panel(
        f"unexpected error: {type(exc).__name__}: {exc}",
        "rerun with COSTANZA_DEBUG=1 and report the output",
    )
    raise typer.Exit(1) from None


def _run(work: Callable[[], None]) -> None:
    from costanza import tokens

    tokens.begin_command()
    tokens.set_warn(ui.warn)
    try:
        work()
    except KeyboardInterrupt:
        ui.write_line("cancelled", err=True)
        raise typer.Exit(130) from None
    except (CostanzaError, Exception) as exc:
        if isinstance(exc, typer.Exit):
            raise
        _handle_domain(exc)
    finally:
        warning = tokens.take_warning()
        if warning:
            ui.warn(warning)


def _later(name: str) -> None:
    ui.deferred(name, COMMAND_STEPS[name])
    raise typer.Exit(2)


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True, help="Show version and exit."),
    ] = False,
) -> None:
    """Keep a small, ratified handoff file any model can continue from."""
    ctx.obj = Globals()
    merge(ctx.obj, root, quiet, no_color)
    ui.configure(no_color=ctx.obj.no_color, quiet=ctx.obj.quiet)
    if ctx.invoked_subcommand is None:
        _show_welcome()


@app.command()
def init(
    ctx: typer.Context,
    force: Annotated[bool, typer.Option("--force", help="Replace COSTANZA.md and config.toml.")] = False,
    name: Annotated[str | None, typer.Option("--name", help="PROJECT line; default is the directory name.")] = None,
    agents: Annotated[
        str | None,
        typer.Option("--agents", help="Install agent instructions: auto, all, or none."),
    ] = None,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Create COSTANZA.md and .costanza/ in this project."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.exceptions import UsageError

        mode = agents
        if mode is None:
            mode = ui.ask_agents_mode() if ui.is_tty() else "auto"
        mode = mode.strip().lower()
        if mode not in {"auto", "all", "none"}:
            raise UsageError("agents mode must be auto, all or none", "cz init --agents auto")
        result = init_mod.initialize(explicit=opts.root, force=force, name=name, agents=mode)
        ui.render_init(result)

    _run(work)


@app.command()
def status(
    ctx: typer.Context,
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Show the project summary and token budget."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        view, config = status_mod.read_status(explicit=opts.root)
        ui.configure(
            no_color=opts.no_color,
            quiet=opts.quiet,
            color_policy=config.color,
            ascii_policy=config.ascii,
        )
        if json_out:
            ui.write_json(view.to_json())
        else:
            ui.render_status(view)

    _run(work)


@app.command()
def decide(
    ctx: typer.Context,
    text: Annotated[str, typer.Argument(help="The decision, optionally with -- reason.")],
    why: Annotated[str | None, typer.Option("--why", help="Why this decision.")] = None,
    files: Annotated[str | None, typer.Option("--files", help="Comma-separated repo paths.")] = None,
    agent: Annotated[str | None, typer.Option("--agent", help="Name to store on the proposal.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Propose even if a duplicate.")] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Propose a decision."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.propose import propose

        result = propose("D", text, why=why, files=files, agent=agent, force=force, explicit=opts.root)
        ui.render_propose(result)

    _run(work)


@app.command()
def reject(
    ctx: typer.Context,
    text: Annotated[str, typer.Argument(help="The idea that was ruled out.")],
    why: Annotated[str | None, typer.Option("--why", help="Why it was ruled out (required).")] = None,
    files: Annotated[str | None, typer.Option("--files", help="Comma-separated repo paths.")] = None,
    agent: Annotated[str | None, typer.Option("--agent", help="Name to store on the proposal.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Propose even if a duplicate.")] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Propose a rejected idea."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.propose import propose

        result = propose("X", text, why=why, files=files, agent=agent, force=force, explicit=opts.root)
        ui.render_propose(result)

    _run(work)


@app.command()
def rule(
    ctx: typer.Context,
    text: Annotated[str, typer.Argument(help="The rule to follow.")],
    why: Annotated[str | None, typer.Option("--why", help="Why, or the scope.")] = None,
    files: Annotated[str | None, typer.Option("--files", help="Comma-separated repo paths.")] = None,
    agent: Annotated[str | None, typer.Option("--agent", help="Name to store on the proposal.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Propose even if a duplicate.")] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Propose a rule."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.propose import propose

        result = propose("R", text, why=why, files=files, agent=agent, force=force, explicit=opts.root)
        ui.render_propose(result)

    _run(work)


@app.command()
def gotcha(
    ctx: typer.Context,
    text: Annotated[str, typer.Argument(help="The surprise or symptom.")],
    why: Annotated[str | None, typer.Option("--why", help="The fix or workaround.")] = None,
    files: Annotated[str | None, typer.Option("--files", help="Comma-separated repo paths.")] = None,
    agent: Annotated[str | None, typer.Option("--agent", help="Name to store on the proposal.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Propose even if a duplicate.")] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Propose a gotcha."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.propose import propose

        result = propose("G", text, why=why, files=files, agent=agent, force=force, explicit=opts.root)
        ui.render_propose(result)

    _run(work)


@app.command()
def ask(
    ctx: typer.Context,
    text: Annotated[str, typer.Argument(help="The open question.")],
    why: Annotated[str | None, typer.Option("--why", help="Current state or leaning.")] = None,
    files: Annotated[str | None, typer.Option("--files", help="Comma-separated repo paths.")] = None,
    agent: Annotated[str | None, typer.Option("--agent", help="Name to store on the proposal.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Propose even if a duplicate.")] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Propose an open question."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.propose import propose

        result = propose("Q", text, why=why, files=files, agent=agent, force=force, explicit=opts.root)
        ui.render_propose(result)

    _run(work)


@app.command()
def now(
    ctx: typer.Context,
    doing: Annotated[str | None, typer.Option("--doing", help="What is in progress.")] = None,
    done: Annotated[str | None, typer.Option("--done", help="Replace the done line.")] = None,
    next_items: Annotated[str | None, typer.Option("--next", help="What comes next.")] = None,
    blocked: Annotated[str | None, typer.Option("--blocked", help="What is blocking work.")] = None,
    add_done: Annotated[str | None, typer.Option("--add-done", help="Prepend an item to done.")] = None,
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Update the NOW block."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.now import apply_now

        result = apply_now(
            doing=doing,
            done=done,
            next_items=next_items,
            blocked=blocked,
            add_done=add_done,
            explicit=opts.root,
        )
        ui.render_now(result, json_out=json_out)

    _run(work)


@app.command()
def propose(
    ctx: typer.Context,
    kind: Annotated[str, typer.Argument(help="D, X, R, G, Q or a long name.")],
    text: Annotated[str, typer.Argument(help="Entry text, optionally with -- reason.")],
    why: Annotated[str | None, typer.Option("--why", help="Reason.")] = None,
    files: Annotated[str | None, typer.Option("--files", help="Comma-separated repo paths.")] = None,
    source: Annotated[str | None, typer.Option("--source", help="cli, paste, mcp or import.")] = None,
    agent: Annotated[str | None, typer.Option("--agent", help="Name to store on the proposal.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Propose even if a duplicate.")] = False,
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Propose an entry of any kind."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.propose import propose

        result = propose(
            kind,
            text,
            why=why,
            files=files,
            source=source or "cli",
            agent=agent,
            force=force,
            explicit=opts.root,
        )
        if json_out:
            ui.write_json(result.to_json())
        else:
            ui.render_propose(result)

    _run(work)


@app.command("list")
def list_cmd(
    ctx: typer.Context,
    status_filter: Annotated[
        str | None,
        typer.Option("--status", help="proposed, accepted, rejected, dismissed or all."),
    ] = None,
    kind: Annotated[str | None, typer.Option("--kind", help="Filter by D, X, R, G or Q.")] = None,
    limit: Annotated[int | None, typer.Option("--limit", help="Maximum rows.")] = None,
    archived: Annotated[bool, typer.Option("--archived", help="Read the inbox archive.")] = False,
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """List inbox proposals."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.inbox import list_proposals
        from costanza.paths import ProjectPaths, discover_root
        from costanza.propose import parse_kind

        paths = ProjectPaths(discover_root(explicit=opts.root, allow_cwd=False))
        path = paths.inbox_archive if archived else paths.inbox
        kind_filter = parse_kind(kind) if kind else None
        status = status_filter or "proposed"
        rows = list_proposals(path, status=status, kind=kind_filter, limit=limit)
        if json_out:
            ui.write_json([item.to_json() for item in rows])
        else:
            ui.render_list(list(rows))

    _run(work)


@app.command()
def review(
    ctx: typer.Context,
    kind: Annotated[str | None, typer.Option("--kind", help="Filter by D, X, R, G or Q.")] = None,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Review proposed entries interactively."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.accept import ReviewHooks, review_loop

        hooks = ReviewHooks(
            is_tty=ui.is_tty,
            read_key=ui.read_key,
            read_line=ui.read_line,
            confirm=ui.ask_yes_no,
            show=ui.render_review_card,
            ok=ui.ok,
            info=ui.info,
            warn=ui.warn,
            err=ui.err,
        )
        counts = review_loop(kind=kind, hooks=hooks, explicit=opts.root)
        ui.render_review_done(counts)

    _run(work)


@app.command()
def accept(
    ctx: typer.Context,
    pids: Annotated[list[str] | None, typer.Argument(help="Proposal IDs such as p7.")] = None,
    all_open: Annotated[bool, typer.Option("--all", help="Accept every proposed line.")] = False,
    text: Annotated[str | None, typer.Option("--text", help="Replace text before accepting.")] = None,
    why: Annotated[str | None, typer.Option("--why", help="Replace the reason.")] = None,
    files: Annotated[str | None, typer.Option("--files", help="Replace file references.")] = None,
    suggested: Annotated[
        bool,
        typer.Option("--suggested", help="Accept proposals a commit trailer suggested."),
    ] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Accept proposals into COSTANZA.md."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.accept import accept_proposals

        result = accept_proposals(
            pids,
            all_open=all_open,
            text=text,
            why=why,
            files=files,
            suggested_only=suggested,
            explicit=opts.root,
        )
        ui.render_accept(result)

    _run(work)


@app.command()
def dismiss(
    ctx: typer.Context,
    pids: Annotated[list[str] | None, typer.Argument(help="Proposal IDs such as p8.")] = None,
    reject_status: Annotated[bool, typer.Option("--reject", help="Set status to rejected.")] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Dismiss or reject a proposal."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.accept import dismiss_proposals

        messages = dismiss_proposals(pids, reject=reject_status, explicit=opts.root)
        for message in messages:
            if "already" in message:
                ui.info(message)
            else:
                ui.ok(message)

    _run(work)


@app.command()
def resolve(
    ctx: typer.Context,
    entry_id: Annotated[str, typer.Argument(help="A Q or G entry ID.")],
    note: Annotated[str | None, typer.Option("--note", help="Note stored on the archive heading.")] = None,
    decide_text: Annotated[
        str | None, typer.Option("--decide", help="Propose a decision that resolves this ID.")
    ] = None,
    why: Annotated[str | None, typer.Option("--why", help="Reason for --decide.")] = None,
    files: Annotated[str | None, typer.Option("--files", help="File references for --decide.")] = None,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Archive a resolved question or gotcha."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.accept import resolve_entry
        from costanza.propose import ProposeResult
        from costanza.store import WriteResult

        result = resolve_entry(
            entry_id,
            note=note,
            decide_text=decide_text,
            why=why,
            files=files,
            explicit=opts.root,
        )
        if isinstance(result, ProposeResult):
            if result.result == "nothing":
                ui.info("nothing resolved")
            else:
                ui.render_propose(result)
                if result.proposal is not None:
                    ui.next_hint("cz review")
        elif isinstance(result, WriteResult):
            extra = "; merged with your edits" if result.merged else ""
            ui.ok(f"{result.change} → .costanza/archive/{extra}".rstrip())
            ui.info(f"COSTANZA.md: {result.change}{extra}")

    _run(work)


@app.command()
def paste(
    ctx: typer.Context,
    file: Annotated[Path | None, typer.Option("--file", help="Read this file instead of stdin.")] = None,
    clipboard: Annotated[bool, typer.Option("--clipboard", help="Read the system clipboard.")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Parse without writing.")] = False,
    partial: Annotated[bool, typer.Option("--partial", help="Apply good lines if some are malformed.")] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Apply a costanza paste block."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.paste import apply_paste

        text = _read_paste_input(file, clipboard)
        result = apply_paste(
            text,
            dry_run=dry_run,
            partial=partial,
            explicit=opts.root,
        )
        ui.render_paste(result, dry_run=dry_run)
        if result.issues:
            raise typer.Exit(2)

    _run(work)


@app.command()
def handoff(
    ctx: typer.Context,
    out: Annotated[Path | None, typer.Option("--out", help="Write the packet to this path.")] = None,
    copy: Annotated[bool, typer.Option("--copy", help="Copy to the clipboard.")] = False,
    with_inbox: Annotated[bool, typer.Option("--with-inbox", help="Include proposed inbox lines.")] = False,
    no_prompt: Annotated[bool, typer.Option("--no-prompt", help="Omit the paste-block instructions.")] = False,
    budget: Annotated[int | None, typer.Option("--budget", help="Token ceiling for the compiled pack.")] = None,
    for_kind: Annotated[
        str | None,
        typer.Option("--for", help="chat: prepend a preamble for a fresh chat with no tools."),
    ] = None,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Print a handoff packet for a new chat."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.clipboard import copy as copy_clip
        from costanza.constants import CLIPBOARD_HINT
        from costanza.exceptions import ClipboardError, ClipboardUnavailable, UsageError
        from costanza.handoff import build_handoff
        from costanza.io import write_text

        for_chat = False
        if for_kind is not None:
            if for_kind.strip().lower() != "chat":
                raise UsageError('--for must be "chat"', "cz handoff --for chat")
            for_chat = True
        packet = build_handoff(
            budget=budget,
            for_chat=for_chat,
            with_inbox=with_inbox,
            no_prompt=no_prompt,
            explicit=opts.root,
        )
        if out is not None:
            write_text(out, packet.text)
        if copy:
            try:
                copied = copy_clip(packet.text)
            except (ClipboardUnavailable, ClipboardError) as exc:
                ui.write_raw(packet.text)
                ui.err(exc.message)
                ui.write_line(f"next: {CLIPBOARD_HINT}", err=True)
                raise typer.Exit(1) from None
            ui.render_handoff(packet, copied=copied)
            return
        if out is None:
            ui.write_raw(packet.text)
        ui.render_handoff(packet, copied=None)

    _run(work)


@app.command()
def prompt(
    ctx: typer.Context,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Print the one-sentence bootstrap for tools that can read COSTANZA.md."""
    _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.handoff import prompt_text

        ui.write_raw(prompt_text())

    _run(work)


@app.command()
def scan(
    ctx: typer.Context,
    write: Annotated[bool, typer.Option("--write", help="Fill ? header keys.")] = False,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Replace detected keys that already have a value.")
    ] = False,
    force: Annotated[bool, typer.Option("--force", help="Same as --overwrite.")] = False,
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Detect header facts from the repo."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.scan import scan_project

        result, config = scan_project(
            write=write,
            overwrite=overwrite or force,
            explicit=opts.root,
        )
        ui.configure(
            no_color=opts.no_color,
            quiet=opts.quiet,
            color_policy=config.color,
            ascii_policy=config.ascii,
        )
        if json_out:
            ui.write_json(result.to_json())
        else:
            ui.render_scan(result)

    _run(work)


@app.command()
def check(
    ctx: typer.Context,
    strict: Annotated[bool, typer.Option("--strict", help="Treat warnings as errors.")] = False,
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    fix: Annotated[bool, typer.Option("--fix", help="Rewrite COSTANZA.md in canonical form.")] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Validate COSTANZA.md."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza import check as check_mod

        report, config = check_mod.run_check(explicit=opts.root, fix=fix)
        ui.configure(
            no_color=opts.no_color,
            quiet=opts.quiet,
            color_policy=config.color,
            ascii_policy=config.ascii,
        )
        if json_out:
            ui.write_json(report.to_json())
        else:
            ui.render_check(report)
        if report.errors or (strict and report.warnings):
            raise typer.Exit(3)

    _run(work)


@app.command()
def compact(
    ctx: typer.Context,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Print the plan without writing.")] = False,
    apply: Annotated[bool, typer.Option("--apply", help="Write the plan (default is dry-run).")] = False,
    target: Annotated[int | None, typer.Option("--target", help="Stop at this token count.")] = None,
    inbox: Annotated[bool, typer.Option("--inbox", help="Move old decided proposals instead.")] = False,
    purge: Annotated[bool, typer.Option("--purge", help="Erase old archived proposal text.")] = False,
    older_than: Annotated[int | None, typer.Option("--older-than", help="Age in days.")] = None,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Move overflow entries to the archive."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.compact import run_compact

        result, config = run_compact(
            apply=apply,
            dry_run=dry_run,
            target=target,
            inbox=inbox,
            purge=purge,
            older_than=older_than,
            explicit=opts.root,
        )
        ui.configure(
            no_color=opts.no_color,
            quiet=opts.quiet,
            color_policy=config.color,
            ascii_policy=config.ascii,
        )
        ui.render_compact(result)
        if result.applied and result.still_over and result.tokens_after > config.budget_tokens:
            raise typer.Exit(3)

    _run(work)


@app.command()
def sync(
    ctx: typer.Context,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would change.")] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Update the synced commit pointer."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.git import git_gap
        from costanza.paths import discover_root
        from costanza.sync import sync_file

        root = discover_root(explicit=opts.root, allow_cwd=False)
        gap = git_gap(root)
        if gap:
            ui.write_line(gap, err=True)
            raise typer.Exit(2)
        result, config = sync_file(apply=not dry_run, explicit=opts.root)
        ui.configure(
            no_color=opts.no_color,
            quiet=opts.quiet,
            color_policy=config.color,
            ascii_policy=config.ascii,
        )
        ui.render_sync(result)

    _run(work)


@app.command()
def mcp(
    ctx: typer.Context,
    print_config: Annotated[
        str | None,
        typer.Option(
            "--print-config",
            help="Print the MCP config for one client and exit.",
            metavar="CLIENT",
        ),
    ] = None,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Run the MCP server on stdio."""
    opts = _prepare(ctx, root, quiet, no_color)
    if print_config is not None:

        def show() -> None:
            from costanza.mcp_server import render_print_config

            ui.write_line(render_print_config(print_config))

        _run(show)
        return

    import importlib.util

    if importlib.util.find_spec("mcp") is None:
        ui.err("MCP support is not installed")
        ui.next_hint('pip install "costanza[mcp]"')
        raise typer.Exit(1)

    def work() -> None:
        from costanza.mcp_server import serve

        serve(opts.root)

    _run(work)


@app.command("import")
def import_cmd(
    ctx: typer.Context,
    source: Annotated[
        str,
        typer.Argument(help="plain, aider or claude-code. Each adapter is best-effort."),
    ],
    path: Annotated[Path, typer.Argument(help="Session file to read.")],
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Write low-confidence proposals. Otherwise preview only."),
    ] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Import session notes as proposals. Best-effort; nothing is accepted."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.importers import import_transcript

        result = import_transcript(source, path, yes=yes, explicit=opts.root)
        ui.render_import(result)

    _run(work)


@app.command()
def doctor(
    ctx: typer.Context,
    fix: Annotated[bool, typer.Option("--fix", help="Apply the safe repairs.")] = False,
    json_out: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Check the Costanza installation."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.doctor import run_doctor

        report = run_doctor(explicit=opts.root, fix=fix, encoding=ui.stdout_encoding())
        ui.configure(
            no_color=opts.no_color,
            quiet=opts.quiet,
            color_policy=report.color_policy,
            ascii_policy=report.ascii_policy,
        )
        if json_out:
            ui.write_json(report.to_json())
        else:
            ui.render_doctor(report)
        if report.failed:
            raise typer.Exit(3)

    _run(work)


@agents_app.callback(invoke_without_command=True)
def agents_root(
    ctx: typer.Context,
    remove: Annotated[bool, typer.Option("--remove", help="Remove the Costanza block.")] = False,
    mode: Annotated[str, typer.Option("--mode", help="auto, all, or none.")] = "auto",
    target: Annotated[list[Path] | None, typer.Option("--target", help="Agent file to manage.")] = None,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Install or remove agent instruction blocks."""
    opts = _prepare(ctx, root, quiet, no_color)
    if ctx.invoked_subcommand is not None:
        return

    def work() -> None:
        _run_agents("remove" if remove else "install", mode=mode, target=target, root=opts.root)

    _run(work)


@agents_app.command("install")
def agents_install(
    ctx: typer.Context,
    mode: Annotated[str, typer.Option("--mode", help="auto, all, or none.")] = "auto",
    target: Annotated[list[Path] | None, typer.Option("--target", help="Agent file to manage.")] = None,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Write the Costanza block into agent files."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        _run_agents("install", mode=mode, target=target, root=opts.root)

    _run(work)


@agents_app.command("remove")
def agents_remove(
    ctx: typer.Context,
    mode: Annotated[str, typer.Option("--mode", help="auto, all, or none.")] = "auto",
    target: Annotated[list[Path] | None, typer.Option("--target", help="Agent file to manage.")] = None,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Remove the Costanza block from agent files."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        _run_agents("remove", mode=mode, target=target, root=opts.root)

    _run(work)


@agents_app.command("status")
def agents_status(
    ctx: typer.Context,
    mode: Annotated[str, typer.Option("--mode", help="auto, all, or none.")] = "auto",
    target: Annotated[list[Path] | None, typer.Option("--target", help="Agent file to manage.")] = None,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Show which agent files have the Costanza block."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        _run_agents("status", mode=mode, target=target, root=opts.root)

    _run(work)


def _emit_hook(report: object) -> None:
    from costanza.hooks import HookReport

    if not isinstance(report, HookReport):
        return
    if report.warning:
        ui.warn(report.warning)
    if report.exit_code:
        ui.err(report.message)
        if report.hint:
            ui.next_hint(report.hint)
        raise typer.Exit(report.exit_code)
    if report.message != report.state and report.state in {"installed", "updated", "removed"}:
        ui.ok(report.message)
        return
    if report.message != report.state and report.state in {"unchanged", "missing"}:
        ui.info(report.message)
        return
    ui.write_line(report.message)


@hook_app.callback(invoke_without_command=True)
def hook_root(
    ctx: typer.Context,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Install or remove the git post-commit hook."""
    _prepare(ctx, root, quiet, no_color)
    if ctx.invoked_subcommand is None:
        ui.write_line("usage: cz hook install|remove|status", err=True)
        raise typer.Exit(2)


@hook_app.command("install")
def hook_install(
    ctx: typer.Context,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Write the post-commit hook."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.git import git_gap
        from costanza.hooks import install_hook
        from costanza.paths import discover_root

        found = discover_root(explicit=opts.root, allow_cwd=False)
        gap = git_gap(found)
        if gap:
            ui.write_line(gap, err=True)
            raise typer.Exit(2)
        _emit_hook(install_hook(found))

    _run(work)


@hook_app.command("remove")
def hook_remove(
    ctx: typer.Context,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Delete Costanza's post-commit hook."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.hooks import remove_hook
        from costanza.paths import discover_root

        _emit_hook(remove_hook(discover_root(explicit=opts.root)))

    _run(work)


@hook_app.command("uninstall")
def hook_uninstall(
    ctx: typer.Context,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Delete Costanza's post-commit hook."""
    hook_remove(ctx, root, quiet, no_color)


@hook_app.command("status")
def hook_status_cmd(
    ctx: typer.Context,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Show whether the hook is installed."""
    opts = _prepare(ctx, root, quiet, no_color)

    def work() -> None:
        from costanza.hooks import hook_status
        from costanza.paths import discover_root

        report = hook_status(discover_root(explicit=opts.root))
        _emit_hook(report)
        ui.write_line("log")
        ui.write_line(report.log or "none")

    _run(work)


@hook_app.command("run", hidden=True)
def hook_run(
    ctx: typer.Context,
    event: Annotated[str, typer.Argument(help="Hook event name.")],
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Called by the installed hook script. Always exits 0."""
    opts = _prepare(ctx, root, quiet, no_color)
    from costanza.hooks import append_hook_log, run_post_commit
    from costanza.paths import ProjectPaths, discover_root

    try:
        message = run_post_commit(event, explicit=opts.root)
    except typer.Exit:
        raise
    except Exception as exc:
        reason = exc.message if isinstance(exc, CostanzaError) else f"{type(exc).__name__}: {exc}"
        found: Path | None
        try:
            found = discover_root(explicit=opts.root)
        except Exception:
            found = None
        if found is not None:
            append_hook_log(ProjectPaths(found).hook_log, reason)
        ui.write_line(f"costanza: hook skipped: {reason}", err=True)
        raise typer.Exit(0) from None
    if message:
        ui.write_line(message, err=True)
    raise typer.Exit(0)


app.add_typer(agents_app, name="agents")
app.add_typer(hook_app, name="hook")


def _read_paste_input(file: Path | None, clipboard: bool) -> str:
    from costanza.constants import PASTE_MAX_BYTES
    from costanza.exceptions import UsageError

    if file is not None and clipboard:
        raise UsageError("use --file or --clipboard, not both", "cz paste --help")
    if file is not None:
        try:
            data = file.read_bytes()
        except OSError as exc:
            raise UsageError(f"cannot read {file}", "pass a readable file") from exc
        if len(data) > PASTE_MAX_BYTES:
            raise UsageError(
                f"paste is larger than {PASTE_MAX_BYTES} bytes",
                "trim the reply and paste again",
            )
        return data.decode("utf-8")
    if clipboard:
        from costanza.clipboard import read as read_clip

        text = read_clip()
        if len(text.encode("utf-8")) > PASTE_MAX_BYTES:
            raise UsageError(
                f"paste is larger than {PASTE_MAX_BYTES} bytes",
                "trim the reply and paste again",
            )
        return text
    if sys.stdin.isatty():
        ui.write_line("paste the reply, then Ctrl-D (Ctrl-Z Enter on Windows)", err=True)
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        raw = buffer.read(PASTE_MAX_BYTES + 1)
        data = bytes(raw) if isinstance(raw, (bytes, bytearray)) else str(raw).encode("utf-8")
        if len(data) > PASTE_MAX_BYTES:
            raise UsageError(
                f"paste is larger than {PASTE_MAX_BYTES} bytes",
                "trim the reply and paste again",
            )
        return data.decode("utf-8")
    text = sys.stdin.read()
    if len(text.encode("utf-8")) > PASTE_MAX_BYTES:
        raise UsageError(
            f"paste is larger than {PASTE_MAX_BYTES} bytes",
            "trim the reply and paste again",
        )
    return text


def _run_agents(
    action: str,
    *,
    mode: str,
    target: list[Path] | None,
    root: Path | None,
) -> None:
    from costanza.agents import install_agents, remove_agents, status_agents
    from costanza.exceptions import UsageError

    cleaned = mode.strip().lower()
    if cleaned not in {"auto", "all", "none"}:
        raise UsageError("mode must be auto, all or none", "cz agents --mode auto")
    if action == "install":
        result = install_agents(mode=cleaned, targets=target, explicit=root)
    elif action == "remove":
        result = remove_agents(mode=cleaned, targets=target, explicit=root)
    else:
        result = status_agents(mode=cleaned, targets=target, explicit=root)
    ui.render_agents(result)
    if result.failed:
        raise typer.Exit(1)


@app.command()
def welcome(
    ctx: typer.Context,
    root: RootOpt = None,
    quiet: QuietOpt = None,
    no_color: NoColorOpt = None,
) -> None:
    """Print the welcome screen."""
    _prepare(ctx, root, quiet, no_color)
    _show_welcome()


def _show_welcome() -> None:
    def work() -> None:
        ui.render_welcome(__version__)

    _run(work)


def main() -> None:
    app()
