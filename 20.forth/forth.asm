; ============================================================================
; forth.asm - interprete de Forth sobre la consola serie de la MiniCPU
;
; Un Forth son dos cosas: un interprete de texto sobre una pila y un compilador
; que anade palabras al diccionario. Aqui estan las dos, y lo interesante es
; que son EL MISMO BUCLE: la unica diferencia es una variable, STATE, que dice
; si la palabra encontrada se ejecuta o se anota.
;
; Lo que `:` produce no es codigo maquina: es una lista de punteros a entradas
; del diccionario, y hace falta un segundo interprete --el INTERNO, en
; `run_colon`-- para recorrerla. Por eso Forth sigue siendo un lenguaje
; interpretado aunque tenga compilador, y por eso "compilar" aqui significa
; algo mucho mas modesto que en C.
;
; Se usa por la consola del monitor, que es la misma UART por la que se carga:
;
;     .\run-demo.ps1 forth            (desde 20.forth)
;     ..\.venv\Scripts\python.exe ..\19.fpga-cpu-hdmi-ls\monitor.py console
;
;     ok> 2 3 + .
;     5
;     ok> 10 20 30 .s
;     <3> 10 20 30
;     ok> bye
;
; ---- Por que un diccionario de palabras empaquetadas ----
;
; Cada nombre cabe en CUATRO caracteres y se guarda como una sola palabra de 32
; bits: `DUP` es 0x00505544. Asi buscar una palabra es comparar enteros, no
; recorrer cadenas, y el diccionario entero son dos palabras por entrada:
; nombre y direccion del codigo.
;
; Es una limitacion de verdad --`NEGATE` no cabe, y por eso la palabra se llama
; `NEG`-- pero compra un buscador de siete instrucciones. Un Forth con nombres
; largos necesita longitud mas bytes mas comparacion byte a byte, y eso es
; mucho mas codigo para un interprete que tiene que caber en una carpeta.
;
; ---- Por que hacen falta JAL, JALR y JR ----
;
; El interprete no puede saber a que codigo saltar hasta que ha buscado la
; palabra en el diccionario: el destino sale de una tabla en memoria. Eso es
; exactamente `JALR`, y sin el este programa no se puede escribir. Con solo
; `BRA` habria que poner una cadena de comparaciones, una por palabra, y el
; diccionario dejaria de ser datos para convertirse en codigo.
;
; Las rutinas nativas siguen devolviendo por registros de enlace repartidos a
; mano, y llegan a cuatro niveles:
;
;     main (R31) -> palabra (R28) -> print_num (R29) -> emit (R30)
;
; Eso funciona porque la profundidad se conoce al escribir el programa. Lo que
; NO se conoce es cuanto se anidan las definiciones que escriba el usuario:
; `: b a a ;` y `: c b b ;` pueden encadenarse sin limite. Para eso esta la
; pila de retorno en memoria (R19), y se usa en un solo sitio: `inner_call`.
;
; ---- Mapa de memoria ----
;
;   0x00000000  este programa, con el diccionario y los mensajes dentro
;   0x00100000  pila de datos, hacia arriba
;   0x00101000  buffer de la linea de entrada, 128 bytes
;   0x00102000  memoria libre para @ y !
;   0x00103000  pila de retorno del interprete interno
;   0x00104000  diccionario en RAM, donde : anade palabras
;   0x80000200  puerto serie: +0 DATA, +4 STATUS
;
; ---- Convencion de registros ----
;
;   R20 base del puerto serie        R21 puntero de pila (primer hueco)
;   R22 base de la pila              R23 base del buffer de entrada
;   R24 puntero de lectura del buffer
;   R3  constante 0
;   R4  argumento y valor devuelto de las rutinas
;   R5, R6, R7  temporales de las rutinas
;   R8..R12 temporales del interprete
;   R28 enlace de las palabras   R29 enlace de print_num y read_line
;   R30 enlace de emit y key     R31 enlace de las rutinas del bucle principal
; ============================================================================

start:
    MOVHI R20, 0x8000
    ORI   R20, R20, 0x0200      ; puerto serie
    MOVHI R22, 0x0010           ; 0x00100000, base de la pila
    ADDI  R21, R22, 0           ; pila vacia
    MOVHI R23, 0x0010
    ORI   R23, R23, 0x1000      ; buffer de entrada
    MOVI  R3, 0
    ; SHL y SHR toman el desplazamiento de un REGISTRO, no de un inmediato, asi
    ; que los dos que usa el programa se dejan puestos aqui.
    MOVI  R26, 2
    MOVI  R27, 8

    ; Pila de RETORNO. Es otra cosa que la de datos: aqui van los punteros de
    ; instruccion del interprete interno cuando una definicion compilada llama
    ; a otra. Sin ella `:` no puede existir, porque el anidamiento no se conoce
    ; al ensamblar y no se puede repartir un registro por nivel.
    MOVHI R19, 0x0010
    ORI   R19, R19, 0x3000

    ; Diccionario en RAM. Los builtins viven en la imagen y son el final de la
    ; lista; las palabras nuevas se anaden AQUI y se encadenan por delante, asi
    ; que una redefinicion tapa a la anterior, como en cualquier Forth.
    MOVHI R16, 0x0010
    ORI   R16, R16, 0x4000      ; HERE
    MOVI  R17, d_last           ; HEAD: la ultima entrada de la imagen

    MOVI  R2, 0                 ; STATE: 0 interpretando, 1 compilando
    MOVI  R0, 10                ; BASE. R0 es un registro general en esta ISA

    MOVI  R4, msg_banner
    JAL   R31, print_str

; ---------------------------------------------------------------------------
; Bucle principal: prompt, leer una linea, interpretarla.
; ---------------------------------------------------------------------------
main_loop:
    MOVI  R4, msg_prompt
    JAL   R31, print_str
    JAL   R31, read_line        ; llena el buffer, termina en NUL
    ADDI  R24, R23, 0           ; puntero de lectura al principio

interpret:
    JAL   R29, skip_spaces
    LOADUB R8, R24, 0
    BEQ   R8, R3, main_loop     ; fin de la linea

    JAL   R29, read_token       ; R4 = nombre empaquetado, R5 = longitud
    ADDI  R9, R4, 0             ; R9 = nombre
    ADDI  R10, R5, 0            ; R10 = longitud

    ; --- buscar en el diccionario, de la mas nueva a la mas vieja ---
    ;
    ; Se comparan DOS cosas: el nombre empaquetado y la longitud. Solo con el
    ; nombre, `dropit` coincidiria con `DROP` --el empaquetado se queda con los
    ; cuatro primeros caracteres-- y ejecutaria una palabra que el usuario no
    ; ha escrito.
    ;
    ; Con la longitud tambien, `dropit` (6) y `DROP` (4) ya no chocan, y siguen
    ; siendo legales los nombres largos que el usuario defina con `:`. Lo que
    ; SI chocan son dos nombres de la misma longitud que solo se diferencien a
    ; partir del quinto caracter: `dropit` y `dropzz` son la misma palabra.
    ADDI  R11, R17, 0
