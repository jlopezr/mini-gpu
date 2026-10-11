/*
 * MiniCPU unity build of mini-basic: mini-lcc has no linker, so the TUI, the MMIO
 * console, the interpreter and the application go in one translation unit. The
 * order of the TUI modules follows v.tui/tui_unity.c.
 */
#define TUI_BACKEND_MMIO

#include "../v.tui/tui.c"
#include "../v.tui/tui_window.c"
#include "../v.tui/tui_button.c"
#include "../v.tui/tui_label.c"
#include "../v.tui/tui_panel.c"
#include "../v.tui/tui_edit.c"
#include "../v.tui/tui_listbox.c"
#include "../v.tui/tui_menu.c"
#include "../v.tui/tui_statusbar.c"
#include "../v.tui/tui_checkbox.c"
#include "../v.tui/tui_radiobutton.c"
#include "../v.tui/tui_combobox.c"
#include "../v.tui/tui_scrollbar.c"
#include "../v.tui/tui_textmodel.c"
#include "../v.tui/tui_editor.c"
#include "../v.tui/console_mini.c"

#include "../28.basic/basic.c"
#include "../28.basic/basic_builtins.c"

#include "mb_main.c"
