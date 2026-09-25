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

test: test_basic_store test_expr test_run test_console test_repl
	./test_basic_store
	./test_expr
	./test_run
	./test_console
	./test_repl

clean:
	rm -f test_basic_store test_expr test_run test_console test_repl