find:
    BEQ   R11, R3, not_a_word   ; se acabo la lista
    LOAD  R12, R11, 4           ; nombre de la entrada
    BNE   R12, R9, find_next
    LOAD  R14, R11, 12          ; flags: la longitud va en los bits 15:8
    SHR   R14, R14, R27
    ANDI  R14, R14, 0x00FF
    BEQ   R14, R10, found
find_next:
    LOAD  R11, R11, 0           ; enlace a la anterior
    BRA   find

; La encontro. Aqui esta la bifurcacion que convierte al interprete en
; compilador: con STATE=0 la ejecuta, y con STATE=1 se limita a ANOTARLA en la
; definicion que se esta construyendo. Son dos ramas del mismo bucle; eso es
; todo el compilador de Forth.
;
; Salvo las palabras INMEDIATAS, que se ejecutan tambien compilando. Si `;` no
; lo fuera, se anotaria a si misma y la definicion no se cerraria nunca.
found:
    LOAD  R14, R11, 12          ; flags
    ANDI  R15, R14, 1           ; bit 0: inmediata
    BNE   R15, R3, execute_it
    BEQ   R2, R3, execute_it    ; STATE = 0: ejecutar
    STORE R11, R16, 0           ; compilar: anotar la entrada
    ADDI  R16, R16, 4
    BRA   interpret

execute_it:
    ADDI  R13, R11, 0
    JAL   R31, run_word
    BRA   interpret

; No esta en el diccionario: puede ser un numero.
not_a_word:
    JAL   R29, parse_number     ; R4 = valor, R5 = 1 si era un numero
    BEQ   R5, R3, unknown
    BEQ   R2, R3, push_number

    ; Compilando, un numero no se apila ahora: se anota un LIT y el valor
    ; detras, y ya lo apilara el interprete interno cuando toque.
    MOVI  R15, d_lit
    STORE R15, R16, 0
    ADDI  R16, R16, 4
    STORE R4, R16, 0
    ADDI  R16, R16, 4
    BRA   interpret

push_number:
    STORE R4, R21, 0
    ADDI  R21, R21, 4
    BRA   interpret

unknown:
    MOVI  R4, msg_unknown
    JAL   R31, print_str
    JAL   R29, print_token      ; ensena la palabra que no entendio
    MOVI  R4, 0x0A
    JAL   R31, emit_from_main
    BRA   abort                 ; se descarta el resto de la linea

; ---------------------------------------------------------------------------
; Abortar: se llega aqui desde cualquier error.
;
; Ademas de tirar la linea, deshace la definicion a medias. Sin esto, un fallo
; dentro de un `:` deja en la lista una entrada cuyo cuerpo no termina en cero,
; y la proxima vez que alguien la invoque el interprete interno se va a
; recorrer memoria. Es el `SMUDGE` de los Forth de verdad, en version pobre.
; ---------------------------------------------------------------------------
abort:
    MOVHI R19, 0x0010
    ORI   R19, R19, 0x3000      ; pila de retorno vacia
    BEQ   R2, R3, abort_done
    ADDI  R16, R17, 0           ; HERE vuelve al principio de la entrada
    LOAD  R17, R17, 0           ; HEAD vuelve a la anterior
    MOVI  R2, 0
abort_done:
    BRA   main_loop

; ---------------------------------------------------------------------------
; Ejecutar una palabra. R13 = direccion de su entrada. Vuelve por R31.
;
; Una primitiva es codigo nativo que termina en `JR R28`. Una definicion
; compilada es una lista de direcciones de entrada terminada en cero, y lo que
; la recorre es el INTERPRETE INTERNO de aqui abajo. Los dos se invocan igual
; desde fuera; la diferencia esta en el bit 1 de las flags.
; ---------------------------------------------------------------------------
run_word:
    LOAD  R15, R13, 12
    ANDI  R14, R15, 4           ; bit 2: hecha con CREATE
    BNE   R14, R3, run_created
    ANDI  R15, R15, 2
    BNE   R15, R3, run_colon
    LOAD  R14, R13, 8
    JALR  R28, R14, 0
    JR    R31

; Una palabra hecha con CREATE apila SIEMPRE la direccion de su zona de datos
; --que esta justo detras de la cabecera-- y despues, si DOES> le dio un cuerpo,
; lo ejecuta. Con esas dos lineas se construyen CONSTANT, VARIABLE y los arrays
; dentro del propio Forth, sin tocar el interprete.
run_created:
    ADDI  R6, R13, 16
    STORE R6, R21, 0
    ADDI  R21, R21, 4
    LOAD  R14, R13, 8           ; cuerpo del DOES>, o cero
    BEQ   R14, R3, run_created_done
    ADDI  R18, R14, 0
    ADDI  R1, R19, 0
    BRA   inner
run_created_done:
    JR    R31

run_colon:
    LOAD  R18, R13, 8           ; IP = cuerpo de la definicion
    ADDI  R1, R19, 0            ; fondo de la pila de retorno de ESTA ejecucion

inner:
    LOAD  R13, R18, 0           ; siguiente palabra de la definicion
    ADDI  R18, R18, 4
    BEQ   R13, R3, inner_exit   ; cero = fin de la definicion
    LOAD  R15, R13, 12
    ANDI  R14, R15, 4
    BNE   R14, R3, inner_created
    ANDI  R15, R15, 2
    BNE   R15, R3, inner_call
    LOAD  R14, R13, 8
    JALR  R28, R14, 0           ; primitiva
    BRA   inner

; Lo mismo que run_created, pero dentro de una definicion.
inner_created:
    ADDI  R6, R13, 16
    STORE R6, R21, 0
    ADDI  R21, R21, 4
    LOAD  R14, R13, 8
    BEQ   R14, R3, inner        ; CREATE pelado: solo la direccion
    STORE R18, R19, 0
    ADDI  R19, R19, 4
    ADDI  R18, R14, 0
    BRA   inner

; Una definicion dentro de otra: se guarda donde ibamos y se salta a su cuerpo.
; ESTE es el sitio donde hace falta la pila de retorno, y el unico: la
; profundidad depende de lo que el usuario escriba, no de lo que haya escrito
; quien programo el interprete.
inner_call:
    STORE R18, R19, 0
    ADDI  R19, R19, 4
    LOAD  R18, R13, 8
    BRA   inner

inner_exit:
    BGE   R1, R19, inner_done   ; si esta en el fondo, se acabo
    ADDI  R19, R19, -4
    LOAD  R18, R19, 0
    BRA   inner

inner_done:
    JR    R31

; ---------------------------------------------------------------------------
; Las palabras del diccionario. Todas vuelven por R28.
;
; La pila crece hacia arriba y R21 apunta al primer HUECO, asi que la cima esta
; en R21-4. Cada palabra comprueba que hay bastante antes de tocar nada: sin
; eso, un `+` con la pila vacia leeria memoria de cualquier sitio y el error
; aparecia mucho mas tarde y en otro lado.
; ---------------------------------------------------------------------------

