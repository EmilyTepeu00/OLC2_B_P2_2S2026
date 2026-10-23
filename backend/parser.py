# --- ANALIZADOR SINTACTICO ---

import ply.yacc as yacc
from ply.lex import LexToken
from backend.lexer import tokens, lexer, escanear_errores_lexicos, encontrar_columna

errores_parseo = []
lineas_nodo = {}
columnas_nodo = {}
_codigo_actual = ''  # para calcular columnas dentro de las reglas de gramatica

inicio = 'programa'


class FlujoTokens:
    # Envuelve al lexer para poder:
    #  - devolverle al parser tokens "inventados" (un ';' o '}' que faltaba) durante la recuperacion de errores
    #  - recordar donde termino el ultimo token real (para reportar la columna del error)
    #  - llevar la cuenta de llaves abiertas (para cerrar las que falten al llegar al fin del archivo)
    def __init__(self, lexer_base):
        self.lexer = lexer_base
        self.pendientes = []
        self.reset()

    def reset(self):
        self.pendientes = []
        self.profundidad = 0       # llaves '{' abiertas sin cerrar
        self.fin_previo = None     # lexpos donde termino el penultimo token real
        self.fin_actual = None     # lexpos donde termino el ultimo token real
        self.ultimo = None         # ultimo token entregado al parser (real o inventado)
        self.inserciones = 0

    def input(self, data):
        self.lexer.input(data)

    # PLY lee estos atributos del lexer cuando usa tracking=True
    @property
    def lineno(self):
        return self.lexer.lineno

    @property
    def lexpos(self):
        return self.lexer.lexpos

    @property
    def lexdata(self):
        return self.lexer.lexdata

    def token(self):
        if self.pendientes:
            tok = self.pendientes.pop(0)
        else:
            tok = self.lexer.token()
            if tok is not None:
                self.fin_previo = self.fin_actual
                self.fin_actual = self.lexer.lexpos
                if tok.type == 'LLAVEIZQ':
                    self.profundidad += 1
                elif tok.type == 'LLAVEDER':
                    self.profundidad -= 1
        self.ultimo = tok
        return tok


flujo = FlujoTokens(lexer)


def _token_inventado(tipo, valor, lexpos):
    tok = LexToken()
    tok.type = tipo
    tok.value = valor
    tok.lexpos = lexpos if lexpos is not None else 0
    tok.lineno = _linea_de_pos(tok.lexpos)
    tok.lexer = flujo.lexer
    return tok


def _linea_de_pos(pos):
    return _codigo_actual.count('\n', 0, pos) + 1


def _registrar(p, nodo, i=1):
    # Guarda la linea y columna del simbolo i de la regla para el nodo (se usan en los mensajes de error)
    try:
        linea = p.lineno(i)
        lexpos = p.lexpos(i)
    except Exception:
        return
    if linea:
        lineas_nodo[id(nodo)] = linea
    if lexpos is not None and _codigo_actual:
        columnas_nodo[id(nodo)] = encontrar_columna(_codigo_actual, lexpos)

precedence = (
    ('left', 'O'),                                              # ||
    ('left', 'Y'),                                              # &&
    ('left', 'IGUAL', 'DIFERENTE'),                             # == !=
    ('left', 'MAYOR', 'MAYORIGUAL', 'MENOR', 'MENORIGUAL'),     # > >= < <=
    ('left', 'SUMA', 'RESTA'),                                  # + -
    ('left', 'MULT', 'DIV', 'RESTO'),                           # * / %
    ('right', 'NO', 'UMINUS'),                                  # ! y el "-" unario
    ('left', 'PUNTO', 'CORCHIZQ'),                              # .campo, .metodo(), [indice]
)

def p_programa(p):
    """programa : lista_declaraciones"""
    p[0] = ('programa', p[1])

def p_lista_declaraciones(p):
    """lista_declaraciones : declaracion
                           | lista_declaraciones declaracion"""
    if len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[2]]

def p_declaracion(p):
    """declaracion : funcion
                   | struct_decl"""
    p[0] = p[1]

