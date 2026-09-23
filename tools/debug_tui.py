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
from tools.mmio_map import MMIO_SYSTEM_BASE

CSS = """
Screen { layout: vertical; }
#top { height: 1fr; }
#code { width: 2fr; height: 100%; border: round $accent; padding: 0 1; }
#registers {
    width: 42; height: 100%; border: round $accent; padding: 0 1;
    overflow-y: auto;
    scrollbar-size: 1 1;
}
#register-values { height: auto; }
#memory { height: 10; border: round $accent; padding: 0 1; }
#console-area { height: 9; border: round $accent; }
#code:focus, #registers:focus, #memory:focus, #console-area:focus-within {
    border: double $warning;
}
#console { height: 1fr; padding: 0 1; }
#prompt { dock: bottom; }
"""

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _code_view(
        session: DebugSession, height: int | None = None,
        center: int | None = None,
) -> tuple[str, list[tuple[str, int, int, int] | None], set[int]]:
    if height is not None and height <= 0:
        # Durante on_mount Textual todavía puede no haber calculado el layout.
        height = None
    # Se pide una pantalla completa a cada lado. Después de expandir las
    # etiquetas se recorta alrededor del PC; pedir solo media pantalla hacia
    # atrás dejaría hueco al llegar al final del programa.
    radius = max(1, height) if height is not None else None
    # (markup, anchura visible, anotación, tipo/destino, es_pc, dirección)
    rows: list[tuple[
        str, int, str | None, tuple[str, int] | None, bool, int | None
    ]] = []
    focus_row = 0
    registers = session.target.registers()
    pc = session.target.state().pc
    listing = (session.listing(before=radius, after=radius, center=center)
               if radius is not None else session.listing())
    for row in listing:
        for label in row.labels:
            text = f"{label}:"
            rows.append((f"[dim]{text}[/dim]", len(text), None, None,
                         False, None))
        cursor_text = ">" if center is not None and row.address == center else " "
        cursor = "[bold yellow]>[/bold yellow]" if cursor_text == ">" else " "
        mark_text = "*" if row.has_breakpoint else " "
        mark = "[red]*[/red]" if row.has_breakpoint else " "
        word = f"{row.word:08X}" if row.word is not None else "????????"
        line = (f"{cursor}{mark} 0x{row.address:08X}  {word}  "
                f"{_escape(row.text)}")
        visible = (f"{cursor_text}{mark_text} 0x{row.address:08X}  {word}  "
                   f"{row.text}")
        if row.address == (pc if center is None else center):
            focus_row = len(rows)
        annotation = session.source.target_annotation(row.address, registers)
        rows.append((
            line, len(visible),
            annotation[0] if annotation else None,
            (annotation[1], annotation[2]) if annotation else None,
            row.is_pc, row.address,
        ))
    if height is not None and height > 0 and len(rows) > height:
        start = max(0, focus_row - height // 2)
        start = min(start, len(rows) - height)
        rows = rows[start:start + height]
    annotated_widths = [
        width for _, width, note, _, _, _ in rows if note]
    comment_column = max([64, *annotated_widths]) + 2
    rendered = []
    targets: list[tuple[str, int, int, int] | None] = []
    visible_addresses: set[int] = set()
    for line, width, note, destination, is_pc, address in rows:
        target = None
        if note:
            line += " " * max(2, comment_column - width)
            kind, destination_address = destination
            if kind == "code":
                style = "dim cyan"
            elif destination_address >= MMIO_SYSTEM_BASE:
                style = "dim yellow"
            else:
                style = "dim magenta"
            line += f"[{style}]{_escape(note)}[/{style}]"
            bracket = note.index("[")
            note_column = max(comment_column, width + 2)
            # En saltos, toda la instrucción (incluida la etiqueta fuente) y
            # su comentario actúan como enlace. En memoria solo lo hace la
            # dirección efectiva: pulsar el mnemonic no debe mover el dump.
            start = 0 if kind == "code" else note_column + bracket
            target = (kind, destination_address, start,
                      note_column + len(note))
        rendered.append(f"[reverse]{line}[/reverse]" if is_pc else line)
        targets.append(target)
        if address is not None:
            visible_addresses.add(address)
    return "\n".join(rendered), targets, visible_addresses


def _code_lines(session: DebugSession, height: int | None = None) -> str:
    return _code_view(session, height)[0]


def _register_lines(session: DebugSession,
                    changed: set[int] | None = None) -> str:
    changed = changed or set()
    rows = []
    for index, (name, value) in enumerate(session.register_rows()):
        signed = value - (1 << 32) if value & 0x80000000 else value
        if index in changed:
            style = "bold yellow"
        else:
            style = "dim" if value == 0 else "none"
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


def _console_markup(text: str) -> str:
    escaped = _escape(text)
    return f"[red]{escaped}[/red]" if text.startswith("ERROR ") else escaped


def _warning_markup(text: str) -> str:
    return f"[bold yellow]AVISO: {_escape(text)}[/bold yellow]"


def build_app(session: DebugSession):
    """La app montada pero sin arrancar.

    Separado de `run_tui` para que se pueda pilotar con `App.run_test()` sin
    abrir un terminal: es la única forma de que la interfaz entre en la suite.
    """
    from textual import events
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.widgets import Footer, Input, RichLog, Static

    has_video = session.target.video_layout() is not None
    can_advance_frame = session.target.video_swap_count() is not None

    class CodePanel(Static):
        can_focus = True
        BINDINGS = [
            ("/", "search", "buscar"),
            ("a", "repeat_search", "buscar siguiente"),
            ("up", "cursor_up", "subir"),
            ("down", "cursor_down", "bajar"),
            ("pageup", "page_up", "pag. arriba"),
            ("pagedown", "page_down", "pag. abajo"),
            ("home", "home", "inicio"),
            ("p", "center_pc", "centrar PC"),
            ("b", "toggle_breakpoint", "alternar break"),
            ("u", "until_cursor", "ejecutar hasta aqui"),
        ]

        def action_cursor_up(self) -> None:
            self.app.action_move_view(-1)

        def action_cursor_down(self) -> None:
            self.app.action_move_view(1)

        def action_page_up(self) -> None:
            self.app.action_page_view(-1)

        def action_page_down(self) -> None:
            self.app.action_page_view(1)

        def action_home(self) -> None:
            self.app.action_view_home()

        def action_center_pc(self) -> None:
            self.app.action_center_pc()

        def action_toggle_breakpoint(self) -> None:
            self.app.action_toggle_breakpoint()

        def action_search(self) -> None:
            self.app.action_start_search()

        def action_repeat_search(self) -> None:
            self.app.action_repeat_search()

        def action_until_cursor(self) -> None:
            self.app.action_until_cursor()

    class MemoryPanel(Static):
        can_focus = True
        BINDINGS = [
            ("/", "search", "buscar"),
            ("a", "repeat_search", "buscar siguiente"),
            ("up", "cursor_up", "subir"),
            ("down", "cursor_down", "bajar"),
            ("pageup", "page_up", "pag. arriba"),
            ("pagedown", "page_down", "pag. abajo"),
            ("home", "home", "memoria 0"),
            ("h", "home", "memoria 0"),
        ]

        def action_cursor_up(self) -> None:
            self.app.action_move_view(-1)

        def action_cursor_down(self) -> None:
            self.app.action_move_view(1)

        def action_page_up(self) -> None:
            self.app.action_page_view(-1)

        def action_page_down(self) -> None:
            self.app.action_page_view(1)

        def action_home(self) -> None:
            self.app.action_memory_home()

        def action_search(self) -> None:
            self.app.action_start_search()

        def action_repeat_search(self) -> None:
            self.app.action_repeat_search()

    class RegisterPanel(VerticalScroll):
        can_focus = True
        BINDINGS = [
            ("/", "search", "buscar"),
            ("a", "repeat_search", "buscar siguiente"),
            ("up", "cursor_up", "subir"),
            ("down", "cursor_down", "bajar"),
        ]

        def compose(self) -> ComposeResult:
            yield Static(id="register-values")

        def action_cursor_up(self) -> None:
            self.app.action_move_view(-1)

        def action_cursor_down(self) -> None:
            self.app.action_move_view(1)

        def action_search(self) -> None:
            self.app.action_start_search()

        def action_repeat_search(self) -> None:
            self.app.action_repeat_search()

    class DebuggerApp(App):
        CSS = globals()["CSS"]
        TITLE = "minidbg"
        BINDINGS = [
            ("s", "command('step')", "paso"),
            ("n", "command('over')", "saltar llamada"),
            ("o", "command('finish')", "salir funcion"),
            ("c", "command('run')", "continuar"),
            ("R", "command('reset')", "reset"),
            ("escape", "interrupt", ""),
            ("ctrl+c", "ctrl_c", ""),
            ("q", "quit", "salir"),
        ] + ([
            ("v", "command('fb')", "ver framebuffer"),
        ] if has_video else []) + ([
            ("f", "command('frame')", "siguiente frame"),
        ] if can_advance_frame else [])

        def __init__(self) -> None:
            super().__init__()
            self.changed_registers: set[int] = set()
            self.code_center: int | None = None
            self.code_row_targets: list[
                tuple[str, int, int, int] | None] = []
            self.code_row_addresses: set[int] = set()
            self.running = False
            self.search_context: str | None = None
            self.search_focus = None
            self.last_search: tuple[str, str] | None = None
            self.last_memory_match: int | None = None
            self.spinner_index = 0
            self.spinner_timer = None

        def compose(self) -> ComposeResult:
            with Horizontal(id="top"):
                yield CodePanel(id="code")
                yield RegisterPanel(id="registers")
            yield MemoryPanel(id="memory")
            with Vertical(id="console-area"):
                yield RichLog(id="console", markup=True, wrap=True)
                yield Input(placeholder="comando (`help` para la lista)",
                            id="prompt")
            yield Footer()

        def on_mount(self) -> None:
            self.query_one("#code", Static).border_title = "codigo"
            self.query_one("#registers", RegisterPanel).border_title = "registros"
            self.query_one("#memory", Static).border_title = "memoria"
            self.query_one("#console-area", Vertical).border_title = "consola"
            self.query_one("#console", RichLog).write(
                "[dim]`help` lista los comandos. Las teclas de abajo hacen "
                "lo mismo que escribirlos.[/dim]")
            for warning in session.warnings:
                self.query_one("#console", RichLog).write(
                    _warning_markup(warning))
            if has_video:
                session.video.on_key = lambda key: self.call_from_thread(
                    self.action_video_key, key)
                session.video.on_error = lambda message: self.call_from_thread(
                    self.action_video_error, message)
            self.refresh_panels()
            # El primer refresco puede ocurrir antes de que el motor de layout
            # conozca la altura interior de código. Repetirlo tras pintar el
            # primer frame llena el viewport sin esperar al primer comando.
            self.call_after_refresh(self.refresh_panels)

        def on_unmount(self) -> None:
            # Textual puede desmontarse por `q`, cierre del terminal o Ctrl+C.
            # Un `to_thread()` no se cancela con la coroutine que lo espera:
            # hay que despertar explícitamente el bucle de `run` para que
            # asyncio no se quede esperando su executor durante el cierre.
            if self.running:
                session.interrupt()

        def refresh_panels(self) -> None:
            code = self.query_one("#code", Static)
            rendered, self.code_row_targets, self.code_row_addresses = _code_view(
                session, code.content_region.height, self.code_center)
            code.update(rendered)
            self.query_one("#register-values", Static).update(
                _register_lines(session, self.changed_registers))
            self.query_one("#memory", Static).update(_memory_lines(session))
            self.sub_title = session.status_line()

        def on_resize(self) -> None:
            # La cantidad de instrucciones visibles forma parte del viewport,
            # no del estado del depurador.
            self.refresh_panels()

        def dispatch(self, command: str) -> None:
            log = self.query_one("#console", RichLog)
            log.write(f"[bold cyan]> {command}[/bold cyan]")
            log.write("[dim]Esc para interrumpir la ejecución[/dim]")
            before = session.target.registers()
            try:
                for line in session.execute(command):
                    log.write(_console_markup(line))
            except (CommandError, TargetError) as exc:
                log.write(f"[red]{exc}[/red]")
            self._finish_dispatch(command, before)

        def _finish_dispatch(self, command: str,
                             before: list[int]) -> None:
            after = session.target.registers()
            self.changed_registers = {
                index for index, (old, new) in enumerate(zip(before, after))
                if old != new
            }
            if command.split(None, 1)[0].lower() in {
                    "s", "step", "n", "next", "over", "c", "continue",
                    "run", "until", "f", "frame", "finish", "reset"}:
                # Después de ejecutar, el cursor conceptual vuelve al PC aunque
                # la selección anterior siguiera visible. Así el próximo
                # arriba/abajo siempre parte de la instrucción actual.
                self.code_center = None
            self.refresh_panels()
            if session.quit:
                self.exit()

        def action_command(self, command: str) -> None:
            # Con el foco en la caja de texto, las teclas son texto: quien
            # escribe un comando no quiere que la `s` dispare un paso.
            if self.focused is self.query_one("#prompt", Input):
                return
            if self.running:
                return
            name = command.split(None, 1)[0].lower()
            if name in {"c", "continue", "run", "until", "u",
                        "over", "n", "finish", "frame", "f"}:
                self.run_worker(self._dispatch_long(command), exclusive=True)
            else:
                self.dispatch(command)

        async def _dispatch_long(self, command: str) -> None:
            import asyncio

            log = self.query_one("#console", RichLog)
            log.write(f"[bold cyan]> {command}[/bold cyan]")
            before = session.target.registers()
            session.clear_interrupt()
            self.running = True
            self.spinner_index = 0
            self._spin()
            self.spinner_timer = self.set_interval(0.1, self._spin)
            try:
                try:
                    lines = await asyncio.to_thread(session.execute, command)
                except (CommandError, TargetError) as exc:
                    log.write(f"[red]{exc}[/red]")
                else:
                    for line in lines:
                        log.write(_console_markup(line))
                self._finish_dispatch(command, before)
            finally:
                self.running = False
                if self.spinner_timer is not None:
                    self.spinner_timer.pause()
                    self.spinner_timer = None
                for code in self.query(CodePanel):
                    code.border_title = "codigo"

        def _spin(self) -> None:
            glyph = _SPINNER[self.spinner_index % len(_SPINNER)]
            self.spinner_index += 1
            for code in self.query(CodePanel):
                code.border_title = f"codigo  {glyph} ejecutando"

        def action_toggle_breakpoint(self) -> None:
            if self.focused is self.query_one("#prompt", Input):
                return
            code = self.query_one("#code", CodePanel)
            address = (self.code_center
                       if self.focused is code and self.code_center is not None
                       else session.target.state().pc)
            command = ("delete" if address in session.breakpoints else "break")
            self.dispatch(f"{command} 0x{address:08X}")

        def action_until_cursor(self) -> None:
            if self.focused is self.query_one("#prompt", Input):
                return
            address = (session.target.state().pc if self.code_center is None
                       else self.code_center)
            self.action_command(f"until 0x{address:08X}")

        def action_move_view(self, amount: int) -> None:
            code = self.query_one("#code", CodePanel)
            if self.focused is code:
                current = (session.target.state().pc
                           if self.code_center is None else self.code_center)
                addresses = sorted(session.source.addresses)
                if addresses:
                    import bisect
                    index = bisect.bisect_left(addresses, current)
                    index = max(0, min(len(addresses) - 1, index + amount))
                    self.code_center = addresses[index]
                else:
                    self.code_center = max(0, current + amount * 4)
                self.refresh_panels()
            elif self.focused is self.query_one("#memory", MemoryPanel):
                session.memory_address = max(
                    0, session.memory_address + amount * 16)
                self.refresh_panels()
            elif self.focused is self.query_one("#registers", RegisterPanel):
                self.query_one("#registers", RegisterPanel).scroll_relative(
                    y=amount, animate=False)

        def action_center_pc(self) -> None:
            if self.focused is self.query_one("#code", CodePanel):
                self.code_center = None
                self.refresh_panels()

        def action_memory_home(self) -> None:
            if self.focused is self.query_one("#memory", MemoryPanel):
                session.memory_address = 0
                self.refresh_panels()

        def action_page_view(self, direction: int) -> None:
            if self.focused is self.query_one("#code", CodePanel):
                height = max(1, self.query_one("#code").content_region.height)
                self.action_move_view(direction * height)
            elif self.focused is self.query_one("#memory", MemoryPanel):
                rows = max(1, self.query_one("#memory").content_region.height)
                session.memory_address = max(
                    0, session.memory_address + direction * rows * 16)
                self.refresh_panels()

        def action_view_home(self) -> None:
            if self.focused is self.query_one("#code", CodePanel):
                addresses = sorted(session.source.addresses)
                self.code_center = addresses[0] if addresses else 0
                self.refresh_panels()
            elif self.focused is self.query_one("#memory", MemoryPanel):
                self.action_memory_home()

        def action_interrupt(self) -> None:
            if self.running:
                session.interrupt()

        def action_ctrl_c(self) -> None:
            if self.running:
                session.interrupt()
            else:
                self.exit()

        def action_video_key(self, key: str) -> None:
            """Trata las teclas de Tk como pulsadas sobre el panel código."""
            if self.search_context is not None:
                prompt = self.query_one("#prompt", Input)
                if key in {"Return", "KP_Enter"}:
                    query = prompt.value
                    prompt.value = ""
                    if query:
                        self._search(query)
                    self._finish_search()
                elif key == "BackSpace":
                    prompt.value = prompt.value[:-1]
                elif len(key) == 1 and key.isprintable():
                    prompt.value += key
                return
            code = self.query_one("#code", CodePanel)
            self.set_focus(code)
            commands = {
                "s": "step", "n": "over", "o": "finish", "c": "run",
                "R": "reset", "f": "frame", "q": "quit",
            }
            if key in commands:
                self.action_command(commands[key])
                return
            if key == "Up":
                self.action_move_view(-1)
            elif key == "Down":
                self.action_move_view(1)
            elif key == "Prior":
                self.action_page_view(-1)
            elif key == "Next":
                self.action_page_view(1)
            elif key == "Home":
                self.action_view_home()
            elif key == "p":
                self.action_center_pc()
            elif key == "b":
                self.action_toggle_breakpoint()
            elif key == "u":
                self.action_until_cursor()
            elif key == "/":
                self.action_start_search()
            elif key == "a":
                self.action_repeat_search()

        def action_video_error(self, message: str) -> None:
            self.query_one("#console", RichLog).write(
                f"[red]ERROR video: {_escape(message)}[/red]")

        def action_start_search(self) -> None:
            if self.running:
                return
            focused = self.focused
            contexts = {
                self.query_one("#code", CodePanel): "codigo",
                self.query_one("#memory", MemoryPanel): "memoria",
                self.query_one("#registers", RegisterPanel): "registros",
            }
            context = contexts.get(focused)
            if context is None:
                return
            self.search_context = context
            self.search_focus = focused
            prompt = self.query_one("#prompt", Input)
            prompt.value = ""
            prompt.placeholder = f"buscar en {context}"
            self.set_focus(prompt)

        def action_repeat_search(self) -> None:
            if self.running or self.last_search is None:
                return
            context, query = self.last_search
            focused_context = self._focused_search_context()
            if focused_context != context:
                self.query_one("#console", RichLog).write(
                    f"[yellow]la ultima busqueda pertenece a {context}[/yellow]")
                return
            self.search_context = context
            self._search(query, remember=False)
            self.search_context = None

        def _focused_search_context(self) -> str | None:
            focused = self.focused
            if focused is self.query_one("#code", CodePanel):
                return "codigo"
            if focused is self.query_one("#memory", MemoryPanel):
                return "memoria"
            if focused is self.query_one("#registers", RegisterPanel):
                return "registros"
            return None

        def _finish_search(self) -> None:
            prompt = self.query_one("#prompt", Input)
            prompt.placeholder = "comando (`help` para la lista)"
            focus = self.search_focus
            self.search_context = None
            self.search_focus = None
            if focus is not None:
                self.set_focus(focus)

        def _search(self, query: str, remember: bool = True) -> None:
            log = self.query_one("#console", RichLog)
            context = self.search_context
            if remember and context is not None:
                self.last_search = (context, query)
                self.last_memory_match = None
            needle = query.casefold()
            if context == "codigo":
                addresses = sorted(session.source.addresses)
                current = (session.target.state().pc if self.code_center is None
                           else self.code_center)
                later = [address for address in addresses if address > current]
                earlier = [address for address in addresses if address <= current]
                for address in later + earlier:
                    labels = " ".join(session.source.labels_at.get(address, ()))
                    text = session.source.text.get(address, "")
                    if needle in f"{labels} {text}".casefold():
                        self.code_center = address
                        log.write(f"[dim]encontrado en 0x{address:08X}[/dim]")
                        self.refresh_panels()
                        return
            elif context == "registros":
                token = query.upper()
                if token.startswith("R"):
                    token = token[1:]
                if token.isdigit() and 0 <= int(token) < 32:
                    index = int(token)
                    self.query_one("#registers", RegisterPanel).scroll_to(
                        y=index, animate=False)
                    log.write(f"[dim]R{index}[/dim]")
                    return
            elif context == "memoria":
                try:
                    compact = query.removeprefix("0x").replace(" ", "")
                    pattern = (bytes.fromhex(compact)
                               if compact and len(compact) % 2 == 0
                               and all(c in "0123456789abcdefABCDEF"
                                       for c in compact)
                               else query.encode())
                    start = session.memory_address
                    data = session.target.read_memory(start,
                                                      session.memory_length)
                    search_from = 0
                    if (not remember and self.last_memory_match is not None
                            and start <= self.last_memory_match
                            < start + len(data)):
                        search_from = self.last_memory_match - start + 1
                    offset = data.find(pattern, search_from)
                    if offset < 0 and search_from:
                        offset = data.find(pattern, 0, search_from)
                    if offset >= 0:
                        address = start + offset
                        self.last_memory_match = address
                        session.memory_address = address & ~0xF
                        log.write(
                            f"[dim]encontrado en 0x{address:08X}[/dim]")
                        self.refresh_panels()
                        return
                except (ValueError, TargetError):
                    pass
            log.write(f"[yellow]no encontrado: {_escape(query)}[/yellow]")

        def on_input_submitted(self, event: Input.Submitted) -> None:
            event.input.value = ""
            if self.search_context is not None:
                if event.value:
                    self._search(event.value)
                self._finish_search()
                return
            if event.value.strip():
                command = event.value.strip()
                name = command.split(None, 1)[0].lower()
                if name in {"c", "continue", "run", "until", "u",
                            "over", "n", "finish", "frame", "f"}:
                    if not self.running:
                        self.run_worker(
                            self._dispatch_long(command), exclusive=True)
                else:
                    self.dispatch(command)

        def on_mouse_down(self, event: events.MouseDown) -> None:
            prompt = self.query_one("#prompt", Input)
            console_area = self.query_one("#console-area", Vertical)
            if event.screen_offset in console_area.region:
                # Todo el panel hace de blanco cómodo para la línea de
                # comandos, no solo la única fila que ocupa el Input.
                self.set_focus(prompt)
            elif event.screen_offset in self.query_one("#code").region:
                code = self.query_one("#code", CodePanel)
                self.set_focus(code)
                row = event.screen_y - code.content_region.y
                if 0 <= row < len(self.code_row_targets):
                    target = self.code_row_targets[row]
                    if target is not None:
                        kind, address, start, end = target
                        column = event.screen_x - code.content_region.x
                        if start <= column < end:
                            if kind == "memory":
                                session.memory_address = address & ~0xF
                            else:
                                self.code_center = address
                            self.refresh_panels()
            elif event.screen_offset in self.query_one("#memory").region:
                self.set_focus(self.query_one("#memory", MemoryPanel))
            elif event.screen_offset in self.query_one("#registers").region:
                self.set_focus(self.query_one("#registers", RegisterPanel))
            elif self.focused is prompt:
                # Los paneles de solo lectura no aceptan foco por sí mismos.
                # Sin retirarlo explícitamente, el Input conserva las teclas y
                # el Footer no vuelve a enseñar los atajos del depurador.
                self.set_focus(None)

        def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
            if event.screen_offset in self.query_one("#code").region:
                self.set_focus(self.query_one("#code", CodePanel))
                self.action_move_view(-1)
                event.stop()
            elif event.screen_offset in self.query_one("#memory").region:
                self.set_focus(self.query_one("#memory", MemoryPanel))
                self.action_move_view(-1)
                event.stop()

        def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
            if event.screen_offset in self.query_one("#code").region:
                self.set_focus(self.query_one("#code", CodePanel))
                self.action_move_view(1)
                event.stop()
            elif event.screen_offset in self.query_one("#memory").region:
                self.set_focus(self.query_one("#memory", MemoryPanel))
                self.action_move_view(1)
                event.stop()

    return DebuggerApp()


def run_tui(session: DebugSession) -> int:
    try:
        build_app(session).run()
    finally:
        session.interrupt()
        session.close_video()
    return 0


def run_line_mode(session: DebugSession) -> int:
    """El mismo depurador sin terminal gráfico, para tuberías y sesiones ssh."""
    for warning in session.warnings:
        print(f"AVISO: {warning}")
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