w_plus:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    LOAD  R7, R21, -8
    ADD   R7, R7, R6
    STORE R7, R21, -8
    ADDI  R21, R21, -4
    JR    R28

w_minus:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    LOAD  R7, R21, -8
    SUB   R7, R7, R6
    STORE R7, R21, -8
    ADDI  R21, R21, -4
    JR    R28

w_star:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    LOAD  R7, R21, -8
    MUL   R7, R7, R6
    STORE R7, R21, -8
    ADDI  R21, R21, -4
    JR    R28

w_slash:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    ; Dividir por cero para la CPU con un codigo de error terminal, y eso
    ; mataria el interprete entero. Se comprueba antes.
    BEQ   R6, R3, divzero_error
    LOAD  R7, R21, -8
    DIV   R7, R7, R6
    STORE R7, R21, -8
    ADDI  R21, R21, -4
    JR    R28

w_dup:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    STORE R6, R21, 0
    ADDI  R21, R21, 4
    JR    R28

w_drop:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    ADDI  R21, R21, -4
    JR    R28

w_swap:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    LOAD  R7, R21, -8
    STORE R6, R21, -8
    STORE R7, R21, -4
    JR    R28

w_over:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -8
    STORE R6, R21, 0
    ADDI  R21, R21, 4
    JR    R28

w_neg:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    SUB   R6, R3, R6
    STORE R6, R21, -4
    JR    R28

; `.` saca la cima y la imprime seguida de un salto de linea.
w_dot:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R4, R21, -4
    ADDI  R21, R21, -4
    JAL   R29, print_num
    MOVI  R4, 0x0A
    JAL   R30, emit
    JR    R28

; `.S` ensena la pila entera sin tocarla: `<3> 10 20 30`.
w_dots:
    MOVI  R4, 0x3C              ; '<'
    JAL   R30, emit
    SUB   R4, R21, R22
    SHR   R4, R4, R26           ; profundidad = bytes / 4
    JAL   R29, print_num
    MOVI  R4, 0x3E              ; '>'
    JAL   R30, emit
    ; El cursor va en R7 y no en R11 porque print_num usa R11 de temporal:
    ; con el cursor ahi, la primera cifra impresa lo destruia y el bucle se
    ; quedaba recorriendo memoria para siempre. Los cuatro niveles de llamada
    ; comparten un solo banco de registros y no hay pila donde salvarlos, asi
    ; que quien llama tiene que conocer lo que usa el llamado.
    ADDI  R7, R22, 0
dots_loop:
    BGE   R7, R21, dots_done
    MOVI  R4, 0x20
    JAL   R30, emit
    LOAD  R4, R7, 0
    ; El cursor se SALVA en la pila de retorno mientras print_num trabaja, en
    ; vez de confiar en que no toque este registro.
    ;
    ; La version anterior lo tenia en R11, print_num lo destrozaba y el bucle
    ; se iba a recorrer memoria. Se movio a R7... y al anadir la base de
    ; numeracion, print_num empezo a usar R7 tambien y volvio a romperse
    ; exactamente igual. Dos veces el mismo fallo es que el metodo estaba mal:
    ; con un solo banco de registros y sin convenio de quien salva que, elegir
    ; "un registro que el otro no use" no es una solucion, es una apuesta.
    STORE R7, R19, 0
    ADDI  R19, R19, 4
    JAL   R29, print_num
    ADDI  R19, R19, -4
    LOAD  R7, R19, 0
    ADDI  R7, R7, 4
    BRA   dots_loop
dots_done:
    MOVI  R4, 0x0A
    JAL   R30, emit
    JR    R28

; Comparaciones: dejan -1 (cierto) o 0 (falso), como manda Forth.
w_equals:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    LOAD  R7, R21, -8
    MOVI  R8, 0
    BNE   R7, R6, eq_store
    MOVI  R8, -1
eq_store:
    STORE R8, R21, -8
    ADDI  R21, R21, -4
    JR    R28

w_less:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    LOAD  R7, R21, -8
    MOVI  R8, 0
    BGE   R7, R6, lt_store
    MOVI  R8, -1
lt_store:
    STORE R8, R21, -8
    ADDI  R21, R21, -4
    JR    R28

w_greater:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    LOAD  R7, R21, -8
    MOVI  R8, 0
    BGE   R6, R7, gt_store
    MOVI  R8, -1
gt_store:
    STORE R8, R21, -8
    ADDI  R21, R21, -4
    JR    R28

; `@` y `!` dan acceso a la memoria: `addr @` y `valor addr !`.
w_fetch:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    LOAD  R7, R6, 0
    STORE R7, R21, -4
    JR    R28

w_store:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4           ; direccion
    LOAD  R7, R21, -8           ; valor
    STORE R7, R6, 0
    ADDI  R21, R21, -8
    JR    R28

w_cr:
    MOVI  R4, 0x0A
    JAL   R30, emit
    JR    R28

w_bye:
    MOVI  R4, msg_bye
    JAL   R29, print_str_inner
    HALT

; ---------------------------------------------------------------------------
; El compilador: tres palabras y una variable de estado.
; ---------------------------------------------------------------------------

; `:` toma el nombre que viene DETRAS en la linea, crea la cabecera y pone el
; interprete en modo compilacion. Que lea de la entrada es lo que la hace
; distinta de las demas: las otras palabras solo ven la pila.
;
; Puede llamar a skip_spaces y read_token porque esas devuelven por R29, y R29
; esta libre aqui: `:` se ejecuta bajo R28 y R31 lo tiene run_word.
w_colon:
    JAL   R29, skip_spaces
    JAL   R29, read_token       ; R4 = nombre empaquetado, R5 = longitud
    ; Las flags se arman ANTES de tocar R5, que es la longitud y hace falta.
    SHL   R6, R5, R27           ; longitud en los bits 15:8
    ORI   R6, R6, 2             ; bit 1: es una definicion compilada
    STORE R17, R16, 0           ; enlace = la entrada anterior
    STORE R4,  R16, 4           ; nombre
    ADDI  R7, R16, 16
    STORE R7,  R16, 8           ; el cuerpo empieza justo detras de la cabecera
    STORE R6,  R16, 12
    ADDI  R17, R16, 0           ; HEAD pasa a ser esta
    ADDI  R16, R16, 16          ; HERE avanza al cuerpo
    MOVI  R2, 1                 ; a compilar
    JR    R28

; `;` cierra la definicion. Es INMEDIATA --flags bit 0-- y tiene que serlo: si
; se compilara como las demas, se anotaria dentro de la definicion y el modo
; compilacion no se apagaria nunca.
w_semi:
    STORE R3, R16, 0            ; cero = fin del cuerpo
    ADDI  R16, R16, 4
    MOVI  R2, 0
    JR    R28