def p_funcion(p):
    """funcion : FN ID PARENIZQ lista_parametros PARENDER FLECHA tipo LLAVEIZQ lista_sentencias LLAVEDER
               | FN ID PARENIZQ lista_parametros PARENDER LLAVEIZQ lista_sentencias LLAVEDER"""
    if len(p) == 11:
        p[0] = ('funcion', p[2], p[4], p[7], p[9])
    else:
        p[0] = ('funcion', p[2], p[4], None, p[7])
    lineas_nodo[id(p[0])] = p.lineno(1)

def p_lista_parametros(p):
    """lista_parametros : 
                        | parametro
                        | lista_parametros COMA parametro"""
    if len(p) == 1:
        p[0] = []
    elif len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[3]]

def p_parametro(p):
    "parametro : ID DOSPUNTOS tipo"
    p[0] = (p[1], p[3])

def p_tipo(p):
    """tipo : I32
            | F64
            | BOOL
            | STRING_TYPE
            | CHAR
            | CORCHIZQ tipo PUNTOCOMA INTEGER CORCHDER
            | ID"""
    if len(p) == 6:  # [T; N
        p[0] = ('array', p[2], p[4])
    else:
        p[0] = p[1]

def p_lista_sentencias(p):
    """lista_sentencias : 
                        | sentencia
                        | lista_sentencias sentencia"""
    if len(p) == 1:
        p[0] = []
    elif len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[2]]

def p_sentencia(p):
    """sentencia : declaracion_let
                 | asignacion
                 | sentencia_if
                 | sentencia_while
                 | sentencia_loop
                 | sentencia_match
                 | sentencia_return
                 | sentencia_break
                 | sentencia_continue
                 | sentencia_bloque
                 | expresion PUNTOCOMA"""
    p[0] = p[1]
    if isinstance(p[0], tuple) and id(p[0]) not in lineas_nodo:
        _registrar(p, p[0], 1)

def p_sentencia_bloque(p):
    "sentencia_bloque : LLAVEIZQ lista_sentencias LLAVEDER"
    # Crea su propio scope
    p[0] = ('bloque', p[2])

def p_declaracion_let_tipada_con_valor(p):
    "declaracion_let : LET ID DOSPUNTOS tipo ASIGN valor PUNTOCOMA"
    p[0] = ('let', p[2], p[4], p[6], False)

def p_declaracion_let_inferida_con_valor(p):
    "declaracion_let : LET ID ASIGN valor PUNTOCOMA"
    p[0] = ('let', p[2], None, p[4], False)

def p_declaracion_let_mut_tipada_con_valor(p):
    "declaracion_let : LET MUT ID DOSPUNTOS tipo ASIGN valor PUNTOCOMA"
    p[0] = ('let', p[3], p[5], p[7], True)

def p_declaracion_let_mut_inferida_con_valor(p):
    "declaracion_let : LET MUT ID ASIGN valor PUNTOCOMA"
    p[0] = ('let', p[3], None, p[5], True)

def p_declaracion_let_tipada_sin_valor(p):
    "declaracion_let : LET ID DOSPUNTOS tipo PUNTOCOMA"
    p[0] = ('let', p[2], p[4], None, False)

def p_declaracion_let_mut_tipada_sin_valor(p):
    "declaracion_let : LET MUT ID DOSPUNTOS tipo PUNTOCOMA"
    p[0] = ('let', p[3], p[5], None, True)

def p_asignacion(p):
    """asignacion : ID ASIGN valor PUNTOCOMA
                  | ID MASIGUAL expresion PUNTOCOMA
                  | ID MENOSIGUAL expresion PUNTOCOMA
                  | ID MULTIGUAL expresion PUNTOCOMA
                  | ID DIVIGUAL expresion PUNTOCOMA
                  | ID RESTOIGUAL expresion PUNTOCOMA"""
    tipo_token = p.slice[2].type
    if tipo_token == 'ASIGN':
        p[0] = ('asignar', p[1], p[3])
    else:
        # x += e  se traduce a  x = x + e  (igual con -=, *=, /=, %=)
        operador = {
            'MASIGUAL': '+', 'MENOSIGUAL': '-',
            'MULTIGUAL': '*', 'DIVIGUAL': '/', 'RESTOIGUAL': '%',
        }[tipo_token]
        p[0] = ('asignar', p[1], ('binop', operador, ('var', p[1]), p[3]))

