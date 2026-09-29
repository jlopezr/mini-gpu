CC ?= cc
CFLAGS ?= -std=c89 -Wall -Wextra -pedantic -g

CORE=basic.c basic_builtins.c
HEADERS=basic.h basic_builtins.h

test_basic_store: $(CORE) $(HEADERS) test_basic_store.c
	$(CC) $(CFLAGS) -o test_basic_store $(CORE) test_basic_store.c

test_expr: $(CORE) $(HEADERS) test_expr.c
	$(CC) $(CFLAGS) -o test_expr $(CORE) test_expr.c

test_run: $(CORE) $(HEADERS) test_run.c
	$(CC) $(CFLAGS) -o test_run $(CORE) test_run.c

test_console: $(CORE) $(HEADERS) test_console.c
	$(CC) $(CFLAGS) -o test_console $(CORE) test_console.c

test_repl: $(CORE) $(HEADERS) test_repl.c
	$(CC) $(CFLAGS) -o test_repl $(CORE) test_repl.c

test_strings: $(CORE) $(HEADERS) test_strings.c
	$(CC) $(CFLAGS) -o test_strings $(CORE) test_strings.c

test_input: $(CORE) $(HEADERS) test_input.c
	$(CC) $(CFLAGS) -o test_input $(CORE) test_input.c

test_arrays: $(CORE) $(HEADERS) test_arrays.c
	$(CC) $(CFLAGS) -o test_arrays $(CORE) test_arrays.c

test_logic: $(CORE) $(HEADERS) test_logic.c
	$(CC) $(CFLAGS) -o test_logic $(CORE) test_logic.c

basic_host: $(CORE) $(HEADERS) basic_platform.h basic_main.c basic_platform_host.c
	$(CC) $(CFLAGS) -o basic_host $(CORE) basic_main.c basic_platform_host.c

# BASIC para la placa con la consola de texto del prototipo 30: entrada por
# UART, salida por UART y pantalla. No se compila con $(CC) sino con mini-lcc,
# que en Windows necesita vcvars32.bat cargado en la misma llamada. Se carga con
#   board-load --prototype 30 --program 28.basic/_build/basic_console.asm
CONSOLE_SRC=basic_mini_console.c basic_platform_console.c basic_platform.h basic_main.c $(CORE) $(HEADERS)

_build/basic_console.asm: $(CONSOLE_SRC)
	mkdir -p _build
	python ../tools/mini-lcc basic_mini_console.c -o $@

basic_console: _build/basic_console.asm

test: test_basic_store test_expr test_run test_console test_repl test_strings test_input test_arrays test_logic
	./test_basic_store
	./test_expr
	./test_run
	./test_console
	./test_repl
	./test_strings
	./test_input
	./test_arrays
	./test_logic

clean:
	rm -f _build/basic_console.asm basic_host test_basic_store test_expr test_run test_console test_repl test_strings test_input test_arrays test_logic