; LIT no tiene nombre que se pueda escribir: solo la coloca el compilador, y
; solo aparece dentro de una definicion. Coge la palabra que va detras de ella
; en el cuerpo --por eso toca R18, el puntero del interprete interno-- y la
; apila.
w_lit:
    LOAD  R6, R18, 0
    ADDI  R18, R18, 4
    STORE R6, R21, 0
    ADDI  R21, R21, 4
    JR    R28

; ---------------------------------------------------------------------------
; Pila
; ---------------------------------------------------------------------------

w_rot:                          ; a b c -- b c a
    ADDI  R5, R22, 12
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -12          ; a
    LOAD  R7, R21, -8           ; b
    STORE R7, R21, -12
    LOAD  R7, R21, -4           ; c
    STORE R7, R21, -8
    STORE R6, R21, -4
    JR    R28

w_nip:                          ; a b -- b
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    STORE R6, R21, -8
    ADDI  R21, R21, -4
    JR    R28

w_tuck:                         ; a b -- b a b
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4           ; b
    LOAD  R7, R21, -8           ; a
    STORE R6, R21, -8
    STORE R7, R21, -4
    STORE R6, R21, 0
    ADDI  R21, R21, 4
    JR    R28

w_twodup:                       ; a b -- a b a b
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -8
    LOAD  R7, R21, -4
    STORE R6, R21, 0
    STORE R7, R21, 4
    ADDI  R21, R21, 8
    JR    R28

w_twodrop:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    ADDI  R21, R21, -8
    JR    R28

w_depth:
    SUB   R6, R21, R22
    SHR   R6, R6, R26
    STORE R6, R21, 0
    ADDI  R21, R21, 4
    JR    R28

; n PICK copia el elemento n contando desde arriba; 0 PICK es DUP.
w_pick:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    ADDI  R21, R21, -4
    ADD   R7, R6, R6
    ADD   R7, R7, R7            ; n * 4
    SUB   R7, R21, R7
    ADDI  R7, R7, -4
    BLT   R7, R22, stack_error  ; mas hondo que la pila
    LOAD  R6, R7, 0
    STORE R6, R21, 0
    ADDI  R21, R21, 4
    JR    R28

; ---------------------------------------------------------------------------
; Aritmetica y logica
; ---------------------------------------------------------------------------

; MOD no existe en la CPU: DIV solo da el cociente, asi que el resto se calcula
; con n - (n/m)*m. Son dos instrucciones caras --DIV son 40 ciclos-- y es la
; unica forma con esta ISA.
w_mod:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    BEQ   R6, R3, divzero_error
    LOAD  R7, R21, -8
    DIV   R5, R7, R6
    MUL   R5, R5, R6
    SUB   R7, R7, R5
    STORE R7, R21, -8
    ADDI  R21, R21, -4
    JR    R28

w_abs:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    BGE   R6, R3, abs_done
    SUB   R6, R3, R6
    STORE R6, R21, -4
abs_done:
    JR    R28

w_min:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    LOAD  R7, R21, -8
    ADDI  R21, R21, -4
    BLT   R6, R7, min_take
    JR    R28
min_take:
    STORE R6, R21, -4
    JR    R28

w_max:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    LOAD  R7, R21, -8
    ADDI  R21, R21, -4
    BLT   R7, R6, max_take
    JR    R28
max_take:
    STORE R6, R21, -4
    JR    R28

w_oneplus:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    ADDI  R6, R6, 1
    STORE R6, R21, -4
    JR    R28

w_oneminus:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    ADDI  R6, R6, -1
    STORE R6, R21, -4
    JR    R28

w_and:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    LOAD  R7, R21, -8
    AND   R7, R7, R6
    STORE R7, R21, -8
    ADDI  R21, R21, -4
    JR    R28

w_or:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    LOAD  R7, R21, -8
    OR    R7, R7, R6
    STORE R7, R21, -8
    ADDI  R21, R21, -4
    JR    R28

w_xor:
    ADDI  R5, R22, 8
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    LOAD  R7, R21, -8
    XOR   R7, R7, R6
    STORE R7, R21, -8
    ADDI  R21, R21, -4
    JR    R28

w_invert:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    MOVI  R7, -1
    XOR   R6, R6, R7
    STORE R6, R21, -4
    JR    R28

w_zeroeq:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    MOVI  R7, 0
    BNE   R6, R3, zeq_store
    MOVI  R7, -1
zeq_store:
    STORE R7, R21, -4
    JR    R28

w_zeroless:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    MOVI  R7, 0
    BGE   R6, R3, zlt_store
    MOVI  R7, -1
zlt_store:
    STORE R7, R21, -4
    JR    R28

; ---------------------------------------------------------------------------
; Salida de texto y base de numeracion
; ---------------------------------------------------------------------------

w_emit:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R4, R21, -4
    ADDI  R21, R21, -4
    JAL   R30, emit
    JR    R28

w_space:
    MOVI  R4, 0x20
    JAL   R30, emit
    JR    R28

; La base vive en R0, que en esta ISA es un registro general como los demas.
w_hex:
    MOVI  R0, 16
    JR    R28

w_decimal:
    MOVI  R0, 10
    JR    R28

; ." texto"  imprime el texto. Interpretando lo suelta ya; compilando lo mete
; en el cuerpo detras de una primitiva escondida que lo imprimira.
w_dotquote:
    LOADUB R6, R24, 0           ; saltarse UN espacio tras ."
    MOVI  R7, 0x20
    BNE   R6, R7, dq_start
    ADDI  R24, R24, 1
dq_start:
    BEQ   R2, R3, dq_now

    ; --- compilando ---
    MOVI  R6, d_dotstr
    STORE R6, R16, 0
    ADDI  R16, R16, 4
dq_copy:
    LOADUB R6, R24, 0
    BEQ   R6, R3, dq_end        ; se acabo la linea sin cerrar comillas
    MOVI  R7, 0x22
    BEQ   R6, R7, dq_close
    STOREB R6, R16, 0
    ADDI  R16, R16, 1
    ADDI  R24, R24, 1
    BRA   dq_copy
dq_close:
    ADDI  R24, R24, 1           ; consumir la comilla
dq_end:
    STOREB R3, R16, 0           ; NUL
    ADDI  R16, R16, 4
    MOVI  R7, -4
    AND   R16, R16, R7          ; y alinear a palabra
    JR    R28

    ; --- interpretando: se imprime directamente ---
dq_now:
    LOADUB R4, R24, 0
    BEQ   R4, R3, dq_now_done
    MOVI  R7, 0x22
    BEQ   R4, R7, dq_now_close
    JAL   R30, emit
    ADDI  R24, R24, 1
    BRA   dq_now
dq_now_close:
    ADDI  R24, R24, 1
dq_now_done:
    JR    R28

; La primitiva escondida que imprime la cadena incrustada en el cuerpo y deja
; el puntero del interprete interno justo detras.
w_dotstr:
    ADDI  R7, R18, 0
ds_loop:
    LOADUB R4, R7, 0
    BEQ   R4, R3, ds_done
    JAL   R30, emit
    ADDI  R7, R7, 1
    BRA   ds_loop