def p_asignacion_indice(p):
    """asignacion : expresion CORCHIZQ expresion CORCHDER ASIGN valor PUNTOCOMA
                  | expresion CORCHIZQ expresion CORCHDER MASIGUAL expresion PUNTOCOMA
                  | expresion CORCHIZQ expresion CORCHDER MENOSIGUAL expresion PUNTOCOMA
                  | expresion CORCHIZQ expresion CORCHDER MULTIGUAL expresion PUNTOCOMA
                  | expresion CORCHIZQ expresion CORCHDER DIVIGUAL expresion PUNTOCOMA
                  | expresion CORCHIZQ expresion CORCHDER RESTOIGUAL expresion PUNTOCOMA"""
    # arreglo[indice] = valor;  (para swaps en sort_array())
    tipo_token = p.slice[5].type
    base, indice = p[1], p[3]
    if tipo_token == 'ASIGN':
        p[0] = ('asignar_indice', base, indice, p[6])
    else:
        operador = {
            'MASIGUAL': '+', 'MENOSIGUAL': '-',
            'MULTIGUAL': '*', 'DIVIGUAL': '/', 'RESTOIGUAL': '%',
        }[tipo_token]
        actual = ('array_access', base, indice)
        p[0] = ('asignar_indice', base, indice, ('binop', operador, actual, p[6]))

def p_asignacion_campo(p):
    """asignacion : expresion PUNTO ID ASIGN valor PUNTOCOMA
                  | expresion PUNTO ID MASIGUAL expresion PUNTOCOMA
                  | expresion PUNTO ID MENOSIGUAL expresion PUNTOCOMA
                  | expresion PUNTO ID MULTIGUAL expresion PUNTOCOMA
                  | expresion PUNTO ID DIVIGUAL expresion PUNTOCOMA
                  | expresion PUNTO ID RESTOIGUAL expresion PUNTOCOMA"""
    # struct.campo = valor;
    tipo_token = p.slice[4].type
    base, campo = p[1], p[3]
    if tipo_token == 'ASIGN':
        p[0] = ('asignar_campo', base, campo, p[5])
    else:
        operador = {
            'MASIGUAL': '+', 'MENOSIGUAL': '-',
            'MULTIGUAL': '*', 'DIVIGUAL': '/', 'RESTOIGUAL': '%',
        }[tipo_token]
        actual = ('field_access', base, campo)
        p[0] = ('asignar_campo', base, campo, ('binop', operador, actual, p[5]))

def p_sentencia_if(p):
    """sentencia_if : IF expresion LLAVEIZQ lista_sentencias LLAVEDER
                    | IF expresion LLAVEIZQ lista_sentencias LLAVEDER ELSE LLAVEIZQ lista_sentencias LLAVEDER
                    | IF expresion LLAVEIZQ lista_sentencias LLAVEDER ELSE sentencia_if"""
    condicion = p[2]
    if len(p) == 6:
        p[0] = ('if', condicion, p[4], None)
    elif len(p) == 10:
        p[0] = ('if', condicion, p[4], p[8])
    else:
        p[0] = ('if', condicion, p[4], p[7])

def p_sentencia_while(p):
    "sentencia_while : WHILE expresion LLAVEIZQ lista_sentencias LLAVEDER"
    p[0] = ('while', p[2], p[4])

def p_sentencia_loop(p):
    """sentencia_loop : LOOP LLAVEIZQ lista_sentencias LLAVEDER
                      | LABEL DOSPUNTOS LOOP LLAVEIZQ lista_sentencias LLAVEDER"""
    if len(p) == 5:
        p[0] = ('loop', None, p[3])
    else:
        p[0] = ('loop', p[1], p[5])

def p_sentencia_match(p):
    "sentencia_match : MATCH expresion LLAVEIZQ casos_match LLAVEDER"
    p[0] = ('match', p[2], p[4])

def p_casos_match(p):
    """casos_match : caso_match
                   | casos_match caso_match"""
    if len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[2]]

