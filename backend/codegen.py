# --- GENERADOR DE CODIGO ARM64 (AArch64) ---
# Recorre el mismo AST que ya usa interpreter.py, pero en vez de ejecutar cada nodo, emite las instrucciones de ensamblador equivalentes

SYSCALL_WRITE = 64
SYSCALL_EXIT = 93

TAMANO_SLOT = 16  # bytes reservados por variable (simple sin empacar)


class GeneradorCodigo:
    def __init__(self):
        self.texto = []     # lineas que van dentro de .section .text
        self.datos = []     # lineas que van dentro de .section .data
        self.errores = []
        self._contador_etiquetas = 0
        self._usa_imprimir_entero = False
        self._offsets_por_nodo = {}     # id(nodo 'let') -> offset unico en el stack frame
        self._longitudes_por_nodo = {}  # id(nodo 'let') -> cantidad de elementos, solo arreglos

    def nueva_etiqueta(self, prefijo='L'):
        self._contador_etiquetas += 1
        return f'.{prefijo}{self._contador_etiquetas}'

    def generar(self, ast):
        """Punto de entrada. Devuelve (codigo_asm: str | None, errores: list)"""
        self.texto = []
        self.datos = []
        self.errores = []
        self._usa_imprimir_entero = False
        self._offsets_por_nodo = {}
        self._longitudes_por_nodo = {}

        programa = ast
        funciones = [d for d in programa[1] if d[0] == 'funcion']
        nombres_funciones = {f[1] for f in funciones}

        if 'main' not in nombres_funciones:
            self.errores.append({
                'tipo': 'Semantico',
                'linea': 0,
                'mensaje': 'No se encontro la funcion main',
            })
            return None, self.errores

        for funcion in funciones:
            self._generar_funcion(funcion)

        return self._ensamblar_archivo_final(), self.errores

    # Ensamblado final del archivo .s
    def _ensamblar_archivo_final(self):
        lineas = []

        lineas.append('.section .data')
        lineas.append('    .align 3')
        if self._usa_imprimir_entero:
            lineas.append('buffer_entero: .skip 24')
            lineas.append('buffer_entero_fin:')
            lineas.append('salto_de_linea: .ascii "\\n"')
        if self.datos:
            lineas.extend(self.datos)
        lineas.append('')

        lineas.append('.section .text')
        lineas.append('.global _start')
        lineas.append('')
        lineas.append('_start:')
        lineas.append('    bl main')
        lineas.append('    mov x0, #0')
        lineas.append(f'    mov x8, #{SYSCALL_EXIT}')
        lineas.append('    svc #0')
        lineas.append('')
        lineas.extend(self.texto)

        if self._usa_imprimir_entero:
            lineas.append(self._rutina_imprimir_entero())

        lineas.append('')

        return '\n'.join(lineas)

    def _rutina_imprimir_entero(self):
        # Entrada: x0 = valor entero (con signo) a imprimir
        # Convierte a decimal ASCII en buffer_entero (construyendo del final al principio) y lo escribe a stdout + '\n'
        return '\n'.join([
            'imprimir_entero:',
            '    stp x29, x30, [sp, -32]!',
            '    mov x29, sp',
            '    stp x19, x20, [sp, 16]',
            '',
            '    mov x19, x0',                  # x19 = valor original (para el signo)
            '    mov x9, x0',                   # x9  = valor de trabajo
            '    adr x10, buffer_entero_fin',   # x10 = cursor, se arranca al final
            '    mov x11, #10',
            '',
            '    cbnz x9, .Limprimir_no_es_cero',
            "    mov w12, #'0'",
            '    strb w12, [x10, #-1]!',
            '    b .Limprimir_fin_digitos',
            '',
            '.Limprimir_no_es_cero:',
            '    cmp x9, #0',
            '    bge .Limprimir_loop',
            '    neg x9, x9',
            '',
            '.Limprimir_loop:',
            '    cbz x9, .Limprimir_fin_digitos',
            '    udiv x12, x9, x11',
            '    msub x13, x12, x11, x9',
            "    add x13, x13, #'0'",
            '    strb w13, [x10, #-1]!',
            '    mov x9, x12',
            '    b .Limprimir_loop',
            '',
            '.Limprimir_fin_digitos:',
            '    cmp x19, #0',
            '    bge .Limprimir_calcular_len',
            "    mov w12, #'-'",
            '    strb w12, [x10, #-1]!',
            '',
            '.Limprimir_calcular_len:',
            '    adr x14, buffer_entero_fin',
            '    sub x2, x14, x10',
            '    mov x1, x10',
            '    mov x0, #1',
            f'    mov x8, #{SYSCALL_WRITE}',
            '    svc #0',
            '',
            '    adr x1, salto_de_linea',
            '    mov x2, #1',
            '    mov x0, #1',
            f'    mov x8, #{SYSCALL_WRITE}',
            '    svc #0',
            '',
            '    ldp x19, x20, [sp, 16]',
            '    ldp x29, x30, [sp], 32',
            '    ret',
        ])

    # --- FUNCIONES ---

    REGISTROS_PARAMETRO = ['x0', 'x1', 'x2', 'x3', 'x4', 'x5', 'x6', 'x7']

    def _generar_funcion(self, nodo):
        # nodo = ('funcion', nombre, parametros, tipo_retorno, cuerpo)
        nombre = nodo[1]
        parametros = nodo[2]
        cuerpo = nodo[4]

        self.texto.append(f'{nombre}:')
        # Prologo: guardamos frame pointer (x29) y link register (x30)
        self.texto.append('    stp x29, x30, [sp, -16]!')
        self.texto.append('    mov x29, sp')

        espacio = self._reservar_variables(cuerpo, parametros)
        self._ajustar_sp('sub', espacio)

        contexto = {'scopes': [{}], 'bucles': [], 'etiqueta_fin_funcion': self.nueva_etiqueta('fin_funcion')}

        # Los primeros 8 parametros llegan en x0-x7 y se copian a su slot en el stack antes de generar el cuerpo 
        # para que el resto del codigo lo trate igual que cualquier otra variable
        for i, parametro in enumerate(parametros):
            offset = self._offsets_por_nodo[id(parametro)]
            contexto['scopes'][0][parametro[0]] = {'offset': offset, 'longitud': None}
            if i < len(self.REGISTROS_PARAMETRO):
                self._guardar_variable(self.REGISTROS_PARAMETRO[i], offset)
            else:
                self.texto.append(f'    # parametro "{parametro[0]}": mas de 8 parametros no soportado')

        for sentencia in cuerpo:
            self._generar_sentencia(sentencia, contexto)

        self.texto.append(f'{contexto["etiqueta_fin_funcion"]}:')
        self._ajustar_sp('add', espacio)
        # Epilogo: restauramos y retornamos
        self.texto.append('    ldp x29, x30, [sp], 16')
        self.texto.append('    ret')
        self.texto.append('')

    def _reservar_variables(self, cuerpo, parametros=()):
        # Cada parametro y cada 'let' del cuerpo recibe su propio slot, identificado por el nodo
        # Asi dos variables con el mismo nombre en bloques distintos nunca comparten memoria
        offset = [0]
        for parametro in parametros:
            offset[0] += TAMANO_SLOT
            self._offsets_por_nodo[id(parametro)] = offset[0]
        self._recolectar_lets(cuerpo, offset)
        return offset[0]

    def _longitud_arreglo_1d(self, valor):
        # Longitud si 'valor' es un arreglo unidimensional (literal o [v; N])
        # None si no es arreglo, o si es multidimensional
        if valor is None:
            return None
        if valor[0] == 'array_literal':
            elementos = valor[1]
            if elementos and elementos[0][0] in ('array_literal', 'array_repeat'):
                return None
            return len(elementos)
        if valor[0] == 'array_repeat':
            if valor[1][0] in ('array_literal', 'array_repeat'):
                return None
            return valor[2]
        return None

    def _recolectar_lets(self, sentencias, offset):
        for sentencia in sentencias:
            tipo = sentencia[0]
            if tipo == 'let':
                longitud = self._longitud_arreglo_1d(sentencia[3])
                if longitud is not None:
                    offset_elem0 = offset[0] + 8
                    offset[0] += longitud * 8
                    self._offsets_por_nodo[id(sentencia)] = offset_elem0
                    self._longitudes_por_nodo[id(sentencia)] = longitud
                else:
                    offset[0] += TAMANO_SLOT
                    self._offsets_por_nodo[id(sentencia)] = offset[0]
            elif tipo == 'if':
                self._recolectar_lets(sentencia[2], offset)
                cuerpo_else = sentencia[3]
                if cuerpo_else is not None:
                    if cuerpo_else[0] == 'if':
                        self._recolectar_lets([cuerpo_else], offset)
                    else:
                        self._recolectar_lets(cuerpo_else, offset)
            elif tipo == 'while':
                self._recolectar_lets(sentencia[2], offset)
            elif tipo == 'loop':
                self._recolectar_lets(sentencia[2], offset)

    # --- ACCESO A VARIABLES Y STACK ---
    # ldr/str con offset negativo respecto a x29 solo admite hasta -256, para variables mas lejanas se calcula la direccion en x16

    def _direccion_variable(self, offset):
        if offset <= 255:
            return f'[x29, #-{offset}]'
        self.texto.append(f'    mov x16, #{offset}')
        self.texto.append('    sub x16, x29, x16')
        return '[x16]'

    def _cargar_variable(self, registro, offset):
        direccion = self._direccion_variable(offset)
        self.texto.append(f'    ldr {registro}, {direccion}')

    def _guardar_variable(self, registro, offset):
        direccion = self._direccion_variable(offset)
        self.texto.append(f'    str {registro}, {direccion}')

    def _ajustar_sp(self, operacion, bytes_):
        # 'sub' (reservar) o 'add' (liberar), el inmediato de add/sub llega hasta 4095, por encima se usa un registro
        if bytes_ <= 0:
            return
        if bytes_ <= 4095:
            self.texto.append(f'    {operacion} sp, sp, #{bytes_}')
        else:
            self.texto.append(f'    mov x16, #{bytes_}')
            self.texto.append(f'    {operacion} sp, sp, x16')

    # --- SCOPES ---

    def _abrir_scope(self, contexto):
        contexto['scopes'].append({})

    def _cerrar_scope(self, contexto):
        contexto['scopes'].pop()

    def _declarar_variable(self, nodo_let, contexto):
        offset = self._offsets_por_nodo[id(nodo_let)]
        longitud = self._longitudes_por_nodo.get(id(nodo_let))
        contexto['scopes'][-1][nodo_let[1]] = {'offset': offset, 'longitud': longitud}
        return offset

    def _buscar_variable(self, nombre, contexto):
        # Del bloque mas interno hacia el mas externo
        for scope in reversed(contexto['scopes']):
            if nombre in scope:
                return scope[nombre]
        raise KeyError(f'variable "{nombre}" sin declarar en el codegen')

    # --- SENTENCIAS ---

    def _generar_sentencia(self, sentencia, contexto):
        tipo = sentencia[0]

        if tipo == 'let':
            self._generar_let(sentencia, contexto)
        elif tipo == 'asignar':
            self._generar_asignar(sentencia, contexto)
        elif tipo == 'llamada':
            self._generar_expresion(sentencia, contexto)
        elif tipo == 'if':
            self._generar_if(sentencia, contexto)
        elif tipo == 'while':
            self._generar_while(sentencia, contexto)
        elif tipo == 'loop':
            self._generar_loop(sentencia, contexto)
        elif tipo == 'break':
            self._generar_break(sentencia, contexto)
        elif tipo == 'continue':
            self._generar_continue(sentencia, contexto)
        elif tipo == 'match':
            self._generar_match(sentencia, contexto)
        elif tipo == 'return':
            self._generar_return(sentencia, contexto)
        elif tipo == 'asignar_indice':
            self._generar_asignar_indice(sentencia, contexto)
        else:
            self.texto.append(f'    # sentencia "{tipo}"')

    def _generar_if(self, nodo, contexto):
        # nodo = ('if', condicion, cuerpo_then, cuerpo_else), cuerpo_else puede ser: None una lista de sentencias o un nodo ('if', ...) suelto
        condicion = nodo[1]
        cuerpo_then = nodo[2]
        cuerpo_else = nodo[3]

        etiqueta_else = self.nueva_etiqueta('if_else')
        etiqueta_fin = self.nueva_etiqueta('if_fin')

        self._generar_expresion(condicion, contexto)
        self.texto.append('    cmp x0, #0')
        self.texto.append(f'    beq {etiqueta_else}')
        self._abrir_scope(contexto)
        for sent in cuerpo_then:
            self._generar_sentencia(sent, contexto)
        self._cerrar_scope(contexto)
        self.texto.append(f'    b {etiqueta_fin}')
        self.texto.append(f'{etiqueta_else}:')
        if cuerpo_else is not None:
            if cuerpo_else[0] == 'if':
                self._generar_if(cuerpo_else, contexto)
            else:
                self._abrir_scope(contexto)
                for sent in cuerpo_else:
                    self._generar_sentencia(sent, contexto)
                self._cerrar_scope(contexto)
        self.texto.append(f'{etiqueta_fin}:')

    def _generar_match(self, nodo, contexto):
        # nodo = ('match', expresion, [('caso', patron, cuerpo), ...]) patron es un entero y el string 'default' para el comodin "_" cuerpo es una lista de sentencias 
        expresion = nodo[1]
        casos = nodo[2]
        etiqueta_fin = self.nueva_etiqueta('match_fin')

        self._generar_expresion(expresion, contexto)
        self.texto.append('    str x0, [sp, -16]!')

        for caso in casos:
            patron = caso[1]
            cuerpo = caso[2]
            etiqueta_siguiente = self.nueva_etiqueta('match_caso')

            if patron != 'default':
                self.texto.append('    ldr x0, [sp]')
                self.texto.append(f'    cmp x0, #{patron}')
                self.texto.append(f'    bne {etiqueta_siguiente}')

            self.texto.append('    add sp, sp, #16')
            self._abrir_scope(contexto)
            for sent in cuerpo:
                self._generar_sentencia(sent, contexto)
            self._cerrar_scope(contexto)
            self.texto.append(f'    b {etiqueta_fin}')
            self.texto.append(f'{etiqueta_siguiente}:')

        # Ningun caso coincidio (no habia comodin): liberar el valor guardado
        self.texto.append('    add sp, sp, #16')
        self.texto.append(f'{etiqueta_fin}:')

    # --- BUCLES ---

    def _generar_while(self, nodo, contexto):
        # nodo = ('while', condicion, cuerpo)
        condicion = nodo[1]
        cuerpo = nodo[2]

        etiqueta_inicio = self.nueva_etiqueta('while_inicio')
        etiqueta_fin = self.nueva_etiqueta('while_fin')

        self.texto.append(f'{etiqueta_inicio}:')
        self._generar_expresion(condicion, contexto)
        self.texto.append('     cmp x0, #0')
        self.texto.append(f'    beq {etiqueta_fin}')

        contexto['bucles'].append({'etiqueta': None, 'inicio': etiqueta_inicio, 'fin': etiqueta_fin})
        self._abrir_scope(contexto)
        for sent in cuerpo:
            self._generar_sentencia(sent, contexto)
        self._cerrar_scope(contexto)
        contexto['bucles'].pop()

        self.texto.append(f'    b {etiqueta_inicio}')
        self.texto.append(f'{etiqueta_fin}:')

    def _generar_loop(self, nodo, contexto):
        # nodo = ('loop', etiqueta | None, cuerpo)
        etiqueta = nodo[1]
        cuerpo = nodo[2]

        etiqueta_inicio = self.nueva_etiqueta('loop_inicio')
        etiqueta_fin = self.nueva_etiqueta('loop_fin')

        self.texto.append(f'{etiqueta_inicio}:')

        contexto['bucles'].append({'etiqueta': etiqueta, 'inicio': etiqueta_inicio, 'fin': etiqueta_fin})
        self._abrir_scope(contexto)
        for sent in cuerpo:
            self._generar_sentencia(sent, contexto)
        self._cerrar_scope(contexto)
        contexto['bucles'].pop()

        self.texto.append(f'    b {etiqueta_inicio}')
        self.texto.append(f'{etiqueta_fin}:')

    def _buscar_bucle(self, etiqueta, contexto):
        # Sin etiqueta: el bucle mas interno
        # Con etiqueta: el que la tenga
        for bucle in reversed(contexto['bucles']):
            if etiqueta is None or bucle['etiqueta'] == etiqueta:
                return bucle
        return None

    def _generar_break(self, nodo, contexto):
        bucle = self._buscar_bucle(nodo[1], contexto)
        if bucle is None:
            self.errores.append({'tipo': 'Semantico', 'linea': 0,
                                 'mensaje': 'break fuera de un bucle o con etiqueta inexistente'})
            return
        self.texto.append(f'    b {bucle["fin"]}')

    def _generar_continue(self, nodo, contexto):
        bucle = self._buscar_bucle(nodo[1], contexto)
        if bucle is None:
            self.errores.append({'tipo': 'Semantico', 'linea': 0,
                                 'mensaje': 'continue fuera de un bucle o con etiqueta inexistente'})
            return
        self.texto.append(f'    b {bucle["inicio"]}')

    def _generar_return(self, nodo, contexto):
        # nodo = ('return', valor | None)
        valor = nodo[1]
        if valor is not None:
            self._generar_expresion(valor, contexto)
        self.texto.append(f'    b {contexto["etiqueta_fin_funcion"]}')

    def _generar_let(self, nodo, contexto):
        # nodo = ('let', nombre, tipo, valor, mutable)
        nombre = nodo[1]
        valor = nodo[3]

        if valor is not None and valor[0] in ('array_literal', 'array_repeat'):
            offset_elem0 = self._declarar_variable(nodo, contexto)
            self._generar_inicializacion_arreglo(valor, offset_elem0, contexto)
            return

        if valor is None:
            # Sin valor inicial: se deja en 0
            offset = self._declarar_variable(nodo, contexto)
            self._guardar_variable('xzr', offset)
            return

        # El valor se evalua antes de declarar el nombre (let x = x + 1 usa el x anterior)
        self._generar_expresion(valor, contexto)    # deja el valor en x0
        offset = self._declarar_variable(nodo, contexto)
        self._guardar_variable('x0', offset)

    def _generar_inicializacion_arreglo(self, valor, offset_elem0, contexto):
        # Los indices son constantes de compilacion (posicion dentro del literal), asi que se usa _guardar_variable directo por cada elemento
        if valor[0] == 'array_literal':
            for i, elemento in enumerate(valor[1]):
                self._generar_expresion(elemento, contexto)
                self._guardar_variable('x0', offset_elem0 + i * 8)
        elif valor[0] == 'array_repeat':
            elemento, n = valor[1], valor[2]
            self._generar_expresion(elemento, contexto) # se evalua una sola vez
            self.texto.append('    mov x2, x0')
            for i in range(n):
                self._guardar_variable('x2', offset_elem0 + i * 8)

    def _generar_asignar(self, nodo, contexto):
        # nodo = ('asignar', nombre, valor)
        nombre = nodo[1]
        valor = nodo[2]

        self._generar_expresion(valor, contexto)
        offset = self._buscar_variable(nombre, contexto)['offset']
        self._guardar_variable('x0', offset)

    def _generar_asignar_indice(self, nodo, contexto):
        # nodo = ('asignar_indice', base, indice, valor)
        base, indice, valor = nodo[1], nodo[2], nodo[3]
        if base[0] != 'var':
            self.texto.append('    # asignar_indice: solo sobre una variable directa por ahora')
            return
        info = self._buscar_variable(base[1], contexto)
        if info['longitud'] is None:
            self.texto.append(f'    # "{base[1]}" no es un arreglo conocido por el codegen')
            return

        self._generar_expresion(valor, contexto)      # x0 = valor a guardar
        self.texto.append('    str x0, [sp, -16]!')   # se protege el valor mientras se calcula la direccion
        self._generar_direccion_arreglo(info['offset'], indice, contexto)   # x1 = direccion real
        self.texto.append('    ldr x0, [sp], 16')
        self.texto.append('    str x0, [x1]')

    def _generar_direccion_arreglo(self, offset_elem0, nodo_indice, contexto):
        # Deja en x1 la direccion real (offset_elem0 + indice*8 respecto a x29)
        # El indice se evalua en tiempo de ejecucion, calculandolo con aritmetica de registros
        self._generar_expresion(nodo_indice, contexto)      # x0 = indice
        self.texto.append('    lsl x0, x0, #3')             # x0 = indice * 8
        self.texto.append(f'    mov x1, #{offset_elem0}')
        self.texto.append('    add x1, x1, x0')
        self.texto.append('    sub x1, x29, x1')

    # --- EXPRESIONES (dejan el resultado en x0) ---

    def _generar_expresion(self, nodo, contexto):
        tipo = nodo[0]

        if tipo == 'literal':
            self.texto.append(f'    mov x0, #{nodo[1]}')
        elif tipo == 'bool':
            self.texto.append(f'    mov x0, #{1 if nodo[1] else 0}')
        elif tipo == 'var':
            nombre = nodo[1]
            info = self._buscar_variable(nombre, contexto)
            if info['longitud'] is not None:
                self.texto.append(f'    # "{nombre}" es un arreglo, imprimir/usar el arreglo completo aun no esta')
                return
            self._cargar_variable('x0', info['offset'])
        elif tipo == 'array_access':
            base, indice = nodo[1], nodo[2]
            if base[0] != 'var':
                self.texto.append('    # array_access: solo sobre una variable directa por ahora')
                return
            info = self._buscar_variable(base[1], contexto)
            if info['longitud'] is None:
                self.texto.append(f'    # "{base[1]}" no es un arreglo conocido por el codegen')
                return
            self._generar_direccion_arreglo(info['offset'], indice, contexto)
            self.texto.append('    ldr x0, [x1]')
        elif tipo == 'llamada':
            self._generar_llamada(nodo, contexto)
        elif tipo == 'binop':
            self._generar_binop(nodo, contexto)
        else:
            self.texto.append(f'    # expresion "{tipo}"')

    def _generar_binop(self, nodo, contexto):
        # nodo = ('binop', operador, izquierda, derecha)
        op = nodo[1]
        izquierda = nodo[2]
        derecha = nodo[3]

        operadores_aritmeticos = {'+', '-', '*', '/', '%'}
        operadores_relacionales = {
            '==': 'eq', '!=': 'ne',
            '>': 'gt', '>=': 'ge',
            '<': 'lt', '<=': 'le',
        }

        if op in operadores_aritmeticos:
            self._generar_binop_aritmetico(op, izquierda, derecha, contexto)
        elif op in operadores_relacionales:
            self._generar_binop_relacional(operadores_relacionales[op], izquierda, derecha, contexto)
        elif op == '&&':
            self._generar_and(izquierda, derecha, contexto)
        elif op == '||':
            self._generar_or(izquierda, derecha, contexto)
        else:
            self.texto.append(f'    # operador "{op}"')

    def _generar_binop_aritmetico(self, op, izquierda, derecha, contexto):
        self._generar_expresion(izquierda, contexto)    # x0 = izquierda
        self.texto.append('    str x0, [sp, -16]!')     # push izquierda
        self._generar_expresion(derecha, contexto)      # x0 = derecha
        self.texto.append('    mov x1, x0')             # x1 = derecha
        self.texto.append('    ldr x0, [sp], 16')       # pop -> x0 = izquierda

        if op == '+':
            self.texto.append('    add x0, x0, x1')
        elif op == '-':
            self.texto.append('    sub x0, x0, x1')
        elif op == '*':
            self.texto.append('    mul x0, x0, x1')
        elif op == '/':
            self.texto.append('    sdiv x0, x0, x1')
        elif op == '%':
            self.texto.append('    sdiv x2, x0, x1')
            self.texto.append('    msub x0, x2, x1, x0')

    def _generar_binop_relacional(self, condicion, izquierda, derecha, contexto):
        self._generar_expresion(izquierda, contexto)
        self.texto.append('    str x0, [sp, -16]!')
        self._generar_expresion(derecha, contexto)
        self.texto.append('    mov x1, x0')
        self.texto.append('    ldr x0, [sp], 16')
        self.texto.append('    cmp x0, x1')
        self.texto.append(f'    cset x0, {condicion}')

    def _generar_and(self, izquierda, derecha, contexto):
        # Corto-circuito: si izquierda es falso, no se evalua derecha
        etiqueta_falso = self.nueva_etiqueta('and_falso')
        etiqueta_fin = self.nueva_etiqueta('and_fin')

        self._generar_expresion(izquierda, contexto)
        self.texto.append('    cmp x0, #0')
        self.texto.append(f'    beq {etiqueta_falso}')
        self._generar_expresion(derecha, contexto)
        self.texto.append(f'    b {etiqueta_fin}')
        self.texto.append(f'{etiqueta_falso}:')
        self.texto.append('    mov x0, #0')
        self.texto.append(f'{etiqueta_fin}:')

    def _generar_or(self, izquierda, derecha, contexto):
        # Corto-circuito: si izquierda es verdadero, no se evalua derecha
        etiqueta_verdadero = self.nueva_etiqueta('or_verdadero')
        etiqueta_fin = self.nueva_etiqueta('or_fin')

        self._generar_expresion(izquierda, contexto)
        self.texto.append('    cmp x0, #0')
        self.texto.append(f'   bne {etiqueta_verdadero}')
        self._generar_expresion(derecha, contexto)
        self.texto.append(f'   b {etiqueta_fin}')
        self.texto.append(f'{etiqueta_verdadero}:')
        self.texto.append('    mov x0, #1')
        self.texto.append(f'{etiqueta_fin}:')

    def _generar_llamada(self, nodo, contexto):
        nombre = nodo[1]
        argumentos = nodo[2]

        if nombre == 'len':
            receptor = argumentos[0] if argumentos else None
            if receptor is not None and receptor[0] == 'var':
                info = self._buscar_variable(receptor[1], contexto)
                if info['longitud'] is not None:
                    self.texto.append(f'    mov x0, #{info["longitud"]}')
                    return
            self.texto.append('    # .len(): solo soportado sobre una variable de arreglo conocida')
            return

        if nombre == 'println':
            arg_valor = None
            if len(argumentos) == 1:
                arg_valor = argumentos[0]
            elif len(argumentos) == 2 and argumentos[0][0] == 'string':
                arg_valor = argumentos[1]

            if arg_valor is None:
                self.texto.append('    # TODO: forma de println! aun no esta')
                return

            self._generar_expresion(arg_valor, contexto)    # deja el valor en x0
            self.texto.append('    bl imprimir_entero')
            self._usa_imprimir_entero = True
        else:
            self._generar_llamada_usuario(nombre, argumentos, contexto)

    def _generar_llamada_usuario(self, nombre, argumentos, contexto):
        # Cada argumento se evalua y se guarda en el stack de inmediato y al final se sacan en orden inverso para dejarlos en x0, x1, x2...
        for argumento in argumentos:
            self._generar_expresion(argumento, contexto)
            self.texto.append('    str x0, [sp, -16]!')

        for i in reversed(range(len(argumentos))):
            if i < len(self.REGISTROS_PARAMETRO):
                self.texto.append(f'    ldr {self.REGISTROS_PARAMETRO[i]}, [sp], 16')
            else:
                self.texto.append('    add sp, sp, #16')

        self.texto.append(f'    bl {nombre}')