ds_done:
    ADDI  R7, R7, 4
    MOVI  R6, -4
    AND   R18, R7, R6
    JR    R28

; ---------------------------------------------------------------------------
; EXIT y RECURSE
; ---------------------------------------------------------------------------

; EXIT sale de la definicion en curso. Apuntar el interprete interno a una
; celda con cero reutiliza la salida normal --que desapila el retorno-- en vez
; de duplicarla.
w_exit:
    MOVI  R18, does_end
    JR    R28

; RECURSE compila una referencia a la palabra que se esta definiendo. Hace
; falta porque su nombre todavia no se puede buscar de forma fiable: si se
; redefine una palabra existente, buscarla por nombre encontraria la VIEJA.
w_recurse:
    BEQ   R2, R3, compile_only
    STORE R17, R16, 0
    ADDI  R16, R16, 4
    JR    R28

; ---------------------------------------------------------------------------
; CREATE y DOES>: palabras que definen palabras.
;
; `CREATE` hace una cabecera con el nombre que viene detras y nada mas. La
; palabra resultante apila la direccion de su zona de datos, que empieza justo
; detras de la cabecera. Con `,` se van metiendo valores ahi.
;
; `DOES>` es lo que convierte eso en un mecanismo de verdad. Va DENTRO de una
; definicion y parte en dos lo que hace esa definicion:
;
;     : CONSTANT  CREATE , DOES> @ ;
;                 ^^^^^^^^        lo que pasa al DEFINIR
;                            ^^   lo que hace la palabra DEFINIDA
;
; Y el truco de como se implementa es bonito: `DOES>` NO es inmediata, se
; compila como una palabra normal. Cuando CONSTANT se ejecuta y llega a ella,
; el puntero del interprete interno apunta ya a lo que la sigue --el `@`--, asi
; que basta con guardar ese puntero en el campo de codigo de la palabra recien
; creada y terminar la definicion ahi mismo.
;
; Por eso `CONSTANT` y `VARIABLE` no son parte de este programa: se escriben en
; Forth, desde la consola. Ver el README.
; ---------------------------------------------------------------------------

w_create:
    JAL   R29, skip_spaces
    JAL   R29, read_token       ; R4 = nombre, R5 = longitud
    SHL   R6, R5, R27
    ORI   R6, R6, 4             ; bit 2: hecha con CREATE
    STORE R17, R16, 0
    STORE R4,  R16, 4
    STORE R3,  R16, 8           ; sin cuerpo de DOES> todavia
    STORE R6,  R16, 12
    ADDI  R17, R16, 0           ; HEAD = esta
    ADDI  R16, R16, 16          ; y su zona de datos empieza aqui
    JR    R28

; `,` mete la cima de la pila en HERE y avanza.
w_comma:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    ADDI  R21, R21, -4
    STORE R6, R16, 0
    ADDI  R16, R16, 4
    JR    R28

; `ALLOT` reserva n BYTES.
w_allot:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    ADDI  R21, R21, -4
    ADD   R16, R16, R6
    JR    R28

; `CELLS` convierte un numero de celdas en bytes. Aqui una celda son 4.
w_cells:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    ADD   R6, R6, R6
    ADD   R6, R6, R6
    STORE R6, R21, -4
    JR    R28

; DOES> en tiempo de ejecucion de la palabra definidora.
w_does:
    ; R18 apunta ya a lo que sigue a DOES> en el cuerpo: ese es el
    ; comportamiento que se le da a la palabra recien creada.
    STORE R18, R17, 8
    ; Y se termina la definicion actual aqui, sin ejecutar lo que sigue.
    ; Apuntando el interprete interno a una celda con cero se reutiliza la
    ; salida normal en vez de duplicarla.
    MOVI  R18, does_end
    JR    R28

does_end:
    .word 0

; ---------------------------------------------------------------------------
; Control de flujo
;
; Las dos primitivas. Solo aparecen dentro de definiciones, puestas por las
; palabras inmediatas de abajo, y las dos leen su destino de la celda que las
; sigue en el cuerpo.
; ---------------------------------------------------------------------------

w_branch:
    LOAD  R18, R18, 0           ; IP = destino
    JR    R28

w_zbranch:
    ADDI  R5, R22, 4
    BLT   R21, R5, stack_error
    LOAD  R6, R21, -4
    ADDI  R21, R21, -4
    BEQ   R6, R3, zb_take
    ADDI  R18, R18, 4           ; falso: saltarse la celda del destino
    JR    R28
zb_take:
    LOAD  R18, R18, 0
    JR    R28

; ---------------------------------------------------------------------------
; Y las palabras que las colocan. TODAS son inmediatas: se ejecutan mientras se
; compila, que es como Forth construye sus estructuras de control sin que el
; interprete sepa nada de ellas.
;
; El truco esta en que un salto hacia adelante no sabe su destino cuando se
; emite: `IF` deja un HUECO y apunta su direccion; `THEN` lo rellena con donde
; hemos llegado. Las direcciones pendientes se guardan en la PILA DE DATOS, que
; es lo que hace Forth de verdad --por eso dejar basura en la pila dentro de una
; definicion desordena el control de flujo, y es un clasico--.
; ---------------------------------------------------------------------------

; IF: compila 0BRANCH y deja el hueco del salto.
w_if:
    BEQ   R2, R3, compile_only
    MOVI  R6, d_zbranch
    STORE R6, R16, 0
    ADDI  R16, R16, 4
    STORE R16, R21, 0           ; la direccion del hueco, a la pila
    ADDI  R21, R21, 4
    ADDI  R16, R16, 4           ; y se reserva
    JR    R28

; THEN: rellena el hueco con donde estamos.
w_then:
    BEQ   R2, R3, compile_only
    ADDI  R5, R22, 4
    BLT   R21, R5, ctrl_error
    LOAD  R6, R21, -4
    ADDI  R21, R21, -4
    STORE R16, R6, 0
    JR    R28

; ELSE: cierra la rama verdadera con un salto y abre un hueco nuevo.
w_else:
    BEQ   R2, R3, compile_only
    ADDI  R5, R22, 4
    BLT   R21, R5, ctrl_error
    MOVI  R6, d_branch
    STORE R6, R16, 0
    ADDI  R16, R16, 4
    LOAD  R7, R21, -4           ; el hueco que dejo IF
    STORE R16, R21, -4          ; se sustituye por el hueco de este BRANCH
    ADDI  R16, R16, 4
    STORE R16, R7, 0            ; y el IF salta a partir de aqui
    JR    R28

; BEGIN: no compila nada, solo se acuerda de donde empieza el bucle.
w_begin:
    BEQ   R2, R3, compile_only
    STORE R16, R21, 0
    ADDI  R21, R21, 4
    JR    R28

; UNTIL: vuelve al BEGIN mientras la condicion sea falsa.
w_until:
    BEQ   R2, R3, compile_only
    ADDI  R5, R22, 4
    BLT   R21, R5, ctrl_error
    MOVI  R6, d_zbranch
    STORE R6, R16, 0
    ADDI  R16, R16, 4
    LOAD  R7, R21, -4
    ADDI  R21, R21, -4
    STORE R7, R16, 0
    ADDI  R16, R16, 4
    JR    R28