def p_caso_match(p):
    """caso_match : patron_match FLECHA_GORDA expresion COMA
                  | patron_match FLECHA_GORDA expresion
                  | patron_match FLECHA_GORDA LLAVEIZQ lista_sentencias LLAVEDER COMA
                  | patron_match FLECHA_GORDA LLAVEIZQ lista_sentencias LLAVEDER"""
    # Se soportan las dos formas: "patron => expresion," y "patron => { sentencias }"
    # La coma es opcional en el ultimo caso y despues de un bloque (igual que en Rust)
    patron = p[1]
    if p.slice[3].type == 'LLAVEIZQ':
        cuerpo = p[4]
    else:
        cuerpo = [p[3]]
    p[0] = ('caso', patron, cuerpo)

def p_patron_match(p):
    """patron_match : INTEGER
                    | RESTA INTEGER
                    | CHAR_LITERAL
                    | TRUE
                    | FALSE
                    | ID"""
    # El patron queda como: 'default' (comodin "_"), un entero, ('char', c) o ('bool', v)
    tipo_token = p.slice[1].type
    if tipo_token == 'INTEGER':
        p[0] = p[1]
    elif tipo_token == 'RESTA':
        p[0] = -p[2]
    elif tipo_token == 'CHAR_LITERAL':
        p[0] = ('char', p[1])
    elif tipo_token in ('TRUE', 'FALSE'):
        p[0] = ('bool', p[1])
    elif p[1] == '_':
        # "_" se tokeniza como ID normal (empieza con "_")
        p[0] = 'default'
    else:
        p[0] = ('var', p[1])

def p_sentencia_return(p):
    """sentencia_return : RETURN valor PUNTOCOMA
                        | RETURN PUNTOCOMA"""
    if len(p) == 4:
        p[0] = ('return', p[2])
    else:
        p[0] = ('return', None)

def p_sentencia_break(p):
    """sentencia_break : BREAK PUNTOCOMA
                       | BREAK LABEL PUNTOCOMA"""
    if len(p) == 3:
        p[0] = ('break', None)
    else:
        p[0] = ('break', p[2])

def p_sentencia_continue(p):
    """sentencia_continue : CONTINUE PUNTOCOMA
                          | CONTINUE LABEL PUNTOCOMA"""
    if len(p) == 3:
        p[0] = ('continue', None)
    else:
        p[0] = ('continue', p[2])

def p_expresion_binaria(p):
    """expresion : expresion SUMA expresion
                 | expresion RESTA expresion
                 | expresion MULT expresion
                 | expresion DIV expresion
                 | expresion RESTO expresion
                 | expresion IGUAL expresion
                 | expresion DIFERENTE expresion
                 | expresion MAYOR expresion
                 | expresion MAYORIGUAL expresion
                 | expresion MENOR expresion
                 | expresion MENORIGUAL expresion
                 | expresion Y expresion
                 | expresion O expresion"""
    p[0] = ('binop', p[2], p[1], p[3])
    _registrar(p, p[0], 2)  # la columna del error es la del operador

def p_expresion_unaria(p):
    """expresion : NO expresion
                 | RESTA expresion %prec UMINUS"""
    p[0] = ('unop', p[1], p[2])
    _registrar(p, p[0], 1)

def p_expresion_literal(p):
    """expresion : INTEGER
                 | FLOAT
                 | STRING
                 | CHAR_LITERAL
                 | TRUE
                 | FALSE"""
    tipo_token = p.slice[1].type
    if tipo_token in ('TRUE', 'FALSE'):
        p[0] = ('bool', p[1])
    elif tipo_token == 'STRING':
        p[0] = ('string', p[1])
    elif tipo_token == 'CHAR_LITERAL':
        p[0] = ('char', p[1])
    else:
        p[0] = ('literal', p[1])
    _registrar(p, p[0], 1)

def p_valor(p):
    """valor : expresion
             | ID LLAVEIZQ valores_struct LLAVEDER"""
    if len(p) == 2:
        p[0] = p[1]
    else:
        p[0] = ('struct_init', p[1], p[3])

def p_expresion_variable(p):
    "expresion : ID"
    p[0] = ('var', p[1])
    _registrar(p, p[0], 1)

def p_expresion_llamada(p):
    """expresion : ID PARENIZQ lista_argumentos PARENDER
                 | PRINTLN NO PARENIZQ lista_argumentos PARENDER"""
    if p.slice[1].type == 'PRINTLN':
        p[0] = ('llamada', 'println', p[4])
    else:
        p[0] = ('llamada', p[1], p[3])
    _registrar(p, p[0], 1)

