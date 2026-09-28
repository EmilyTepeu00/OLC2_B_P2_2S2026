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

    def nueva_etiqueta(self, prefijo='L'):
        self._contador_etiquetas += 1
        return f'.{prefijo}{self._contador_etiquetas}'

    def generar(self, ast):
        """Punto de entrada. Devuelve (codigo_asm: str | None, errores: list)"""
        self.texto = []
        self.datos = []
        self.errores = []
        self._usa_imprimir_entero = False

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

    def _generar_funcion(self, nodo):
        # nodo = ('funcion', nombre, parametros, tipo_retorno, cuerpo)
        nombre = nodo[1]
        cuerpo = nodo[4]

        self.texto.append(f'{nombre}:')
        # Prologo: guardamos frame pointer (x29) y link register (x30)
        self.texto.append('    stp x29, x30, [sp, -16]!')
        self.texto.append('    mov x29, sp')

        variables, espacio = self._reservar_variables(cuerpo)
        if espacio > 0:
            self.texto.append(f'    sub sp, sp, #{espacio}')

        contexto = {'variables': variables}
        for sentencia in cuerpo:
            self._generar_sentencia(sentencia, contexto)

        if espacio > 0:
            self.texto.append(f'    add sp, sp, #{espacio}')
        # Epilogo: restauramos y retornamos
        self.texto.append('    ldp x29, x30, [sp], 16')
        self.texto.append('    ret')
        self.texto.append('')

    def _reservar_variables(self, cuerpo):
        # Recorre el cuerpo completo, incluyendo dentro de if/while para que cualquier 'let' anidado tambien reciba su slot
        variables = {}
        offset = [0]
        self._recolectar_lets(cuerpo, variables, offset)
        return variables, offset[0]

    def _recolectar_lets(self, sentencias, variables, offset):
        for sentencia in sentencias:
            tipo = sentencia[0]
            if tipo == 'let':
                offset[0] += TAMANO_SLOT
                variables[sentencia[1]] = offset[0]
            elif tipo == 'if':
                self._recolectar_lets(sentencia[2], variables, offset)
                cuerpo_else = sentencia[3]
                if cuerpo_else is not None:
                    if cuerpo_else[0] == 'if':
                        self._recolectar_lets([cuerpo_else], variables, offset)
                    else:
                        self._recolectar_lets(cuerpo_else, variables, offset)
            elif tipo == 'while':
                self._recolectar_lets(sentencia[2], variables, offset)

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
        for sent in cuerpo_then:
            self._generar_sentencia(sent, contexto)
        self.texto.append(f'    b {etiqueta_fin}')
        self.texto.append(f'{etiqueta_else}:')
        if cuerpo_else is not None:
            if cuerpo_else[0] == 'if':
                self._generar_if(cuerpo_else, contexto)
            else:
                for sent in cuerpo_else:
                    self._generar_sentencia(sent, contexto)
        self.texto.append(f'{etiqueta_fin}:')

    def _generar_let(self, nodo, contexto):
        # nodo = ('let', nombre, tipo, valor, mutable)
        nombre = nodo[1]
        valor = nodo[3]

        if valor is None:
            # Sin valor inicial: se deja en 0
            return

        self._generar_expresion(valor, contexto)    # deja el valor en x0
        offset = contexto['variables'][nombre]
        self.texto.append(f'    str x0, [x29, #-{offset}]')

    def _generar_asignar(self, nodo, contexto):
        # nodo = ('asignar', nombre, valor)
        nombre = nodo[1]
        valor = nodo[2]

        self._generar_expresion(valor, contexto)
        offset = contexto['variables'][nombre]
        self.texto.append(f'    str x0, [x29, #-{offset}]')

    # --- EXPRESIONES (dejan el resultado en x0) ---

    def _generar_expresion(self, nodo, contexto):
        tipo = nodo[0]

        if tipo == 'literal':
            self.texto.append(f'    mov x0, #{nodo[1]}')
        elif tipo == 'bool':
            self.texto.append(f'    mov x0, #{1 if nodo[1] else 0}')
        elif tipo == 'var':
            nombre = nodo[1]
            offset = contexto['variables'][nombre]
            self.texto.append(f'    ldr x0, [x29, #-{offset}]')
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
            self.texto.append(f'    # TODO: llamada a "{nombre}" aun no esta')