; AGAIN: bucle sin condicion. Solo se sale con BYE o con un error.
w_again:
    BEQ   R2, R3, compile_only
    ADDI  R5, R22, 4
    BLT   R21, R5, ctrl_error
    MOVI  R6, d_branch
    STORE R6, R16, 0
    ADDI  R16, R16, 4
    LOAD  R7, R21, -4
    ADDI  R21, R21, -4
    STORE R7, R16, 0
    ADDI  R16, R16, 4
    JR    R28

; WHILE: salida del bucle por el medio. Deja su hueco ENCIMA del destino que
; apunto BEGIN, y REPEAT los saca en ese orden.
w_while:
    BEQ   R2, R3, compile_only
    MOVI  R6, d_zbranch
    STORE R6, R16, 0
    ADDI  R16, R16, 4
    STORE R16, R21, 0
    ADDI  R21, R21, 4
    ADDI  R16, R16, 4
    JR    R28

; REPEAT: salta al BEGIN y rellena el hueco del WHILE con la salida.
w_repeat:
    BEQ   R2, R3, compile_only
    ADDI  R5, R22, 8
    BLT   R21, R5, ctrl_error
    LOAD  R6, R21, -4           ; hueco del WHILE
    LOAD  R7, R21, -8           ; destino del BEGIN
    ADDI  R21, R21, -8
    MOVI  R8, d_branch
    STORE R8, R16, 0
    ADDI  R16, R16, 4
    STORE R7, R16, 0
    ADDI  R16, R16, 4
    STORE R16, R6, 0            ; el WHILE sale por aqui
    JR    R28

compile_only:
    MOVI  R4, msg_compile_only
    JAL   R31, print_str
    BRA   abort

ctrl_error:
    MOVI  R4, msg_ctrl
    JAL   R31, print_str
    BRA   abort

; `WORDS` ensena el diccionario, de lo mas nuevo a lo mas viejo. Sirve para ver
; que `:` ha anadido lo que decia.
w_words:
    ADDI  R7, R17, 0
words_loop:
    BEQ   R7, R3, words_done
    LOAD  R4, R7, 4
    JAL   R29, print_name
    MOVI  R4, 0x20
    JAL   R30, emit
    LOAD  R7, R7, 0
    BRA   words_loop
words_done:
    MOVI  R4, 0x0A
    JAL   R30, emit
    JR    R28

; Imprime un nombre empaquetado: hasta cuatro caracteres, del byte bajo al
; alto, parando en el primer cero.
print_name:
    ADDI  R8, R4, 0
    MOVI  R9, 4
pn_name_loop:
    BEQ   R9, R3, pn_name_done
    ANDI  R4, R8, 0x00FF
    BEQ   R4, R3, pn_name_done
    JAL   R30, emit
    SHR   R8, R8, R27
    ADDI  R9, R9, -1
    BRA   pn_name_loop
pn_name_done:
    JR    R29

; Los errores de palabra vuelven al bucle principal, no a quien llamo: la linea
; en curso se descarta entera. Por eso saltan con BRA y no con JR R28.
stack_error:
    MOVI  R4, msg_stack
    JAL   R31, print_str
    BRA   abort

divzero_error:
    MOVI  R4, msg_divzero
    JAL   R31, print_str
    BRA   abort

; ---------------------------------------------------------------------------
; Lexico
; ---------------------------------------------------------------------------

; Avanza R24 sobre espacios y tabuladores.
skip_spaces:
    LOADUB R8, R24, 0
    BEQ   R8, R3, skip_done
    MOVI  R9, 0x20
    BEQ   R8, R9, skip_next
    MOVI  R9, 0x09
    BEQ   R8, R9, skip_next
    JR    R29
skip_next:
    ADDI  R24, R24, 1
    BRA   skip_spaces
skip_done:
    JR    R29

; Lee la palabra que empieza en R24 y la empaqueta en R4; R5 = cuantos
; caracteres tenia. Las minusculas se pasan a mayuscula, asi que `dup` y `DUP`
; son la misma palabra. R6 guarda el inicio, para poder reimprimirla.
read_token:
    ADDI  R6, R24, 0
    MOVI  R4, 0
    MOVI  R5, 0
    MOVI  R12, 0                ; desplazamiento dentro de la palabra
token_loop:
    LOADUB R8, R24, 0
    BEQ   R8, R3, token_done
    MOVI  R9, 0x20
    BEQ   R8, R9, token_done
    MOVI  R9, 0x09
    BEQ   R8, R9, token_done

    ; a mayuscula
    MOVI  R9, 0x61
    BLT   R8, R9, token_keep
    MOVI  R9, 0x7A
    BLT   R9, R8, token_keep
    ADDI  R8, R8, -32
token_keep:
    MOVI  R9, 4
    BGE   R5, R9, token_skip    ; mas de cuatro: no cabe, pero se consume
    SHL   R10, R8, R12
    OR    R4, R4, R10
    ADDI  R12, R12, 8
token_skip:
    ADDI  R5, R5, 1
    ADDI  R24, R24, 1
    BRA   token_loop
token_done:
    ADDI  R25, R6, 0            ; inicio de la palabra, para print_token
    JR    R29

; Reimprime la palabra que acaba de leer read_token, desde R25 hasta R24.
print_token:
    ADDI  R11, R25, 0
pt_loop:
    BGE   R11, R24, pt_done
    LOADUB R4, R11, 0
    JAL   R30, emit
    ADDI  R11, R11, 1
    BRA   pt_loop
pt_done:
    JR    R29

; Intenta leer la palabra en curso como numero decimal con signo.
; Devuelve R4 = valor y R5 = 1 si lo era, 0 si no.
parse_number:
    ADDI  R11, R25, 0
    MOVI  R4, 0
    MOVI  R5, 0
    MOVI  R8, 0                 ; signo
    LOADUB R9, R11, 0
    MOVI  R10, 0x2D             ; '-'
    BNE   R9, R10, num_loop
    MOVI  R8, 1
    ADDI  R11, R11, 1
    BGE   R11, R24, num_fail    ; un '-' suelto no es un numero
num_loop:
    BGE   R11, R24, num_done
    LOADUB R9, R11, 0
    ; A mayuscula, para que en hexadecimal valga tanto `ff` como `FF`.
    MOVI  R10, 0x61
    BLT   R9, R10, nm_upper
    MOVI  R10, 0x7A
    BLT   R10, R9, nm_upper
    ADDI  R9, R9, -32
nm_upper:
    MOVI  R10, 0x30             ; '0'
    BLT   R9, R10, num_fail
    MOVI  R10, 0x39             ; '9'
    BLT   R10, R9, nm_letter
    ADDI  R9, R9, -48
    BRA   nm_digit