def p_expresion_llamada_metodo(p):
    """expresion : expresion PUNTO ID PARENIZQ lista_argumentos PARENDER"""
    # variable.metodo(args) se traduce a llamada(metodo, [variable] + args)
    p[0] = ('llamada', p[3], [p[1]] + p[5])
    _registrar(p, p[0], 1)

def p_expresion_string_estatico(p):
    """expresion : STRING_TYPE DOSDOSPUNTOS ID PARENIZQ lista_argumentos PARENDER"""
    # String::from("texto")  y  String::new()
    if p[3] == 'from':
        p[0] = ('string_from', p[5][0] if p[5] else ('string', ''))
    else:  # String::new()
        p[0] = ('string', '')
    _registrar(p, p[0], 1)

def p_lista_argumentos(p):
    """lista_argumentos : 
                        | valor
                        | lista_argumentos COMA valor"""
    if len(p) == 1:
        p[0] = []
    elif len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[3]]

def p_expresion_agrupada(p):
    "expresion : PARENIZQ expresion PARENDER"
    p[0] = p[2]

# --- ARREGLOS ---

def p_expresion_array_literal(p):
    """expresion : CORCHIZQ lista_elementos CORCHDER"""
    p[0] = ('array_literal', p[2])
    _registrar(p, p[0], 1)

def p_expresion_array_repetido(p):
    """expresion : CORCHIZQ expresion PUNTOCOMA INTEGER CORCHDER"""
    p[0] = ('array_repeat', p[2], p[4])

def p_lista_elementos(p):
    """lista_elementos : 
                      | valor
                      | lista_elementos COMA valor"""
    if len(p) == 1:
        p[0] = []
    elif len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[3]]

# --- ARRAYS ---

def p_expresion_array_access(p):
    """expresion : expresion CORCHIZQ expresion CORCHDER"""
    p[0] = ('array_access', p[1], p[3])
    _registrar(p, p[0], 1)  # columna donde empieza el acceso: numeros[5] -> la de "numeros"

def p_expresion_array_slice(p):
    """expresion : AMPERSAND expresion CORCHIZQ expresion RANGO expresion CORCHDER"""
    p[0] = ('array_slice', p[2], p[4], p[6])
    _registrar(p, p[0], 1)

# --- STRUCTS ---

def p_struct_decl(p):
    """struct_decl : STRUCT ID LLAVEIZQ campos_struct LLAVEDER"""
    p[0] = ('struct', p[2], p[4])
    lineas_nodo[id(p[0])] = p.lineno(1)

def p_campos_struct(p):
    """campos_struct : campo_struct
                     | campos_struct campo_struct"""
    if len(p) == 2:
        p[0] = [p[1]]
    else:
        p[0] = p[1] + [p[2]]

def p_campo_struct(p):
    """campo_struct : ID DOSPUNTOS tipo COMA
                     | ID DOSPUNTOS tipo"""
    # La coma en el ultimo campo es opcional
    p[0] = (p[1], p[3])

def p_valores_struct(p):
    """valores_struct : valor_struct
                      | valores_struct COMA valor_struct
                      | valores_struct COMA"""
    if len(p) == 2:
        p[0] = [p[1]]
    elif len(p) == 4:
        p[0] = p[1] + [p[3]]
    else:
        p[0] = p[1]

def p_valor_struct(p):
    """valor_struct : ID DOSPUNTOS valor"""
    p[0] = (p[1], p[3])

def p_expresion_field_access(p):
    """expresion : expresion PUNTO ID"""
    p[0] = ('field_access', p[1], p[3])

def p_sentencia_error(p):
    """sentencia : error PUNTOCOMA
                  | error LLAVEDER"""
    # Recuperacion de errores sintacticos si algo en una sentencia no calza con la gramatica
    # YACC descarta tokens hasta el siguiente ';' o '}' y sigue parseando el resto dela rchivo desde ahi en vez de dat errror
    p[0] = ('error_stmt',)

MAX_INSERCIONES = 200  # tope de tokens inventados para que la recuperacion nunca se cicle


