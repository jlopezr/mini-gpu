"""La cara del depurador: cuatro paneles sobre una `DebugSession`.

    +-------------------------+------------------+
    | codigo (PC centrado)    | registros        |
    +-------------------------+------------------+
    | memoria                                    |
    +--------------------------------------------+
    | consola + linea de comando                 |
    +--------------------------------------------+

Todo lo que se puede hacer con una tecla se puede hacer también escribiendo el
comando, y la tecla no hace otra cosa: llama a `session.execute(...)` igual que
la línea. No hay ni un camino de ejecución que solo exista aquí, que es lo que
mantiene honestos los tests de `debug_core`.

Textual se importa dentro de `run_tui` a propósito: el modo línea y los tests
tienen que funcionar en una máquina sin `textual` instalado.
"""
from __future__ import annotations

from tools.debug_core import (
    CommandError, DebugSession, format_memory_row,
)
from tools.debug_target import TargetError

CSS = """
Screen { layout: vertical; }
#top { height: 1fr; }
#code { width: 2fr; border: round $accent; padding: 0 1; }
#registers { width: 42; border: round $accent; padding: 0 1; }
#memory { height: 10; border: round $accent; padding: 0 1; }
#console { height: 8; border: round $accent; padding: 0 1; }
#prompt { dock: bottom; }
"""


def _code_lines(session: DebugSession) -> str:
    rows = []
    for row in session.listing():
        for label in row.labels:
            rows.append(f"[dim]{label}:[/dim]")
        mark = "[red]*[/red]" if row.has_breakpoint else " "
        word = f"{row.word:08X}" if row.word is not None else "????????"
        line = f"{mark} 0x{row.address:08X}  {word}  {_escape(row.text)}"
        rows.append(f"[reverse]{line}[/reverse]" if row.is_pc else line)
    return "\n".join(rows)


def _register_lines(session: DebugSession) -> str:
    rows = []
    for name, value in session.register_rows():
        signed = value - (1 << 32) if value & 0x80000000 else value
        style = "dim" if value == 0 else "bold"
        rows.append(f"[{style}]{name:<3} 0x{value:08X} {signed:>12}[/{style}]")
    return "\n".join(rows)


def _memory_lines(session: DebugSession) -> str:
    rows = session.memory_rows()
    if not rows:
        return f"[red]region ilegible: 0x{session.memory_address:08X}[/red]"
    return "\n".join(_escape(format_memory_row(address, data))
                     for address, data in rows)


def _escape(text: str) -> str:
    """Un `[` del fuente no es markup de Rich."""
    return text.replace("[", "\\[")


def build_app(session: DebugSession):
    """La app montada pero sin arrancar.

    Separado de `run_tui` para que se pueda pilotar con `App.run_test()` sin
    abrir un terminal: es la única forma de que la interfaz entre en la suite.
    """
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal
    from textual.widgets import Footer, Input, RichLog, Static

    class DebuggerApp(App):
        CSS = globals()["CSS"]
        TITLE = "minidbg"
        BINDINGS = [
            ("s", "command('step')", "paso"),
            ("n", "command('over')", "saltar llamada"),
            ("c", "command('run')", "continuar"),
            ("b", "command('break pc')", "break aqui"),
            ("v", "command('fb')", "ver framebuffer"),
            ("R", "command('reset')", "reset"),
            ("q", "quit", "salir"),
        ]

        def compose(self) -> ComposeResult:
            with Horizontal(id="top"):
                yield Static(id="code")
                yield Static(id="registers")
            yield Static(id="memory")
            yield RichLog(id="console", markup=True, wrap=True)
            yield Input(placeholder="comando (`help` para la lista)",
                        id="prompt")
            yield Footer()

        def on_mount(self) -> None:
            self.query_one("#code", Static).border_title = "codigo"
            self.query_one("#registers", Static).border_title = "registros"
            self.query_one("#memory", Static).border_title = "memoria"
            self.query_one("#console", RichLog).border_title = "consola"
            self.query_one("#console", RichLog).write(
                "[dim]`help` lista los comandos. Las teclas de abajo hacen "
                "lo mismo que escribirlos.[/dim]")
            self.refresh_panels()

        def refresh_panels(self) -> None:
            self.query_one("#code", Static).update(_code_lines(session))
            self.query_one("#registers", Static).update(
                _register_lines(session))
            self.query_one("#memory", Static).update(_memory_lines(session))
            self.sub_title = session.status_line()

        def dispatch(self, command: str) -> None:
            log = self.query_one("#console", RichLog)
            log.write(f"[bold cyan]> {command}[/bold cyan]")
            try:
                for line in session.execute(command):
                    log.write(_escape(line))
            except (CommandError, TargetError) as exc:
                log.write(f"[red]{exc}[/red]")
            self.refresh_panels()
            if session.quit:
                self.exit()

        def action_command(self, command: str) -> None:
            # Con el foco en la caja de texto, las teclas son texto: quien
            # escribe un comando no quiere que la `s` dispare un paso.
            if self.focused is self.query_one("#prompt", Input):
                return
            self.dispatch(command)

        def on_input_submitted(self, event: Input.Submitted) -> None:
            event.input.value = ""
            if event.value.strip():
                self.dispatch(event.value.strip())

    return DebuggerApp()


def run_tui(session: DebugSession) -> int:
    build_app(session).run()
    return 0


def run_line_mode(session: DebugSession) -> int:
    """El mismo depurador sin terminal gráfico, para tuberías y sesiones ssh."""
    print(session.status_line())
    while not session.quit:
        try:
            line = input("(minidbg) ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        try:
            for text in session.execute(line):
                print(text)
        except (CommandError, TargetError) as exc:
            print(f"error: {exc}")
        else:
            if not session.quit:
                print(session.status_line())
    return 0