nm_letter:
    MOVI  R10, 0x41             ; 'A'
    BLT   R9, R10, num_fail
    MOVI  R10, 0x5A             ; 'Z'
    BLT   R10, R9, num_fail
    ADDI  R9, R9, -55
nm_digit:
    ; Un digito tiene que caber en la base: en decimal, `1A` no es un numero.
    BGE   R9, R0, num_fail
    MUL   R4, R4, R0
    ADD   R4, R4, R9
    ADDI  R11, R11, 1
    MOVI  R5, 1
    BRA   num_loop
num_done:
    BEQ   R5, R3, num_fail
    BEQ   R8, R3, num_ok
    SUB   R4, R3, R4
num_ok:
    JR    R29
num_fail:
    MOVI  R5, 0
    JR    R29

; ---------------------------------------------------------------------------
; Entrada y salida
; ---------------------------------------------------------------------------

; Lee una linea del puerto serie hasta el salto de linea, con eco, y la deja
; terminada en NUL. Vuelve por R31; usa emit por R30.
read_line:
    ADDI  R11, R23, 0
    MOVI  R12, 127              ; hueco util del buffer
    ADD   R12, R23, R12
rl_loop:
    JAL   R30, key              ; R4 = caracter
    MOVI  R9, 0x0D
    BEQ   R4, R9, rl_end        ; el terminal manda CR o LF
    MOVI  R9, 0x0A
    BEQ   R4, R9, rl_end

    ; Retroceso, para poder corregir al escribir.
    MOVI  R9, 0x08
    BEQ   R4, R9, rl_back
    MOVI  R9, 0x7F
    BEQ   R4, R9, rl_back

    BGE   R11, R12, rl_loop     ; buffer lleno: se ignora
    STOREB R4, R11, 0
    ADDI  R11, R11, 1
    JAL   R30, emit             ; eco
    BRA   rl_loop

rl_back:
    BGE   R23, R11, rl_loop     ; nada que borrar
    ADDI  R11, R11, -1
    MOVI  R4, 0x08
    JAL   R30, emit
    MOVI  R4, 0x20
    JAL   R30, emit
    MOVI  R4, 0x08
    JAL   R30, emit
    BRA   rl_loop

rl_end:
    STOREB R3, R11, 0           ; NUL final
    MOVI  R4, 0x0A
    JAL   R30, emit
    JR    R31

; Espera a que llegue un byte y lo devuelve en R4. Vuelve por R30.
;
; El bucle mira rx_count en STATUS antes de leer DATA: leer DATA con la cola
; vacia devuelve cero --no bloquea, no puede bloquear-- y el interprete se
; pondria a procesar ceros a toda velocidad.
key:
    LOAD  R5, R20, 4
    ANDI  R6, R5, 0x00FF
    BEQ   R6, R3, key
    LOAD  R4, R20, 0
    JR    R30

; Manda el byte de R4. Vuelve por R30.
;
; Espera a que haya hueco en la cola de salida. Sin esto, un `.s` con la pila
; llena perderia caracteres en silencio: la cola son 64 bytes y el PC solo los
; recoge cuando sondea.
emit:
    LOAD  R5, R20, 4
    SHR   R6, R5, R27
    ANDI  R6, R6, 0x00FF
    BEQ   R6, R3, emit
    STORE R4, R20, 0
    JR    R30

; `emit` desde el bucle principal, que tiene R29 y R30 libres.
emit_from_main:
    JAL   R30, emit
    JR    R31

; Imprime la cadena terminada en NUL que apunta R4. Vuelve por R31.
print_str:
    ADDI  R7, R4, 0
ps_loop:
    LOADUB R4, R7, 0
    BEQ   R4, R3, ps_done
    JAL   R30, emit
    ADDI  R7, R7, 1
    BRA   ps_loop
ps_done:
    JR    R31

; Lo mismo, pero para quien ya esta usando R31 (las palabras del diccionario).
print_str_inner:
    ADDI  R7, R4, 0
psi_loop:
    LOADUB R4, R7, 0
    BEQ   R4, R3, psi_done
    JAL   R30, emit
    ADDI  R7, R7, 1
    BRA   psi_loop
psi_done:
    JR    R29

; Imprime R4 como decimal con signo. Vuelve por R29; usa emit por R30.
;
; Los digitos salen del reves --dividiendo por diez-- asi que se guardan en un
; buffer y se imprimen al reves. Once bytes bastan para el numero mas largo,
; que es -2147483648.
print_num:
    MOVI  R11, digit_buffer
    MOVI  R12, 0                ; cuantos digitos
    MOVI  R8, 0                 ; negativo?
    BGE   R4, R3, pn_positive
    MOVI  R8, 1
    SUB   R4, R3, R4
pn_positive:
    BNE   R4, R3, pn_loop
    ; El cero no entra en el bucle: no tiene digitos que extraer.
    MOVI  R5, 0x30
    STOREB R5, R11, 0
    MOVI  R12, 1
    BRA   pn_print
pn_loop:
    BEQ   R4, R3, pn_sign
    ADDI  R9, R0, 0             ; la base, que HEX y DECIMAL cambian
    DIV   R10, R4, R9           ; cociente
    MUL   R5, R10, R9
    SUB   R5, R4, R5            ; resto = n - (n/base)*base
    ; Por encima de 9 los digitos son letras.
    MOVI  R7, 10
    BLT   R5, R7, pn_digit
    ADDI  R5, R5, 7
pn_digit:
    ADDI  R5, R5, 48
    ADD   R6, R11, R12
    STOREB R5, R6, 0
    ADDI  R12, R12, 1
    ADDI  R4, R10, 0
    BRA   pn_loop
pn_sign:
    BEQ   R8, R3, pn_print
    MOVI  R4, 0x2D
    JAL   R30, emit
pn_print:
    ADDI  R12, R12, -1
    BLT   R12, R3, pn_done
    ADD   R6, R11, R12
    LOADUB R4, R6, 0
    JAL   R30, emit
    BRA   pn_print
pn_done:
    JR    R29