def _agregar_error_sintactico(pos, mensaje):
    # pos = lexpos justo despues del ultimo token valido; el error se reporta ahi (como en el enunciado)
    if pos is None:
        linea, columna = 0, 0
    else:
        linea = _linea_de_pos(pos)
        columna = encontrar_columna(_codigo_actual, pos)
    errores_parseo.append({
        'tipo': 'Sintactico',
        'linea': linea,
        'columna': columna,
        'mensaje': mensaje,
    })


def _fin_token_previo(p):
    # Posicion justo despues del ultimo token real antes del token del error
    if flujo.fin_previo is not None and flujo.fin_previo <= p.lexpos:
        return flujo.fin_previo
    # Respaldo: buscar hacia atras saltando espacios
    pos = p.lexpos - 1
    while pos >= 0 and _codigo_actual[pos] in ' \t\r\n':
        pos -= 1
    return pos + 1 if pos >= 0 else p.lexpos


def p_error(p):
    acciones = parser.action.get(getattr(parser, 'state', None), {})

    if p is None:
        # Fin de archivo con llaves sin cerrar: se reporta una vez y se "cierran" todas para que el AST quede completo
        if flujo.profundidad > 0 and 'LLAVEDER' in acciones and flujo.inserciones < MAX_INSERCIONES:
            _agregar_error_sintactico(flujo.fin_actual, "Se esperaba '}'.")
            cantidad = flujo.profundidad
            flujo.profundidad = 0
            flujo.inserciones += cantidad
            tokens_cierre = [_token_inventado('LLAVEDER', '}', flujo.fin_actual) for _ in range(cantidad)]
            flujo.pendientes = tokens_cierre[1:] + flujo.pendientes
            parser.errok()
            return tokens_cierre[0]
        _agregar_error_sintactico(flujo.fin_actual, 'Fin de archivo inesperado.')
        return None

    fin_previo = _fin_token_previo(p)

    # Falta de ';': el token del error empieza en una linea nueva y en este punto un ';' era valido
    # Se inventa el ';' y se le devuelve el token original al parser para no perder la siguiente sentencia
    ultimo_fue_puntocoma = flujo.ultimo is not None and flujo.ultimo is not p and flujo.ultimo.type == 'PUNTOCOMA'
    if ('PUNTOCOMA' in acciones and p.type != 'PUNTOCOMA'
            and _linea_de_pos(p.lexpos) > _linea_de_pos(max(fin_previo - 1, 0))
            and not ultimo_fue_puntocoma
            and flujo.inserciones < MAX_INSERCIONES):
        _agregar_error_sintactico(fin_previo, "Se esperaba ';'.")
        flujo.inserciones += 1
        flujo.pendientes.insert(0, p)
        parser.errok()
        return _token_inventado('PUNTOCOMA', ';', fin_previo)

    # Falta de ')' o ']' antes de '{' o ';' (println!("x" ;  /  if (a { ...)
    for esperado, simbolo in (('PARENDER', ')'), ('CORCHDER', ']')):
        if esperado in acciones and p.type in ('PUNTOCOMA', 'LLAVEIZQ') and flujo.inserciones < MAX_INSERCIONES:
            _agregar_error_sintactico(fin_previo, f"Se esperaba '{simbolo}'.")
            flujo.inserciones += 1
            flujo.pendientes.insert(0, p)
            parser.errok()
            return _token_inventado(esperado, simbolo, fin_previo)

    valor = p.value if p.type != 'STRING' else f'"{p.value}"'
    _agregar_error_sintactico(p.lexpos, f"Token inesperado '{valor}'.")


parser = yacc.yacc()

def parsear(codigo):
    global errores_parseo, lineas_nodo, columnas_nodo, _codigo_actual
    errores_parseo = []
    lineas_nodo = {}
    columnas_nodo = {}
    _codigo_actual = codigo
    # Ver que se detecten todos los errores lexicos del archivo
    errores_lex = escanear_errores_lexicos(codigo)
    lexer.lineno = 1
    flujo.reset()
    resultado = parser.parse(codigo, lexer=flujo, tracking=True)
    return resultado, errores_parseo, errores_lex, lineas_nodo, columnas_nodo