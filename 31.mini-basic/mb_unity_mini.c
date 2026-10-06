/*
 * MiniCPU unity build of mini-basic: mini-lcc has no linker, so the TUI, the MMIO
 * console, the interpreter and the application go in one translation unit. The
 * order of the TUI modules follows z.tui/tui_unity.c.
 */
#define TUI_BACKEND_MMIO

#include "../z.tui/tui.c"
#include "../z.tui/tui_window.c"
#include "../z.tui/tui_button.c"
#include "../z.tui/tui_label.c"
#include "../z.tui/tui_panel.c"
#include "../z.tui/tui_edit.c"
#include "../z.tui/tui_listbox.c"
#include "../z.tui/tui_menu.c"
#include "../z.tui/tui_statusbar.c"
#include "../z.tui/tui_checkbox.c"
#include "../z.tui/tui_radiobutton.c"
#include "../z.tui/tui_combobox.c"
#include "../z.tui/tui_scrollbar.c"
#include "../z.tui/tui_textmodel.c"
#include "../z.tui/tui_editor.c"
#include "../z.tui/console_mini.c"

#include "../28.basic/basic.c"
#include "../28.basic/basic_builtins.c"

#include "mb_main.c"