; ---------------------------------------------------------------------------
; Diccionario: pares (nombre empaquetado, direccion del codigo).
;
; El nombre son hasta cuatro caracteres en mayuscula, little-endian: el primero
; en el byte bajo. Termina en una entrada con nombre cero.
; ---------------------------------------------------------------------------
; Cada entrada son cuatro palabras:
;
;   +0  enlace a la entrada anterior (0 = final de la lista)
;   +4  nombre empaquetado, hasta cuatro caracteres en mayuscula
;   +8  codigo nativo, o cuerpo si es una definicion compilada
;   +12 flags: bit 0 inmediata, bit 1 definicion compilada
;
; Es una lista enlazada y no una tabla porque `:` anade entradas en RAM que
; tienen que quedar DELANTE de estas: asi una redefinicion tapa a la de fabrica.
; Las flags llevan la LONGITUD del nombre en los bits 15:8, ademas de los dos
; bits de abajo. Sin ella, `dropit` encontraria a `DROP`.
d_plus:    .word 0,         0x0000002B, w_plus,    0x0100   ; +
d_minus:   .word d_plus,    0x0000002D, w_minus,   0x0100   ; -
d_star:    .word d_minus,   0x0000002A, w_star,    0x0100   ; *
d_slash:   .word d_star,    0x0000002F, w_slash,   0x0100   ; /
d_dup:     .word d_slash,   0x00505544, w_dup,     0x0300   ; DUP
d_drop:    .word d_dup,     0x504F5244, w_drop,    0x0400   ; DROP
d_swap:    .word d_drop,    0x50415753, w_swap,    0x0400   ; SWAP
d_over:    .word d_swap,    0x5245564F, w_over,    0x0400   ; OVER
d_neg:     .word d_over,    0x0047454E, w_neg,     0x0300   ; NEG
d_dot:     .word d_neg,     0x0000002E, w_dot,     0x0100   ; .
d_dots:    .word d_dot,     0x0000532E, w_dots,    0x0200   ; .S
d_equals:  .word d_dots,    0x0000003D, w_equals,  0x0100   ; =
d_less:    .word d_equals,  0x0000003C, w_less,    0x0100   ; <
d_greater: .word d_less,    0x0000003E, w_greater, 0x0100   ; >
d_fetch:   .word d_greater, 0x00000040, w_fetch,   0x0100   ; @
d_store:   .word d_fetch,   0x00000021, w_store,   0x0100   ; !
d_cr:      .word d_store,   0x00005243, w_cr,      0x0200   ; CR
; WORDS son cinco letras y solo caben cuatro: se busca por "WORD" mas longitud
; 5, y por eso al listarlo sale "WORD". Es el empaquetado asomando.
d_words:   .word d_cr,      0x44524F57, w_words,   0x0500   ; WORDS
d_colon:   .word d_words,   0x0000003A, w_colon,   0x0100   ; :
d_semi:    .word d_colon,   0x0000003B, w_semi,    0x0101   ; ;  INMEDIATA
; Control de flujo. Todas INMEDIATAS: se ejecutan mientras se compila.
d_if:      .word d_semi,    0x00004649, w_if,      0x0201   ; IF
d_else:    .word d_if,      0x45534C45, w_else,    0x0401   ; ELSE
d_then:    .word d_else,    0x4E454854, w_then,    0x0401   ; THEN
d_begin:   .word d_then,    0x49474542, w_begin,   0x0501   ; BEGIN
d_until:   .word d_begin,   0x49544E55, w_until,   0x0501   ; UNTIL
d_while:   .word d_until,   0x4C494857, w_while,   0x0501   ; WHILE
d_repeat:  .word d_while,   0x45504552, w_repeat,  0x0601   ; REPEAT
d_again:   .word d_repeat,  0x49414741, w_again,   0x0501   ; AGAIN
; Palabras definidoras. DOES> NO es inmediata: se compila como una normal.
d_create:  .word d_again,   0x41455243, w_create,  0x0600   ; CREATE
d_comma:   .word d_create,  0x0000002C, w_comma,   0x0100   ; ,
d_allot:   .word d_comma,   0x4F4C4C41, w_allot,   0x0500   ; ALLOT
d_cells:   .word d_allot,   0x4C4C4543, w_cells,   0x0500   ; CELLS
d_does:    .word d_cells,   0x53454F44, w_does,    0x0500   ; DOES>
; Pila
d_rot:     .word d_does,    0x00544F52, w_rot,     0x0300   ; ROT
d_nip:     .word d_rot,     0x0050494E, w_nip,     0x0300   ; NIP
d_tuck:    .word d_nip,     0x4B435554, w_tuck,    0x0400   ; TUCK
d_2dup:    .word d_tuck,    0x50554432, w_twodup,  0x0400   ; 2DUP
d_2drop:   .word d_2dup,    0x4F524432, w_twodrop, 0x0500   ; 2DROP
d_depth:   .word d_2drop,   0x54504544, w_depth,   0x0500   ; DEPTH
d_pick:    .word d_depth,   0x4B434950, w_pick,    0x0400   ; PICK
; Aritmetica y logica
d_mod:     .word d_pick,    0x00444F4D, w_mod,     0x0300   ; MOD
d_abs:     .word d_mod,     0x00534241, w_abs,     0x0300   ; ABS
d_min:     .word d_abs,     0x004E494D, w_min,     0x0300   ; MIN
d_max:     .word d_min,     0x0058414D, w_max,     0x0300   ; MAX
d_1plus:   .word d_max,     0x00002B31, w_oneplus, 0x0200   ; 1+
d_1minus:  .word d_1plus,   0x00002D31, w_oneminus,0x0200   ; 1-
d_and:     .word d_1minus,  0x00444E41, w_and,     0x0300   ; AND
d_or:      .word d_and,     0x0000524F, w_or,      0x0200   ; OR
d_xor:     .word d_or,      0x00524F58, w_xor,     0x0300   ; XOR
d_invert:  .word d_xor,     0x45564E49, w_invert,  0x0600   ; INVERT
d_0eq:     .word d_invert,  0x00003D30, w_zeroeq,  0x0200   ; 0=
d_0less:   .word d_0eq,     0x00003C30, w_zeroless,0x0200   ; 0<
; Texto y base
d_emit:    .word d_0less,   0x54494D45, w_emit,    0x0400   ; EMIT
d_space:   .word d_emit,    0x43415053, w_space,   0x0500   ; SPACE
d_hex:     .word d_space,   0x00584548, w_hex,     0x0300   ; HEX
d_decimal: .word d_hex,     0x49434544, w_decimal, 0x0700   ; DECIMAL
d_dotq:    .word d_decimal, 0x0000222E, w_dotquote,0x0201   ; ."  INMEDIATA
; Salida y recursion
d_exit:    .word d_dotq,    0x54495845, w_exit,    0x0400   ; EXIT
d_recurse: .word d_exit,    0x55434552, w_recurse, 0x0701   ; RECURSE INMEDIATA
d_last:    .word d_recurse, 0x00455942, w_bye,     0x0300   ; BYE

; LIT, BRANCH y 0BRANCH estan FUERA de la lista a proposito: no se pueden
; escribir ni encontrar, solo las coloca el compilador.
d_lit:     .word 0,         0xFFFFFFFF, w_lit,     0
d_branch:  .word 0,         0xFFFFFFFF, w_branch,  0
d_zbranch: .word 0,         0xFFFFFFFF, w_zbranch, 0
d_dotstr:  .word 0,         0xFFFFFFFF, w_dotstr,  0

; ---------------------------------------------------------------------------
; Mensajes
; ---------------------------------------------------------------------------
msg_banner:
    .string "MiniForth\n"
msg_prompt:
    .string "ok> "
msg_unknown:
    .string "? "
msg_stack:
    .string "pila vacia\n"
msg_divzero:
    .string "division por cero\n"
msg_bye:
    .string "adios\n"
msg_compile_only:
    .string "solo dentro de :\n"
msg_ctrl:
    .string "control de flujo descuadrado\n"

digit_buffer:
    .word 0, 0, 0
