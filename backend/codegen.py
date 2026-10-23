# --- GENERADOR DE CODIGO ARM64 (AArch64) ---
# Recorre el mismo AST que ya usa interpreter.py, pero en vez de ejecutar cada nodo, emite las instrucciones de ensamblador equivalentes

import re
import struct

SYSCALL_WRITE = 64
SYSCALL_EXIT = 93

TAMANO_HEAP = 33554432  # 32 MB reservados en .bss para el heap de cadenas

TAMANO_SLOT = 16  # bytes reservados por variable escalar (simple sin empacar)

# Marcadores de formato de println!: {} y {:?}
MARCADOR = re.compile(r'(\{(?::\?)?\})')

ESCAPES_CHAR = {'n': 10, 't': 9, 'r': 13, '0': 0, '\\': 92, "'": 39, '"': 34}


class GeneradorCodigo:
    def __init__(self):
        self.texto = []     # lineas que van dentro de .section .text
        self.datos = []     # lineas que van dentro de .section .data
        self.errores = []
        self._contador_etiquetas = 0
        self._usa_imprimir_entero = False
        self._usa_salto_de_linea = False
        self._offsets_por_nodo = {}     # id(nodo 'let') -> offset unico en el stack frame
        self._formas_por_nodo = {}      # id(nodo 'let') -> [dim0, dim1, ...] si es arreglo
        self._usa_imprimir_bool = False
        self._usa_imprimir_char = False
        self._usa_imprimir_f64 = False
        self._usa_heap = False
        self._usa_concatenar = False
        self._usa_repetir = False
        self._usa_comparar_strings = False
        self._usa_contiene = False
        self._usa_reemplazar = False
        self._usa_caja = False
        self._usa_split = False
        self._usa_imprimir_vec = False
        self._usa_aleatorio = False
        self._tipos_funcion = {}        # nombre de funcion -> tipo de retorno (o None)
        self._tipos_parametros = {}     # nombre de funcion -> [tipo de cada parametro]
        self._formas_parametros = {}    # nombre de funcion -> [forma del parametro si es arreglo, o None]
        self._forma_retorno = {}        # nombre de funcion -> forma del arreglo que retorna (o None)
        self._elemento_retorno = {}     # nombre de funcion -> tipo de los elementos del arreglo que retorna
        self._omitir = set()            # id(sentencia) con error semantico fatal: no se genera

    def nueva_etiqueta(self, prefijo='L'):
        self._contador_etiquetas += 1
        return f'.{prefijo}{self._contador_etiquetas}'

    def generar(self, ast, omitir=None):
        """Punto de entrada. Devuelve (codigo_asm: str | None, errores: list)
        omitir: ids de sentencias que el analisis semantico marcó con error fatal (no se emiten)"""
        self._omitir = set(omitir or ())
        self.texto = []
        self.datos = []
        self.errores = []
        self._usa_imprimir_entero = False
        self._usa_salto_de_linea = False
        self._usa_imprimir_bool = False
        self._usa_imprimir_char = False
        self._usa_imprimir_f64 = False
        self._usa_heap = False
        self._usa_concatenar = False
        self._usa_repetir = False
        self._usa_comparar_strings = False
        self._usa_contiene = False
        self._usa_reemplazar = False
        self._usa_caja = False
        self._usa_split = False
        self._usa_imprimir_vec = False
        self._usa_aleatorio = False
        self._offsets_por_nodo = {}
        self._formas_por_nodo = {}

        programa = ast
        funciones = [d for d in programa[1] if d[0] == 'funcion']
        nombres_funciones = {f[1] for f in funciones}
        self._tipos_funcion = {f[1]: (f[3] if isinstance(f[3], str) else None) for f in funciones}
        self._tipos_parametros = {
            f[1]: [p[1] if isinstance(p[1], str) else None for p in f[2]] for f in funciones
        }
        self._formas_parametros = {f[1]: [self._forma_de_tipo(p[1]) for p in f[2]] for f in funciones}
        self._forma_retorno = {f[1]: self._forma_de_tipo(f[3]) for f in funciones}
        self._elemento_retorno = {f[1]: self._elemento_de_tipo(f[3]) for f in funciones}

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
        if self._usa_heap:
            lineas.append('heap_ptr: .quad heap_base')
        if self._usa_imprimir_entero:
            lineas.append('buffer_entero: .skip 24')
            lineas.append('buffer_entero_fin:')
        if self._usa_salto_de_linea:
            lineas.append('salto_de_linea: .ascii "\\n"')
        if self._usa_imprimir_vec:
            lineas.append('vec_texto_abre: .ascii "["')
            lineas.append('vec_texto_cierra: .ascii "]"')
            lineas.append('vec_texto_coma: .ascii ", "')
            lineas.append('vec_texto_comilla: .ascii "\\042"')
        if self._usa_imprimir_bool:
            lineas.append('texto_true: .ascii "true"')
            lineas.append('texto_false: .ascii "false"')
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
        if self._usa_imprimir_bool:
            lineas.append(self._rutina_imprimir_bool())
        if self._usa_imprimir_char:
            lineas.append(self._rutina_imprimir_char())
        if self._usa_imprimir_f64:
            lineas.append(self._rutina_imprimir_f64())
        if self._usa_heap:
            lineas.append(self._rutina_reservar_heap())
        if self._usa_concatenar:
            lineas.append(self._rutina_concatenar_strings())
        if self._usa_repetir:
            lineas.append(self._rutina_repetir_string())
        if self._usa_comparar_strings:
            lineas.append(self._rutina_comparar_strings())
        if self._usa_contiene:
            lineas.append(self._rutina_contiene_string())
        if self._usa_reemplazar:
            lineas.append(self._rutina_reemplazar_string())
        if self._usa_caja:
            lineas.append(self._rutina_cambiar_caja())
        if self._usa_split:
            lineas.append(self._rutina_split_string())
        if self._usa_imprimir_vec:
            lineas.append(self._rutina_imprimir_vec_strings())
        if self._usa_aleatorio:
            lineas.append(self._rutina_aleatorio_rango())

        if self._usa_heap:
            lineas.append('')
            lineas.append('.section .bss')
            lineas.append('    .align 4')
            lineas.append(f'heap_base: .skip {TAMANO_HEAP}')

        lineas.append('')

        return '\n'.join(lineas)

    def _rutina_imprimir_entero(self):
        # Entrada: x0 = valor entero (con signo) a imprimir
        # Convierte a decimal ASCII en buffer_entero (construyendo del final al principio) y lo escribe a stdout
        # (Sin salto de linea, eso lo agrega quien llama, una sola vez al final de todo el println!)
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
            '    ldp x19, x20, [sp, 16]',
            '    ldp x29, x30, [sp], 32',
            '    ret',
        ])

    def _rutina_imprimir_bool(self):
        # Entrada: x0 = 0 o 1. Escribe "true" o "false" (sin salto de linea)
        return '\n'.join([
            '',
            'imprimir_bool:',
            '    cbz x0, .Limprimir_bool_falso',
            '    adr x1, texto_true',
            '    mov x2, #4',
            '    b .Limprimir_bool_escribir',
            '.Limprimir_bool_falso:',
            '    adr x1, texto_false',
            '    mov x2, #5',
            '.Limprimir_bool_escribir:',
            '    mov x0, #1',
            f'    mov x8, #{SYSCALL_WRITE}',
            '    svc #0',
            '    ret',
        ])

    def _rutina_imprimir_char(self):
        # Entrada: x0 = punto de codigo Unicode, lo codifica en UTF-8 (1 a 4 bytes) y lo escribe
        return '\n'.join([
            '',
            'imprimir_char:',
            '    stp x29, x30, [sp, -32]!',
            '    mov x29, sp',
            '    mov x3, x0',
            '    add x1, sp, #16',
            '    cmp x3, #128',
            '    b.hs .Limprimir_char_dos',
            '    strb w3, [x1]',
            '    mov x2, #1',
            '    b .Limprimir_char_escribir',
            '.Limprimir_char_dos:',
            '    cmp x3, #2048',
            '    b.hs .Limprimir_char_tres',
            '    lsr x4, x3, #6',
            '    mov w5, #0xC0',
            '    orr w4, w4, w5',
            '    strb w4, [x1]',
            '    and w4, w3, #0x3F',
            '    mov w5, #0x80',
            '    orr w4, w4, w5',
            '    strb w4, [x1, #1]',
            '    mov x2, #2',
            '    b .Limprimir_char_escribir',
            '.Limprimir_char_tres:',
            '    mov x6, #65536',
            '    cmp x3, x6',
            '    b.hs .Limprimir_char_cuatro',
            '    lsr x4, x3, #12',
            '    mov w5, #0xE0',
            '    orr w4, w4, w5',
            '    strb w4, [x1]',
            '    lsr x4, x3, #6',
            '    and w4, w4, #0x3F',
            '    mov w5, #0x80',
            '    orr w4, w4, w5',
            '    strb w4, [x1, #1]',
            '    and w4, w3, #0x3F',
            '    orr w4, w4, w5',
            '    strb w4, [x1, #2]',
            '    mov x2, #3',
            '    b .Limprimir_char_escribir',
            '.Limprimir_char_cuatro:',
            '    lsr x4, x3, #18',
            '    mov w5, #0xF0',
            '    orr w4, w4, w5',
            '    strb w4, [x1]',
            '    lsr x4, x3, #12',
            '    and w4, w4, #0x3F',
            '    mov w5, #0x80',
            '    orr w4, w4, w5',
            '    strb w4, [x1, #1]',
            '    lsr x4, x3, #6',
            '    and w4, w4, #0x3F',
            '    orr w4, w4, w5',
            '    strb w4, [x1, #2]',
            '    and w4, w3, #0x3F',
            '    orr w4, w4, w5',
            '    strb w4, [x1, #3]',
            '    mov x2, #4',
            '.Limprimir_char_escribir:',
            '    mov x0, #1',
            f'    mov x8, #{SYSCALL_WRITE}',
            '    svc #0',
            '    ldp x29, x30, [sp], 32',
            '    ret',
        ])

    def _rutina_imprimir_f64(self):
        # Entrada: x0 = patron de bits de un f64
        # Escribe la parte entera con imprimir_entero, un punto y hasta 9 decimales sin ceros finales (siempre al menos uno: 3.0)
        return '\n'.join([
            '',
            'imprimir_f64:',
            '    stp x29, x30, [sp, -64]!',
            '    mov x29, sp',
            '    fmov d0, x0',
            '    fmov d1, xzr',
            '    fcmp d0, d1',
            '    b.ge .Limprimir_f64_positivo',
            '    fneg d0, d0',
            '    str d0, [sp, #16]',
            '    mov w1, #45',                          # signo menos
            '    strb w1, [sp, #32]',
            '    add x1, sp, #32',
            '    mov x2, #1',
            '    mov x0, #1',
            f'    mov x8, #{SYSCALL_WRITE}',
            '    svc #0',
            '    ldr d0, [sp, #16]',
            '.Limprimir_f64_positivo:',
            '    fcvtzs x9, d0',                        # x9 = parte entera
            '    scvtf d1, x9',
            '    fsub d2, d0, d1',                      # d2 = parte fraccionaria
            '    movz x10, #0xCA00',
            '    movk x10, #0x3B9A, lsl #16',           # x10 = 1000000000
            '    scvtf d3, x10',
            '    fmul d2, d2, d3',
            '    fcvtns x11, d2',                       # x11 = fraccion redondeada a 9 digitos
            '    cmp x11, x10',
            '    b.lt .Limprimir_f64_sin_acarreo',
            '    add x9, x9, #1',                       # la fraccion se redondeo a 1.000000000
            '    mov x11, #0',
            '.Limprimir_f64_sin_acarreo:',
            '    str x11, [sp, #24]',
            '    mov x0, x9',
            '    bl imprimir_entero',
            '    ldr x11, [sp, #24]',
            '    mov w12, #46',                         # punto decimal en la posicion 0 del buffer
            '    strb w12, [sp, #32]',
            '    mov x12, #10',
            '    mov x13, #9',
            '.Limprimir_f64_digitos:',
            '    udiv x14, x11, x12',
            '    msub x15, x14, x12, x11',
            '    add x15, x15, #48',
            '    add x16, sp, #32',
            '    strb w15, [x16, x13]',
            '    mov x11, x14',
            '    sub x13, x13, #1',
            '    cmp x13, #1',
            '    b.ge .Limprimir_f64_digitos',
            '    mov x13, #10',                         # largo del buffer: punto + 9 digitos
            '.Limprimir_f64_recorte:',
            '    cmp x13, #2',
            '    b.le .Limprimir_f64_escribir',
            '    add x16, sp, #32',
            '    sub x17, x13, #1',
            '    ldrb w15, [x16, x17]',
            '    cmp w15, #48',
            '    b.ne .Limprimir_f64_escribir',
            '    mov x13, x17',
            '    b .Limprimir_f64_recorte',
            '.Limprimir_f64_escribir:',
            '    add x1, sp, #32',
            '    mov x2, x13',
            '    mov x0, #1',
            f'    mov x8, #{SYSCALL_WRITE}',
            '    svc #0',
            '    ldp x29, x30, [sp], 64',
            '    ret',
        ])

    def _rutina_reservar_heap(self):
        # Entrada: x0 = bytes
        # Salida: x0 = direccion del bloque (reserva secuencial, multiplos de 16)
        return '\n'.join([
            '',
            'reservar_heap:',
            '    add x0, x0, #15',
            '    bic x0, x0, #15',
            '    adr x1, heap_ptr',
            '    ldr x2, [x1]',
            '    add x3, x2, x0',
            '    str x3, [x1]',
            '    mov x0, x2',
            '    ret',
        ])

    def _rutina_concatenar_strings(self):
        # Entrada: x0/x1 = puntero y largo de a, x2/x3 = puntero y largo de b
        # Salida: x0/x1 = puntero y largo de la cadena nueva a + b (en el heap)
        return '\n'.join([
            '',
            'concatenar_strings:',
            '    stp x29, x30, [sp, -48]!',
            '    mov x29, sp',
            '    stp x0, x1, [sp, #16]',
            '    stp x2, x3, [sp, #32]',
            '    add x0, x1, x3',
            '    bl reservar_heap',
            '    ldp x4, x5, [sp, #16]',
            '    ldp x6, x7, [sp, #32]',
            '    mov x9, x0',
            '    mov x10, #0',
            '.Lconcatenar_copiar_a:',
            '    cmp x10, x5',
            '    b.ge .Lconcatenar_inicio_b',
            '    ldrb w11, [x4, x10]',
            '    strb w11, [x9, x10]',
            '    add x10, x10, #1',
            '    b .Lconcatenar_copiar_a',
            '.Lconcatenar_inicio_b:',
            '    add x9, x9, x5',
            '    mov x10, #0',
            '.Lconcatenar_copiar_b:',
            '    cmp x10, x7',
            '    b.ge .Lconcatenar_fin',
            '    ldrb w11, [x6, x10]',
            '    strb w11, [x9, x10]',
            '    add x10, x10, #1',
            '    b .Lconcatenar_copiar_b',
            '.Lconcatenar_fin:',
            '    add x1, x5, x7',
            '    ldp x29, x30, [sp], 48',
            '    ret',
        ])

    def _rutina_repetir_string(self):
        # Entrada: x0/x1 = puntero y largo, x2 = cantidad de repeticiones (negativa cuenta como 0)
        # Salida: x0/x1 = puntero y largo de la cadena repetida (en el heap)
        return '\n'.join([
            '',
            'repetir_string:',
            '    stp x29, x30, [sp, -48]!',
            '    mov x29, sp',
            '    cmp x2, #0',
            '    csel x2, xzr, x2, lt',
            '    stp x0, x1, [sp, #16]',
            '    str x2, [sp, #32]',
            '    mul x0, x1, x2',
            '    bl reservar_heap',
            '    ldp x4, x5, [sp, #16]',
            '    ldr x6, [sp, #32]',
            '    mov x9, x0',
            '    mov x12, #0',
            '.Lrepetir_externo:',
            '    cmp x12, x6',
            '    b.ge .Lrepetir_fin',
            '    mov x10, #0',
            '.Lrepetir_interno:',
            '    cmp x10, x5',
            '    b.ge .Lrepetir_siguiente',
            '    ldrb w11, [x4, x10]',
            '    strb w11, [x9, x10]',
            '    add x10, x10, #1',
            '    b .Lrepetir_interno',
            '.Lrepetir_siguiente:',
            '    add x9, x9, x5',
            '    add x12, x12, #1',
            '    b .Lrepetir_externo',
            '.Lrepetir_fin:',
            '    mul x1, x5, x6',
            '    ldp x29, x30, [sp], 48',
            '    ret',
        ])

    def _rutina_comparar_strings(self):
        # Entrada: x0/x1 = puntero y largo de a, x2/x3 = puntero y largo de b
        # Salida: x0 = -1, 0 o 1 segun a < b, a == b o a > b (orden byte a byte, a igualdad de prefijo gana la mas larga)
        return '\n'.join([
            '',
            'comparar_strings:',
            '    mov x9, #0',
            '.Lcomparar_ciclo:',
            '    cmp x9, x1',
            '    b.ge .Lcomparar_fin_a',
            '    cmp x9, x3',
            '    b.ge .Lcomparar_mayor',
            '    ldrb w10, [x0, x9]',
            '    ldrb w11, [x2, x9]',
            '    cmp w10, w11',
            '    b.lo .Lcomparar_menor',
            '    b.hi .Lcomparar_mayor',
            '    add x9, x9, #1',
            '    b .Lcomparar_ciclo',
            '.Lcomparar_fin_a:',
            '    cmp x9, x3',
            '    b.lt .Lcomparar_menor',
            '    mov x0, #0',
            '    ret',
            '.Lcomparar_menor:',
            '    mov x0, #-1',
            '    ret',
            '.Lcomparar_mayor:',
            '    mov x0, #1',
            '    ret',
        ])

    def _rutina_contiene_string(self):
        # Entrada: x0/x1 = texto (puntero, largo), x2/x3 = subcadena
        # Salida: x0 = 1 si aparece, 0 si no
        return '\n'.join([
            '',
            'contiene_string:',
            '    cbz x3, .Lcontiene_si',
            '    sub x7, x1, x3',
            '    mov x5, #0',
            '.Lcontiene_ciclo:',
            '    cmp x5, x7',
            '    b.gt .Lcontiene_no',
            '    mov x8, #0',
            '.Lcontiene_comparar:',
            '    cmp x8, x3',
            '    b.ge .Lcontiene_si',
            '    add x9, x5, x8',
            '    ldrb w10, [x0, x9]',
            '    ldrb w11, [x2, x8]',
            '    cmp w10, w11',
            '    b.ne .Lcontiene_siguiente',
            '    add x8, x8, #1',
            '    b .Lcontiene_comparar',
            '.Lcontiene_siguiente:',
            '    add x5, x5, #1',
            '    b .Lcontiene_ciclo',
            '.Lcontiene_si:',
            '    mov x0, #1',
            '    ret',
            '.Lcontiene_no:',
            '    mov x0, #0',
            '    ret',
        ])

    def _rutina_reemplazar_string(self):
        # Entrada: x0/x1 = texto, x2/x3 = parte a buscar, x4/x5 = reemplazo
        # Salida: x0/x1 = cadena nueva en el heap (si la parte a buscar es vacia el texto queda igual)
        return '\n'.join([
            '',
            'reemplazar_string:',
            '    stp x29, x30, [sp, -96]!',
            '    mov x29, sp',
            '    stp x0, x1, [sp, #16]',
            '    stp x2, x3, [sp, #32]',
            '    stp x4, x5, [sp, #48]',
            '    mov x6, #0',
            '    mov x7, #0',
            '    cbz x3, .Lreemplazar_reservar',
            '.Lreemplazar_contar:',
            '    sub x8, x1, x3',
            '    cmp x7, x8',
            '    b.gt .Lreemplazar_reservar',
            '    mov x9, #0',
            '.Lreemplazar_comparar_1:',
            '    cmp x9, x3',
            '    b.ge .Lreemplazar_coincide_1',
            '    add x10, x7, x9',
            '    ldrb w11, [x0, x10]',
            '    ldrb w12, [x2, x9]',
            '    cmp w11, w12',
            '    b.ne .Lreemplazar_no_coincide_1',
            '    add x9, x9, #1',
            '    b .Lreemplazar_comparar_1',
            '.Lreemplazar_coincide_1:',
            '    add x6, x6, #1',
            '    add x7, x7, x3',
            '    b .Lreemplazar_contar',
            '.Lreemplazar_no_coincide_1:',
            '    add x7, x7, #1',
            '    b .Lreemplazar_contar',
            '.Lreemplazar_reservar:',
            '    sub x8, x5, x3',
            '    mul x8, x8, x6',
            '    add x8, x8, x1',
            '    str x8, [sp, #64]',
            '    mov x0, x8',
            '    bl reservar_heap',
            '    str x0, [sp, #72]',
            '    ldp x0, x1, [sp, #16]',
            '    ldp x2, x3, [sp, #32]',
            '    ldp x4, x5, [sp, #48]',
            '    ldr x13, [sp, #72]',
            '    mov x7, #0',
            '    cbz x3, .Lreemplazar_resto',
            '.Lreemplazar_llenar:',
            '    sub x8, x1, x3',
            '    cmp x7, x8',
            '    b.gt .Lreemplazar_resto',
            '    mov x9, #0',
            '.Lreemplazar_comparar_2:',
            '    cmp x9, x3',
            '    b.ge .Lreemplazar_coincide_2',
            '    add x10, x7, x9',
            '    ldrb w11, [x0, x10]',
            '    ldrb w12, [x2, x9]',
            '    cmp w11, w12',
            '    b.ne .Lreemplazar_no_coincide_2',
            '    add x9, x9, #1',
            '    b .Lreemplazar_comparar_2',
            '.Lreemplazar_coincide_2:',
            '    mov x9, #0',
            '.Lreemplazar_copiar_nuevo:',
            '    cmp x9, x5',
            '    b.ge .Lreemplazar_fin_nuevo',
            '    ldrb w11, [x4, x9]',
            '    strb w11, [x13], #1',
            '    add x9, x9, #1',
            '    b .Lreemplazar_copiar_nuevo',
            '.Lreemplazar_fin_nuevo:',
            '    add x7, x7, x3',
            '    b .Lreemplazar_llenar',
            '.Lreemplazar_no_coincide_2:',
            '    ldrb w11, [x0, x7]',
            '    strb w11, [x13], #1',
            '    add x7, x7, #1',
            '    b .Lreemplazar_llenar',
            '.Lreemplazar_resto:',
            '    cmp x7, x1',
            '    b.ge .Lreemplazar_fin',
            '    ldrb w11, [x0, x7]',
            '    strb w11, [x13], #1',
            '    add x7, x7, #1',
            '    b .Lreemplazar_resto',
            '.Lreemplazar_fin:',
            '    ldr x0, [sp, #72]',
            '    ldr x1, [sp, #64]',
            '    ldp x29, x30, [sp], 96',
            '    ret',
        ])

    def _rutina_cambiar_caja(self):
        # Entrada: x0/x1 = texto, x2 = 0 para mayusculas o 1 para minusculas (letras ASCII)
        # Salida: x0/x1 = copia transformada en el heap
        return '\n'.join([
            '',
            'cambiar_caja:',
            '    stp x29, x30, [sp, -48]!',
            '    mov x29, sp',
            '    stp x0, x1, [sp, #16]',
            '    str x2, [sp, #32]',
            '    mov x0, x1',
            '    bl reservar_heap',
            '    ldp x4, x5, [sp, #16]',
            '    ldr x6, [sp, #32]',
            '    mov x9, #0',
            '.Lcaja_ciclo:',
            '    cmp x9, x5',
            '    b.ge .Lcaja_fin',
            '    ldrb w10, [x4, x9]',
            '    cbnz x6, .Lcaja_a_minuscula',
            '    sub w11, w10, #97',
            '    cmp w11, #25',
            '    b.hi .Lcaja_guardar',
            '    sub w10, w10, #32',
            '    b .Lcaja_guardar',
            '.Lcaja_a_minuscula:',
            '    sub w11, w10, #65',
            '    cmp w11, #25',
            '    b.hi .Lcaja_guardar',
            '    add w10, w10, #32',
            '.Lcaja_guardar:',
            '    strb w10, [x0, x9]',
            '    add x9, x9, #1',
            '    b .Lcaja_ciclo',
            '.Lcaja_fin:',
            '    mov x1, x5',
            '    ldp x29, x30, [sp], 48',
            '    ret',
        ])

    def _rutina_split_string(self):
        # Entrada: x0/x1 = texto, x2/x3 = separador
        # Salida: x0 = bloque en el heap: [cantidad][relleno] seguido de (puntero, largo) por cada pieza
        # Las piezas apuntan dentro del texto original (no se copian)
        return '\n'.join([
            '',
            'split_string:',
            '    stp x29, x30, [sp, -80]!',
            '    mov x29, sp',
            '    stp x0, x1, [sp, #16]',
            '    stp x2, x3, [sp, #32]',
            '    mov x4, x0',
            '    mov x5, #0',
            '    mov x6, #1',
            '    cbz x3, .Lsplit_reservar',
            '.Lsplit_contar:',
            '    sub x7, x1, x3',
            '    cmp x5, x7',
            '    b.gt .Lsplit_reservar',
            '    mov x8, #0',
            '.Lsplit_comparar_1:',
            '    cmp x8, x3',
            '    b.ge .Lsplit_coincide_1',
            '    add x9, x5, x8',
            '    ldrb w10, [x4, x9]',
            '    ldrb w11, [x2, x8]',
            '    cmp w10, w11',
            '    b.ne .Lsplit_no_coincide_1',
            '    add x8, x8, #1',
            '    b .Lsplit_comparar_1',
            '.Lsplit_coincide_1:',
            '    add x6, x6, #1',
            '    add x5, x5, x3',
            '    b .Lsplit_contar',
            '.Lsplit_no_coincide_1:',
            '    add x5, x5, #1',
            '    b .Lsplit_contar',
            '.Lsplit_reservar:',
            '    str x6, [sp, #48]',
            '    lsl x0, x6, #4',
            '    add x0, x0, #16',
            '    bl reservar_heap',
            '    str x0, [sp, #56]',
            '    ldr x6, [sp, #48]',
            '    str x6, [x0]',
            '    ldp x4, x1, [sp, #16]',
            '    ldp x2, x3, [sp, #32]',
            '    add x12, x0, #16',
            '    mov x5, #0',
            '    mov x13, #0',
            '    cbz x3, .Lsplit_ultima',
            '.Lsplit_llenar:',
            '    sub x7, x1, x3',
            '    cmp x5, x7',
            '    b.gt .Lsplit_ultima',
            '    mov x8, #0',
            '.Lsplit_comparar_2:',
            '    cmp x8, x3',
            '    b.ge .Lsplit_coincide_2',
            '    add x9, x5, x8',
            '    ldrb w10, [x4, x9]',
            '    ldrb w11, [x2, x8]',
            '    cmp w10, w11',
            '    b.ne .Lsplit_no_coincide_2',
            '    add x8, x8, #1',
            '    b .Lsplit_comparar_2',
            '.Lsplit_coincide_2:',
            '    add x14, x4, x13',
            '    sub x15, x5, x13',
            '    stp x14, x15, [x12], #16',
            '    add x5, x5, x3',
            '    mov x13, x5',
            '    b .Lsplit_llenar',
            '.Lsplit_no_coincide_2:',
            '    add x5, x5, #1',
            '    b .Lsplit_llenar',
            '.Lsplit_ultima:',
            '    add x14, x4, x13',
            '    sub x15, x1, x13',
            '    stp x14, x15, [x12]',
            '    ldr x0, [sp, #56]',
            '    ldp x29, x30, [sp], 80',
            '    ret',
        ])

    def _rutina_imprimir_vec_strings(self):
        # Entrada: x0 = bloque de split_string. Escribe ["a", "b", "c"] (sin salto de linea)
        escribir = lambda etiqueta, largo: [
            f'    adr x1, {etiqueta}',
            f'    mov x2, #{largo}',
            '    mov x0, #1',
            f'    mov x8, #{SYSCALL_WRITE}',
            '    svc #0',
        ]
        lineas = [
            '',
            'imprimir_vec_strings:',
            '    stp x29, x30, [sp, -48]!',
            '    mov x29, sp',
            '    str x0, [sp, #16]',
            '    str xzr, [sp, #24]',
        ]
        lineas += escribir('vec_texto_abre', 1)
        lineas += [
            '.Limprimir_vec_ciclo:',
            '    ldr x0, [sp, #16]',
            '    ldr x4, [x0]',
            '    ldr x5, [sp, #24]',
            '    cmp x5, x4',
            '    b.ge .Limprimir_vec_fin',
            '    cbz x5, .Limprimir_vec_sin_coma',
        ]
        lineas += escribir('vec_texto_coma', 2)
        lineas += ['.Limprimir_vec_sin_coma:']
        lineas += escribir('vec_texto_comilla', 1)
        lineas += [
            '    ldr x0, [sp, #16]',
            '    ldr x5, [sp, #24]',
            '    lsl x5, x5, #4',
            '    add x5, x5, #16',
            '    add x5, x0, x5',
            '    ldr x1, [x5]',
            '    ldr x2, [x5, #8]',
            '    mov x0, #1',
            f'    mov x8, #{SYSCALL_WRITE}',
            '    svc #0',
        ]
        lineas += escribir('vec_texto_comilla', 1)
        lineas += [
            '    ldr x5, [sp, #24]',
            '    add x5, x5, #1',
            '    str x5, [sp, #24]',
            '    b .Limprimir_vec_ciclo',
            '.Limprimir_vec_fin:',
        ]
        lineas += escribir('vec_texto_cierra', 1)
        lineas += [
            '    ldp x29, x30, [sp], 48',
            '    ret',
        ]
        return '\n'.join(lineas)

    def _rutina_aleatorio_rango(self):
        # Entrada: x0 = minimo, x1 = maximo (ambos incluidos). Salida: x0 = entero aleatorio en [minimo, maximo]
        # Los bytes aleatorios vienen de la llamada al sistema getrandom (278)
        return '\n'.join([
            '',
            'aleatorio_rango:',
            '    stp x29, x30, [sp, -48]!',
            '    mov x29, sp',
            '    stp x0, x1, [sp, #16]',
            '    add x0, sp, #32',
            '    mov x1, #8',
            '    mov x2, #0',
            '    mov x8, #278',
            '    svc #0',
            '    ldp x3, x4, [sp, #16]',
            '    ldr x5, [sp, #32]',
            '    sub x6, x4, x3',
            '    add x6, x6, #1',
            '    cmp x6, #0',
            '    b.le .Laleatorio_sin_rango',
            '    udiv x7, x5, x6',
            '    msub x7, x7, x6, x5',
            '    add x0, x3, x7',
            '    b .Laleatorio_fin',
            '.Laleatorio_sin_rango:',
            '    mov x0, x3',
            '.Laleatorio_fin:',
            '    ldp x29, x30, [sp], 48',
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

        contexto = {
            'scopes': [{}],
            'bucles': [],
            'etiqueta_fin_funcion': self.nueva_etiqueta('fin_funcion'),
            'tipo_retorno': self._tipos_funcion.get(nombre),
            'forma_retorno': self._forma_retorno.get(nombre),
        }

        # Los primeros 8 parametros llegan en x0-x7 y se copian a su slot en el stack antes de generar el cuerpo 
        # para que el resto del codigo lo trate igual que cualquier otra variable
        # Un arreglo llega como puntero a su elemento 0 y se copia completo al frame
        self.texto.append('    # copia de parametros (x0-x7) a su espacio en el stack frame')
        indice_registro = 0
        for parametro in parametros:
            offset = self._offsets_por_nodo[id(parametro)]
            forma = self._formas_por_nodo.get(id(parametro))
            if forma is not None:
                tipo = self._elemento_de_tipo(parametro[1])
                contexto['scopes'][0][parametro[0]] = {'offset': offset, 'forma': forma, 'tipo': tipo}
                if indice_registro < len(self.REGISTROS_PARAMETRO):
                    self.texto.append(f'    mov x10, {self.REGISTROS_PARAMETRO[indice_registro]}')
                    self._direccion_en_registro('x11', offset)
                    self._emitir_copia_arreglo(self._total_elementos(forma))
                else:
                    self.texto.append(f'    # parametro "{parametro[0]}": no cabe en los registros x0-x7')
                indice_registro += 1
                continue
            tipo = parametro[1] if isinstance(parametro[1], str) else None
            contexto['scopes'][0][parametro[0]] = {'offset': offset, 'forma': None, 'tipo': tipo}
            necesarios = 2 if tipo == 'String' else 1
            if indice_registro + necesarios <= len(self.REGISTROS_PARAMETRO):
                self._guardar_variable(self.REGISTROS_PARAMETRO[indice_registro], offset)
                if tipo == 'String':
                    self._guardar_variable(self.REGISTROS_PARAMETRO[indice_registro + 1], offset - 8)
            else:
                self.texto.append(f'    # parametro "{parametro[0]}": no caben en los registros x0-x7')
            indice_registro += necesarios

        for sentencia in cuerpo:
            self._generar_sentencia(sentencia, contexto)

        self.texto.append(f'{contexto["etiqueta_fin_funcion"]}:')
        self._ajustar_sp('add', espacio)
        # Epilogo: restauramos y retornamos
        self.texto.append('    ldp x29, x30, [sp], 16')
        self.texto.append('    ret')
        self.texto.append('')

    # --- RESERVA DE MEMORIA (variables escalares y arreglos, incluye parametros) ---

    def _forma_arreglo(self, valor):
        # Dimensiones de un arreglo, en el mismo orden que se escriben los indices: [dim_0, dim_1, ...]
        # None si 'valor' no es un array_literal/array_repeat
        if valor is None:
            return None
        forma = []
        actual = valor
        while actual is not None and actual[0] in ('array_literal', 'array_repeat'):
            if actual[0] == 'array_literal':
                elementos = actual[1]
                forma.append(len(elementos))
                actual = elementos[0] if elementos else None
            else:
                forma.append(actual[2])
                actual = actual[1]
        return forma if forma else None

    def _aplanar_valores(self, valor):
        # Lista de nodos-expresion escalares en orden row-major (recorre arreglos anidados y expande [v; N] repitiendo el nodo N veces)
        if valor[0] == 'array_literal':
            resultado = []
            for elemento in valor[1]:
                resultado.extend(self._aplanar_valores(elemento))
            return resultado
        if valor[0] == 'array_repeat':
            elemento, n = valor[1], valor[2]
            return self._aplanar_valores(elemento) * n
        return [valor]

    def _strides(self, forma):
        # stride[j] = cuantos elementos se saltan al aumentar el indice j en 1 (row-major: el ultimo indice es el que varia mas seguido)
        strides = []
        acumulado = 1
        for dim in reversed(forma):
            strides.append(acumulado)
            acumulado *= dim
        strides.reverse()
        return strides

    def _forma_de_tipo(self, tipo):
        # ('array', ('array', 'i32', 3), 2)  ->  [2, 3]  (None si el tipo no es un arreglo)
        forma = []
        while isinstance(tipo, tuple) and tipo and tipo[0] == 'array':
            forma.append(tipo[2])
            tipo = tipo[1]
        return forma or None

    def _elemento_de_tipo(self, tipo):
        # Tipo escalar de los elementos: ('array', ('array', 'i32', 3), 2) -> 'i32'
        while isinstance(tipo, tuple) and tipo and tipo[0] == 'array':
            tipo = tipo[1]
        return tipo if isinstance(tipo, str) else None

    def _total_elementos(self, forma):
        total = 1
        for dim in forma:
            total *= dim
        return total

    def _reservar_arreglo(self, nodo, forma, offset):
        bytes_necesarios = self._total_elementos(forma) * 8
        # AArch64 exige que lo reservado con sub sp sea multiplo de 16 las variables escalares ya lo cumple (slots de 16)
        # Se redondea hacia arriba ya que un arreglo con cantidad impar de elementos (N*8 con N impar) no cumple
        bytes_reservados = ((bytes_necesarios + 15) // 16) * 16
        offset_elem0 = offset[0] + 8
        offset[0] += bytes_reservados
        self._offsets_por_nodo[id(nodo)] = offset_elem0
        self._formas_por_nodo[id(nodo)] = forma

    def _reservar_variables(self, cuerpo, parametros=()):
        # Cada parametro y cada 'let' del cuerpo recibe su propio slot, identificado por el nodo
        # Asi dos variables con el mismo nombre en bloques distintos nunca comparten memoria
        offset = [0]
        formas_nombres = {}  # nombre -> forma, para saber el tamaño de arreglos que vienen de otra variable o de un slice
        for parametro in parametros:
            forma = self._forma_de_tipo(parametro[1])
            if forma is not None:
                self._reservar_arreglo(parametro, forma, offset)
                formas_nombres[parametro[0]] = forma
            else:
                offset[0] += TAMANO_SLOT
                self._offsets_por_nodo[id(parametro)] = offset[0]
        self._recolectar_lets(cuerpo, offset, formas_nombres)
        return offset[0]

    def _forma_de_let(self, sentencia, formas_nombres):
        # Forma del arreglo que declara un let: por su valor literal, por la anotacion de tipo,
        # por la variable/llamada/slice de donde se copia. None si es una variable escalar
        valor = sentencia[3]
        forma = self._forma_arreglo(valor)
        if forma is not None:
            return forma
        forma = self._forma_de_tipo(sentencia[2])
        if forma is not None:
            return forma
        if valor is None:
            return None
        if valor[0] == 'var':
            return formas_nombres.get(valor[1])
        if valor[0] == 'llamada':
            return self._forma_retorno.get(valor[1])
        if valor[0] == 'array_slice':
            base = valor[1]
            forma_base = formas_nombres.get(base[1]) if base[0] == 'var' else None
            inicio, fin = valor[2], valor[3]
            if forma_base and inicio[0] == 'literal' and fin[0] == 'literal':
                return [max(fin[1] - inicio[1], 0)] + forma_base[1:]
        return None

    def _recolectar_lets(self, sentencias, offset, formas_nombres=None):
        if formas_nombres is None:
            formas_nombres = {}
        for sentencia in sentencias:
            if not isinstance(sentencia, tuple) or not sentencia:
                continue
            tipo = sentencia[0]
            if tipo == 'let':
                forma = self._forma_de_let(sentencia, formas_nombres)
                if forma is not None and self._total_elementos(forma) > 0:
                    self._reservar_arreglo(sentencia, forma, offset)
                    formas_nombres[sentencia[1]] = forma
                else:
                    offset[0] += TAMANO_SLOT
                    self._offsets_por_nodo[id(sentencia)] = offset[0]
                    formas_nombres.pop(sentencia[1], None)
            elif tipo == 'if':
                self._recolectar_lets(sentencia[2], offset, formas_nombres)
                cuerpo_else = sentencia[3]
                if cuerpo_else is not None:
                    if cuerpo_else[0] == 'if':
                        self._recolectar_lets([cuerpo_else], offset, formas_nombres)
                    else:
                        self._recolectar_lets(cuerpo_else, offset, formas_nombres)
            elif tipo in ('while', 'loop'):
                self._recolectar_lets(sentencia[2], offset, formas_nombres)
            elif tipo == 'bloque':
                self._recolectar_lets(sentencia[1], offset, formas_nombres)
            elif tipo == 'match':
                for caso in sentencia[2]:
                    self._recolectar_lets(caso[2], offset, formas_nombres)

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

    def _direccion_en_registro(self, registro, offset):
        # registro = x29 - offset (direccion real de una variable o del elemento 0 de un arreglo)
        if offset <= 4095:
            self.texto.append(f'    sub {registro}, x29, #{offset}')
        else:
            self._cargar_inmediato(registro, offset)
            self.texto.append(f'    sub {registro}, x29, {registro}')

    def _emitir_copia_arreglo(self, total):
        # Copia 'total' elementos de 8 bytes de x10 (origen) a x11 (destino)
        # Convencion de los arreglos: el elemento i esta en (direccion del elemento 0) - 8*i, por eso se avanza hacia abajo
        # Usa x9 y x12; no toca x0-x7
        if total <= 0:
            return
        etiqueta = self.nueva_etiqueta('copia_arreglo')
        self.texto.append(f'    # copiar arreglo de {total} elementos')
        self._cargar_inmediato('x12', total)
        self.texto.append(f'{etiqueta}:')
        self.texto.append('    ldr x9, [x10], #-8')
        self.texto.append('    str x9, [x11], #-8')
        self.texto.append('    subs x12, x12, #1')
        self.texto.append(f'    b.ne {etiqueta}')

    def _generar_puntero_arreglo(self, nodo, contexto):
        # Deja en x0 la direccion del elemento 0 de un arreglo y devuelve su forma (None si no se pudo)
        if nodo[0] == 'var':
            info = self._buscar_variable(nodo[1], contexto)
            if info['forma'] is None:
                return None
            self._direccion_en_registro('x0', info['offset'])
            return info['forma']
        if nodo[0] == 'llamada' and self._forma_retorno.get(nodo[1]) is not None:
            self._generar_expresion(nodo, contexto)
            return self._forma_retorno[nodo[1]]
        if nodo[0] in ('array_literal', 'array_repeat'):
            # Arreglo literal usado como valor: se arma en el heap
            forma = self._forma_arreglo(nodo)
            planos = self._aplanar_valores(nodo)
            total = len(planos)
            tipo_elemento = self._tipo_expresion(planos[0], contexto) if planos else 'i32'
            self._cargar_inmediato('x0', total * 8)
            self.texto.append('    bl reservar_heap')
            self._usa_heap = True
            self._cargar_inmediato('x1', (total - 1) * 8)
            self.texto.append('    add x0, x0, x1')
            self.texto.append('    str x0, [sp, -16]!')         # direccion del elemento 0 (protegida)
            for i, elemento in enumerate(planos):
                self._generar_expresion(elemento, contexto)
                self._convertir_a_tipo(self._tipo_expresion(elemento, contexto), tipo_elemento)
                self.texto.append('    ldr x1, [sp]')
                if i:
                    self._cargar_inmediato('x2', i * 8)
                    self.texto.append('    sub x1, x1, x2')
                self.texto.append('    str x0, [x1]')
            self.texto.append('    ldr x0, [sp], 16')
            return forma
        if nodo[0] == 'array_slice' and nodo[1][0] == 'var':
            info = self._buscar_variable(nodo[1][1], contexto)
            inicio, fin = nodo[2], nodo[3]
            if info['forma'] is None or inicio[0] != 'literal' or fin[0] != 'literal':
                return None
            bloque = self._total_elementos(info['forma'][1:]) if len(info['forma']) > 1 else 1
            self._direccion_en_registro('x0', info['offset'] + inicio[1] * bloque * 8)
            return [max(fin[1] - inicio[1], 0)] + info['forma'][1:]
        return None

    # --- SCOPES ---

    def _abrir_scope(self, contexto):
        contexto['scopes'].append({})

    def _cerrar_scope(self, contexto):
        contexto['scopes'].pop()

    def _declarar_variable(self, nodo_let, contexto, tipo=None):
        offset = self._offsets_por_nodo[id(nodo_let)]
        forma = self._formas_por_nodo.get(id(nodo_let))
        contexto['scopes'][-1][nodo_let[1]] = {'offset': offset, 'forma': forma, 'tipo': tipo}
        return offset

    def _guardar_segun_tipo(self, tipo, offset):
        # Un String ocupa el slot completo: puntero en la mitad baja y largo en la alta
        self._guardar_variable('x0', offset)
        if tipo == 'String':
            self._guardar_variable('x1', offset - 8)

    def _cargar_segun_tipo(self, tipo, offset):
        self._cargar_variable('x0', offset)
        if tipo == 'String':
            self._cargar_variable('x1', offset - 8)

    def _buscar_variable(self, nombre, contexto):
        # Del bloque mas interno hacia el mas externo
        for scope in reversed(contexto['scopes']):
            if nombre in scope:
                return scope[nombre]
        raise KeyError(f'variable "{nombre}" sin declarar en el codegen')

    # --- ARREGLOS: descomposicion de accesos encadenados ---

    def _descomponer_acceso(self, nodo):
        # Desenreda una cadena de ('array_access', base, indice) anidada hasta llegar a ('var', nombre)
        # Devuelve (nombre, [indices]) en el mismo orden en que se escribieron: matrix[1][2] -> (matrix, [1, 2])
        # (None, None) si la base final no es una variable directa
        indices = []
        actual = nodo
        while actual[0] == 'array_access':
            indices.append(actual[2])
            actual = actual[1]
        if actual[0] != 'var':
            return None, None
        indices.reverse()
        return actual[1], indices

    def _generar_direccion_arreglo(self, offset_elem0, indices, forma, contexto):
        # Deja en x1 la direccion real de arr[i0][i1]...[iN] (row-major)
        strides = self._strides(forma)
        self.texto.append('    mov x0, #0')
        self.texto.append('    str x0, [sp, -16]!')
        for nodo_indice, stride in zip(indices, strides):
            self._generar_expresion(nodo_indice, contexto)  # x0 = indice
            if stride != 1:
                self.texto.append(f'    mov x1, #{stride}')
                self.texto.append('    mul x0, x0, x1')
            self.texto.append('    ldr x1, [sp]')
            self.texto.append('    add x1, x1, x0')
            self.texto.append('    str x1, [sp]')
        self.texto.append('    ldr x0, [sp], 16')
        self.texto.append('    lsl x0, x0, #3')
        self.texto.append(f'    mov x1, #{offset_elem0}')
        self.texto.append('    add x1, x1, x0')
        self.texto.append('    sub x1, x29, x1')

    # --- SENTENCIAS ---

    def _generar_sentencia(self, sentencia, contexto):
        if not isinstance(sentencia, tuple) or not sentencia:
            return
        if id(sentencia) in self._omitir:
            self._generar_sentencia_omitida(sentencia, contexto)
            return
        # Red de seguridad: si una sentencia no se puede traducir, se descarta solo esa y el resto del programa sigue
        inicio_texto = len(self.texto)
        cantidad_scopes = len(contexto['scopes'])
        cantidad_bucles = len(contexto['bucles'])
        try:
            self._generar_sentencia_interna(sentencia, contexto)
        except Exception as error:
            del self.texto[inicio_texto:]
            del contexto['scopes'][cantidad_scopes:]
            del contexto['bucles'][cantidad_bucles:]
            self.texto.append(f'    # sentencia "{sentencia[0]}" no generada: {error}')
            if sentencia[0] == 'let':
                self._generar_sentencia_omitida(sentencia, contexto)

    def _generar_sentencia_omitida(self, sentencia, contexto):
        # Sentencia con error semantico: no se ejecuta, pero si declaraba una variable
        # se declara con su valor por defecto para que el resto del programa la pueda usar
        self.texto.append(f'    # sentencia "{sentencia[0]}" omitida por error semantico')
        if sentencia[0] != 'let' or id(sentencia) not in self._offsets_por_nodo:
            return
        tipo = sentencia[2] if isinstance(sentencia[2], str) else None
        forma = self._formas_por_nodo.get(id(sentencia))
        if forma is not None:
            tipo = self._elemento_de_tipo(sentencia[2]) or 'i32'
        offset = self._declarar_variable(sentencia, contexto, tipo=tipo or 'None')
        total = self._total_elementos(forma) if forma is not None else 1
        for i in range(total):
            self._guardar_variable('xzr', offset + i * 8)

    def _generar_sentencia_interna(self, sentencia, contexto):
        tipo = sentencia[0]

        if tipo == 'let':
            self._generar_let(sentencia, contexto)
        elif tipo == 'asignar':
            self._generar_asignar(sentencia, contexto)
        elif tipo == 'asignar_indice':
            self._generar_asignar_indice(sentencia, contexto)
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
        elif tipo == 'bloque':
            self._abrir_scope(contexto)
            for sent in sentencia[1]:
                self._generar_sentencia(sent, contexto)
            self._cerrar_scope(contexto)
        elif tipo in ('binop', 'unop', 'var', 'literal', 'bool', 'char', 'string', 'string_from', 'array_access'):
            # Sentencia de tipo expresion: se evalua y se descarta el valor
            self._generar_expresion(sentencia, contexto)
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

            if patron != 'default' and not (isinstance(patron, tuple) and patron[0] == 'var'):
                # ('var', x) como patron se comporta como comodin (en Rust liga el valor a x)
                if isinstance(patron, tuple) and patron[0] == 'char':
                    valor_patron = self._punto_de_codigo(patron[1])
                elif isinstance(patron, tuple) and patron[0] == 'bool':
                    valor_patron = 1 if patron[1] else 0
                else:
                    valor_patron = patron
                self.texto.append('    ldr x0, [sp]')
                self._cargar_inmediato('x1', valor_patron)
                self.texto.append('    cmp x0, x1')
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
        if valor is not None and contexto.get('forma_retorno') is not None:
            # Retornar un arreglo: se copia al heap (el frame de la funcion se libera al salir) y se devuelve en x0 la direccion de su elemento 0
            forma = self._generar_puntero_arreglo(valor, contexto)
            if forma is None:
                raise ValueError('el valor retornado no es un arreglo conocido')
            total = self._total_elementos(forma)
            self.texto.append('    mov x10, x0')
            self._cargar_inmediato('x0', total * 8)
            self.texto.append('    bl reservar_heap')
            self._usa_heap = True
            self._cargar_inmediato('x1', (total - 1) * 8)
            self.texto.append('    add x0, x0, x1')         # x0 = elemento 0 (los demas van hacia abajo)
            self.texto.append('    mov x11, x0')
            self._emitir_copia_arreglo(total)
        elif valor is not None:
            self._generar_expresion(valor, contexto)
            self._convertir_a_tipo(self._tipo_expresion(valor, contexto), contexto.get('tipo_retorno'))
        self.texto.append(f'    b {contexto["etiqueta_fin_funcion"]}')

    # --- LET / ASIGNACIONES ---

    def _generar_let(self, nodo, contexto):
        # nodo = ('let', nombre, tipo, valor, mutable)
        tipo_declarado = nodo[2]
        valor = nodo[3]

        if valor is not None and valor[0] in ('array_literal', 'array_repeat'):
            tipo_elemento = self._tipo_elemento_arreglo(tipo_declarado, valor, contexto)
            offset_elem0 = self._declarar_variable(nodo, contexto, tipo=tipo_elemento)
            self._generar_inicializacion_arreglo(valor, offset_elem0, contexto, tipo_elemento)
            return

        forma_destino = self._formas_por_nodo.get(id(nodo))
        if forma_destino is not None:
            # Arreglo que se copia desde otra variable, desde el retorno de una funcion o desde un slice
            tipo_elemento = self._elemento_de_tipo(tipo_declarado) or self._tipo_elemento_origen(valor, contexto)
            if valor is None:
                offset_elem0 = self._declarar_variable(nodo, contexto, tipo=tipo_elemento or 'i32')
                for i in range(self._total_elementos(forma_destino)):
                    self._guardar_variable('xzr', offset_elem0 + i * 8)
                return
            forma_origen = self._generar_puntero_arreglo(valor, contexto)
            if forma_origen is None:
                raise ValueError('no se pudo obtener el arreglo de origen')
            offset_elem0 = self._declarar_variable(nodo, contexto, tipo=tipo_elemento)
            self.texto.append('    mov x10, x0')
            self._direccion_en_registro('x11', offset_elem0)
            self._emitir_copia_arreglo(min(self._total_elementos(forma_origen), self._total_elementos(forma_destino)))
            return

        # El tipo se calcula antes de declarar el nombre (let x = x + 1 usa el x anterior)
        if isinstance(tipo_declarado, str):
            tipo = tipo_declarado
        elif valor is not None:
            tipo = self._tipo_expresion(valor, contexto)
        else:
            tipo = None

        if valor is None:
            # Sin valor inicial: valor por defecto (0, 0.0, false, "")
            offset = self._declarar_variable(nodo, contexto, tipo=tipo)
            self._guardar_variable('xzr', offset)
            if tipo == 'String':
                self._guardar_variable('xzr', offset - 8)
            return

        self._generar_expresion(valor, contexto)    # deja el valor en x0 (un String: puntero en x0 y largo en x1)
        self._convertir_a_tipo(self._tipo_expresion(valor, contexto), tipo)
        offset = self._declarar_variable(nodo, contexto, tipo=tipo)
        self._guardar_segun_tipo(tipo, offset)

    def _tipo_elemento_origen(self, valor, contexto):
        # Tipo de los elementos de un arreglo que viene de una variable, una llamada o un slice
        if valor is None:
            return None
        if valor[0] == 'var':
            return self._buscar_variable(valor[1], contexto)['tipo']
        if valor[0] == 'llamada':
            return self._elemento_retorno.get(valor[1])
        if valor[0] == 'array_slice':
            return self._tipo_elemento_origen(valor[1], contexto)
        return None

    def _tipo_elemento_arreglo(self, tipo_declarado, valor, contexto):
        # Tipo escalar de los elementos: sale de la anotacion [[T; n]; m] o del primer elemento del literal
        actual = tipo_declarado
        while isinstance(actual, tuple):
            actual = actual[1]
        if isinstance(actual, str):
            return actual
        planos = self._aplanar_valores(valor)
        return self._tipo_expresion(planos[0], contexto) if planos else 'i32'

    def _generar_inicializacion_arreglo(self, valor, offset_elem0, contexto, tipo_elemento=None):
        # Los indices son constantes de compilacion (posicion dentro del literal ya aplanado) asi que se usa _guardar_variable directo por cada elemento
        for i, elemento in enumerate(self._aplanar_valores(valor)):
            self._generar_expresion(elemento, contexto)
            self._convertir_a_tipo(self._tipo_expresion(elemento, contexto), tipo_elemento)
            self._guardar_variable('x0', offset_elem0 + i * 8)

    def _generar_asignar(self, nodo, contexto):
        # nodo = ('asignar', nombre, valor)
        nombre = nodo[1]
        valor = nodo[2]

        info = self._buscar_variable(nombre, contexto)
        if info['forma'] is not None:
            # arreglo = otro_arreglo / arreglo = funcion_que_retorna_arreglo()
            forma_origen = self._generar_puntero_arreglo(valor, contexto)
            if forma_origen is None:
                raise ValueError('asignacion de arreglo no soportada')
            self.texto.append('    mov x10, x0')
            self._direccion_en_registro('x11', info['offset'])
            self._emitir_copia_arreglo(min(self._total_elementos(forma_origen), self._total_elementos(info['forma'])))
            return

        self._generar_expresion(valor, contexto)
        self._convertir_a_tipo(self._tipo_expresion(valor, contexto), info['tipo'])
        self._guardar_segun_tipo(info['tipo'], info['offset'])

    def _generar_asignar_indice(self, nodo, contexto):
        # nodo = ('asignar_indice', base, indice, valor)
        # base puede ser ('var', nombre) o a su vez ('array_access', ..., ...) para dimensiones intermedias
        base, indice, valor = nodo[1], nodo[2], nodo[3]
        nombre, indices = self._descomponer_acceso(('array_access', base, indice))
        if nombre is None:
            self.texto.append('    # asignar_indice: forma de acceso no soportada')
            return
        info = self._buscar_variable(nombre, contexto)
        if info['forma'] is None:
            self.texto.append(f'    # "{nombre}" no es un arreglo conocido por el codegen')
            return

        self._generar_expresion(valor, contexto)      # x0 = valor a guardar
        self._convertir_a_tipo(self._tipo_expresion(valor, contexto), info['tipo'])
        self.texto.append('    str x0, [sp, -16]!')   # se protege el valor mientras se calcula la direccion
        self._generar_direccion_arreglo(info['offset'], indices, info['forma'], contexto)   # x1 = direccion real
        self.texto.append('    ldr x0, [sp], 16')
        self.texto.append('    str x0, [x1]')

    # --- EXPRESIONES (dejan el resultado en x0) ---

    def _cargar_inmediato(self, registro, valor):
        # mov solo codifica 16 bits (o su negado), un valor mas grande se arma por partes de 16 bits
        if 0 <= valor <= 0xFFFF or -0x10000 <= valor < 0:
            self.texto.append(f'    mov {registro}, #{valor}')
            return
        bits = valor & 0xFFFFFFFFFFFFFFFF
        primero = True
        for i in range(4):
            parte = (bits >> (16 * i)) & 0xFFFF
            if parte == 0:
                continue
            desplazamiento = f', lsl #{16 * i}' if i else ''
            instruccion = 'movz' if primero else 'movk'
            self.texto.append(f'    {instruccion} {registro}, #{parte}{desplazamiento}')
            primero = False

    def _convertir_a_tipo(self, tipo_origen, tipo_destino):
        # x0 trae un valor de tipo_origen. Un i32 que se usa como f64 se convierte al patron de bits del double
        if tipo_destino == 'f64' and tipo_origen == 'i32':
            self.texto.append('    scvtf d0, x0')
            self.texto.append('    fmov x0, d0')

    def _generar_expresion_como_f64(self, nodo, contexto):
        self._generar_expresion(nodo, contexto)
        self._convertir_a_tipo(self._tipo_expresion(nodo, contexto), 'f64')

    def _punto_de_codigo(self, texto):
        # El lexer entrega el contenido del char sin interpretar escapes: 'a' -> "a", '\n' -> "\\n"
        if len(texto) == 2 and texto[0] == '\\':
            return ESCAPES_CHAR.get(texto[1], ord(texto[1]))
        return ord(texto[0]) if texto else 0

    def _tipo_expresion(self, nodo, contexto):
        # Tipo de una expresion: 'i32', 'f64', 'bool', 'char', 'String' o None
        tipo = nodo[0]
        if tipo == 'literal':
            return 'f64' if isinstance(nodo[1], float) else 'i32'
        if tipo == 'bool':
            return 'bool'
        if tipo == 'char':
            return 'char'
        if tipo in ('string', 'string_from'):
            return 'String'
        if tipo == 'var':
            return self._buscar_variable(nodo[1], contexto)['tipo']
        if tipo == 'array_access':
            nombre, _ = self._descomponer_acceso(nodo)
            if nombre is None:
                return None
            tipo_base = self._buscar_variable(nombre, contexto)['tipo']
            return 'String' if tipo_base == 'Vec' else tipo_base
        if tipo == 'unop':
            operando = self._tipo_expresion(nodo[2], contexto)
            if nodo[1] == '!':
                return 'bool' if operando in ('bool', None) else 'None'
            return operando if operando in ('i32', 'f64', None) else 'None'
        if tipo == 'binop':
            return self._tipo_binop(nodo[1], self._tipo_expresion(nodo[2], contexto),
                                    self._tipo_expresion(nodo[3], contexto))
        if tipo == 'llamada':
            nombre = nodo[1]
            if nombre in ('len', 'random'):
                return 'i32'
            if nombre in ('typeof', 'to_uppercase', 'to_lowercase', 'replace'):
                return 'String'
            if nombre == 'contains':
                return 'bool'
            if nombre == 'split':
                return 'Vec'
            if nombre == 'random':
                return 'i32'
            return self._tipos_funcion.get(nombre)
        return None

    def _tipo_binop(self, op, izquierdo, derecho):
        # Tablas de tipos: 'None' = combinacion invalida (seimprime como None)
        numericos = ('i32', 'f64')
        if 'None' in (izquierdo, derecho):
            return 'None'
        if op in ('&&', '||'):
            return 'bool' if izquierdo in ('bool', None) and derecho in ('bool', None) else 'None'
        if op in ('==', '!=', '>', '>=', '<', '<='):
            if None in (izquierdo, derecho):
                return 'bool'
            validos = ((izquierdo in numericos and derecho in numericos)
                       or (izquierdo, derecho) in (('i32', 'char'), ('char', 'i32'), ('char', 'char'),
                                                    ('bool', 'bool'), ('String', 'String')))
            return 'bool' if validos else 'None'
        if izquierdo in numericos and derecho in numericos:
            return 'f64' if 'f64' in (izquierdo, derecho) else 'i32'
        if op == '+' and izquierdo == 'String' and derecho == 'String':
            return 'String'
        if op == '*' and (izquierdo, derecho) in (('i32', 'String'), ('String', 'i32')):
            return 'String'
        if None in (izquierdo, derecho):
            # tipo desconocido: se asume entero
            otro = derecho if izquierdo is None else izquierdo
            return otro if otro in numericos else 'i32'
        return 'None'

    def _generar_expresion(self, nodo, contexto):
        tipo = nodo[0]

        if tipo in ('binop', 'unop') and self._tipo_expresion(nodo, contexto) == 'None':
            # Operacion con tipos incompatibles (ya reportada por el semantico): el valor es None
            self.texto.append(f'    # operacion "{nodo[1]}" con tipos incompatibles -> None')
            self.texto.append('    mov x0, #0')
            self.texto.append('    mov x1, #0')
            return

        if tipo == 'literal':
            if isinstance(nodo[1], float):
                bits = struct.unpack('<Q', struct.pack('<d', nodo[1]))[0]
                self._cargar_inmediato('x0', bits)
            else:
                self._cargar_inmediato('x0', nodo[1])
        elif tipo == 'bool':
            self.texto.append(f'    mov x0, #{1 if nodo[1] else 0}')
        elif tipo == 'char':
            self._cargar_inmediato('x0', self._punto_de_codigo(nodo[1]))
        elif tipo in ('string', 'string_from'):
            etiqueta, longitud = self._emitir_literal_string(self._texto_de_nodo_string(nodo))
            self.texto.append(f'    adr x0, {etiqueta}')
            self._cargar_inmediato('x1', longitud)
        elif tipo == 'var':
            nombre = nodo[1]
            info = self._buscar_variable(nombre, contexto)
            if info['forma'] is not None:
                self.texto.append(f'    # "{nombre}" es un arreglo, usar el arreglo completo como valor no esta soportado')
                return
            self._cargar_segun_tipo(info['tipo'], info['offset'])
        elif tipo == 'unop':
            op = nodo[1]
            self._generar_expresion(nodo[2], contexto)
            if op == '!':
                self.texto.append('    eor x0, x0, #1')
            elif op == '-':
                if self._tipo_expresion(nodo[2], contexto) == 'f64':
                    self.texto.append('    fmov d0, x0')
                    self.texto.append('    fneg d0, d0')
                    self.texto.append('    fmov x0, d0')
                else:
                    self.texto.append('    neg x0, x0')
            else:
                self.texto.append(f'    # operador unario "{op}"')
        elif tipo == 'array_access':
            nombre, indices = self._descomponer_acceso(nodo)
            if nombre is None:
                self.texto.append('    # array_access: forma de acceso no soportada')
                return
            info = self._buscar_variable(nombre, contexto)
            if info['tipo'] == 'Vec' and len(indices) == 1:
                # pieza i del bloque de split: puntero en x0 y largo en x1
                self._generar_expresion(indices[0], contexto)
                self.texto.append('    lsl x0, x0, #4')
                self.texto.append('    add x0, x0, #16')
                self._cargar_variable('x1', info['offset'])
                self.texto.append('    add x2, x1, x0')
                self.texto.append('    ldr x0, [x2]')
                self.texto.append('    ldr x1, [x2, #8]')
                return
            if info['forma'] is None:
                self.texto.append(f'    # "{nombre}" no es un arreglo conocido por el codegen')
                return
            self._generar_direccion_arreglo(info['offset'], indices, info['forma'], contexto)
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

        tipos_operandos = (self._tipo_expresion(izquierda, contexto), self._tipo_expresion(derecha, contexto))
        if 'String' in tipos_operandos:
            self._generar_binop_string(op, izquierda, derecha, tipos_operandos, contexto)
            return

        if 'f64' in tipos_operandos:
            self._generar_binop_f64(op, izquierda, derecha, contexto)
            return

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

    def _generar_binop_string(self, op, izquierda, derecha, tipos, contexto):
        # Un String viaja como par (x0 = puntero, x1 = largo), por eso se guarda en el stack en dos entradas
        tipo_izquierdo, tipo_derecho = tipos
        condiciones = {'==': 'eq', '!=': 'ne', '<': 'lt', '<=': 'le', '>': 'gt', '>=': 'ge'}

        if op == '*' and tipo_izquierdo == 'i32' and tipo_derecho == 'String':
            self._generar_expresion(izquierda, contexto)
            self.texto.append('    str x0, [sp, -16]!')
            self._generar_expresion(derecha, contexto)      # x0 = puntero, x1 = largo
            self.texto.append('    ldr x2, [sp], 16')       # x2 = repeticiones
            self.texto.append('    bl repetir_string')
            self._usa_repetir = True
            self._usa_heap = True
            return

        if op == '*' and tipo_izquierdo == 'String' and tipo_derecho == 'i32':
            self._generar_expresion(izquierda, contexto)
            self.texto.append('    str x0, [sp, -16]!')
            self.texto.append('    str x1, [sp, -16]!')
            self._generar_expresion(derecha, contexto)
            self.texto.append('    mov x2, x0')             # x2 = repeticiones
            self.texto.append('    ldr x1, [sp], 16')
            self.texto.append('    ldr x0, [sp], 16')
            self.texto.append('    bl repetir_string')
            self._usa_repetir = True
            self._usa_heap = True
            return

        if tipo_izquierdo == 'String' and tipo_derecho == 'String' and (op == '+' or op in condiciones):
            self._generar_expresion(izquierda, contexto)
            self.texto.append('    str x0, [sp, -16]!')
            self.texto.append('    str x1, [sp, -16]!')
            self._generar_expresion(derecha, contexto)
            self.texto.append('    mov x2, x0')             # x2/x3 = derecha
            self.texto.append('    mov x3, x1')
            self.texto.append('    ldr x1, [sp], 16')       # x0/x1 = izquierda
            self.texto.append('    ldr x0, [sp], 16')
            if op == '+':
                self.texto.append('    bl concatenar_strings')
                self._usa_concatenar = True
                self._usa_heap = True
            else:
                self.texto.append('    bl comparar_strings')
                self.texto.append('    cmp x0, #0')
                self.texto.append(f'    cset x0, {condiciones[op]}')
                self._usa_comparar_strings = True
            return

        self.texto.append(f'    # operador "{op}" sobre {tipo_izquierdo} y {tipo_derecho} no soportado')

    def _generar_binop_f64(self, op, izquierda, derecha, contexto):
        # Los dos lados se llevan a f64 (un i32 se promueve), el resultado aritmetico queda como bits en x0 y el relacional como 0/1
        self._generar_expresion_como_f64(izquierda, contexto)
        self.texto.append('    str x0, [sp, -16]!')
        self._generar_expresion_como_f64(derecha, contexto)
        self.texto.append('    fmov d1, x0')
        self.texto.append('    ldr x0, [sp], 16')
        self.texto.append('    fmov d0, x0')

        condiciones = {'==': 'eq', '!=': 'ne', '>': 'gt', '>=': 'ge', '<': 'mi', '<=': 'ls'}
        if op in condiciones:
            self.texto.append('    fcmp d0, d1')
            self.texto.append(f'    cset x0, {condiciones[op]}')
            return

        if op == '+':
            self.texto.append('    fadd d0, d0, d1')
        elif op == '-':
            self.texto.append('    fsub d0, d0, d1')
        elif op == '*':
            self.texto.append('    fmul d0, d0, d1')
        elif op == '/':
            self.texto.append('    fdiv d0, d0, d1')
        elif op == '%':
            self.texto.append('    fdiv d2, d0, d1')
            self.texto.append('    frintz d2, d2')
            self.texto.append('    fmsub d0, d2, d1, d0')
        else:
            self.texto.append(f'    # operador "{op}" sobre f64')
        self.texto.append('    fmov x0, d0')

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
            self._generar_len(argumentos, contexto)
            return

        if nombre == 'typeof':
            self._generar_typeof(argumentos, contexto)
            return

        if nombre == 'println':
            self._generar_println(argumentos, contexto)
            return

        if nombre == 'random':
            self._generar_expresion(argumentos[0], contexto)
            self.texto.append('    str x0, [sp, -16]!')
            self._generar_expresion(argumentos[1], contexto)
            self.texto.append('    mov x1, x0')
            self.texto.append('    ldr x0, [sp], 16')
            self.texto.append('    bl aleatorio_rango')
            self._usa_aleatorio = True
            return

        if nombre in ('contains', 'reverse') and argumentos and argumentos[0][0] == 'var':
            info = self._buscar_variable(argumentos[0][1], contexto)
            if info['forma'] is not None:
                self._generar_funcion_arreglo(nombre, info, argumentos, contexto)
                return

        if nombre in ('contains', 'replace', 'to_uppercase', 'to_lowercase', 'split'):
            self._generar_funcion_string(nombre, argumentos, contexto)
            return

        self._generar_llamada_usuario(nombre, argumentos, contexto)

    def _generar_funcion_arreglo(self, nombre, info, argumentos, contexto):
        # La forma del arreglo se conoce al compilar, por eso el recorrido se desenrolla
        forma = info['forma']
        base = info['offset']
        total = 1
        for dimension in forma:
            total *= dimension

        if nombre == 'reverse':
            # Invierte el orden de la primera dimension; cada bloque conserva el orden interno de sus elementos
            bloque = total // forma[0]
            for i in range(forma[0] // 2):
                j = forma[0] - 1 - i
                for k in range(bloque):
                    offset_a = base + (i * bloque + k) * 8
                    offset_b = base + (j * bloque + k) * 8
                    self._cargar_variable('x0', offset_a)
                    self._cargar_variable('x1', offset_b)
                    self._guardar_variable('x1', offset_a)
                    self._guardar_variable('x0', offset_b)
            return

        # contains(valor): recorre todos los elementos y compara con el valor
        self._generar_expresion(argumentos[1], contexto)
        self._convertir_a_tipo(self._tipo_expresion(argumentos[1], contexto), info['tipo'])
        etiqueta_si = self.nueva_etiqueta('contains_si')
        etiqueta_fin = self.nueva_etiqueta('contains_fin')
        for posicion in range(total):
            self._cargar_variable('x1', base + posicion * 8)
            self.texto.append('    cmp x0, x1')
            self.texto.append(f'    b.eq {etiqueta_si}')
        self.texto.append('    mov x0, #0')
        self.texto.append(f'    b {etiqueta_fin}')
        self.texto.append(f'{etiqueta_si}:')
        self.texto.append('    mov x0, #1')
        self.texto.append(f'{etiqueta_fin}:')

    def _empujar_string(self):
        # Guarda el String que esta en x0/x1 (puntero y largo) en dos entradas del stack
        self.texto.append('    str x0, [sp, -16]!')
        self.texto.append('    str x1, [sp, -16]!')

    def _sacar_string(self, registro_puntero, registro_largo):
        self.texto.append(f'    ldr {registro_largo}, [sp], 16')
        self.texto.append(f'    ldr {registro_puntero}, [sp], 16')

    def _generar_funcion_string(self, nombre, argumentos, contexto):
        # argumentos[0] es el receptor: el String sobre el que se llama el metodo
        receptor = argumentos[0]
        if self._tipo_expresion(receptor, contexto) != 'String':
            self.texto.append(f'    # {nombre}(): receptor no soportado')
            return

        if nombre in ('to_uppercase', 'to_lowercase'):
            self._generar_expresion(receptor, contexto)
            self.texto.append(f'    mov x2, #{0 if nombre == "to_uppercase" else 1}')
            self.texto.append('    bl cambiar_caja')
            self._usa_caja = True
            self._usa_heap = True
            return

        if nombre in ('contains', 'split'):
            self._generar_expresion(receptor, contexto)
            self._empujar_string()
            self._generar_expresion(argumentos[1], contexto)
            self.texto.append('    mov x2, x0')
            self.texto.append('    mov x3, x1')
            self._sacar_string('x0', 'x1')
            if nombre == 'contains':
                self.texto.append('    bl contiene_string')
                self._usa_contiene = True
            else:
                self.texto.append('    bl split_string')
                self._usa_split = True
                self._usa_heap = True
            return

        # replace(buscar, nuevo)
        self._generar_expresion(receptor, contexto)
        self._empujar_string()
        self._generar_expresion(argumentos[1], contexto)
        self._empujar_string()
        self._generar_expresion(argumentos[2], contexto)
        self.texto.append('    mov x4, x0')
        self.texto.append('    mov x5, x1')
        self._sacar_string('x2', 'x3')
        self._sacar_string('x0', 'x1')
        self.texto.append('    bl reemplazar_string')
        self._usa_reemplazar = True
        self._usa_heap = True

    def _generar_len(self, argumentos, contexto):
        receptor = argumentos[0] if argumentos else None
        if receptor is None:
            self.texto.append('    # .len() sin receptor')
            return
        if receptor[0] == 'var':
            info = self._buscar_variable(receptor[1], contexto)
            if info['forma'] is not None:
                self._cargar_inmediato('x0', info['forma'][0])
                return
        if self._tipo_expresion(receptor, contexto) == 'String':
            self._generar_expresion(receptor, contexto)     # x0 = puntero, x1 = largo
            self.texto.append('    mov x0, x1')
            return
        if self._tipo_expresion(receptor, contexto) == 'Vec':
            self._generar_expresion(receptor, contexto)     # x0 = bloque, la cantidad esta en su primer campo
            self.texto.append('    ldr x0, [x0]')
            return
        self.texto.append('    # .len(): receptor no soportado')

    def _generar_typeof(self, argumentos, contexto):
        # El tipo se conoce en tiempo de compilacion: se devuelve como un String literal
        nombre_tipo = 'null'
        if argumentos:
            argumento = argumentos[0]
            if argumento[0] == 'var' and self._buscar_variable(argumento[1], contexto)['forma'] is not None:
                nombre_tipo = 'array'
            else:
                nombre_tipo = self._tipo_expresion(argumento, contexto) or 'null'
        etiqueta, longitud = self._emitir_literal_string(nombre_tipo)
        self.texto.append(f'    adr x0, {etiqueta}')
        self._cargar_inmediato('x1', longitud)

    # --- IMPRESION: println! con texto literal, enteros, bool, char, String y arreglos ---

    def _generar_println(self, argumentos, contexto):
        # println!()                    -> solo el salto de linea
        # println!("a {} b {:?}", x, y) -> el texto literal con un valor por cada marcador
        # println!(x, y)                -> los valores separados por un espacio
        if not argumentos:
            self._generar_salto_de_linea()
            return

        primero = argumentos[0]
        if primero[0] == 'string' and MARCADOR.search(primero[1]):
            valores = list(argumentos[1:])
            for pedazo in MARCADOR.split(primero[1]):
                if not pedazo:
                    continue
                if MARCADOR.fullmatch(pedazo) and valores:
                    self._generar_escribir_valor(valores.pop(0), contexto)
                else:
                    self._generar_escribir_texto_literal(pedazo)
            self._generar_salto_de_linea()
            return

        for i, argumento in enumerate(argumentos):
            if i > 0:
                self._generar_escribir_texto_literal(' ')
            self._generar_escribir_valor(argumento, contexto)
        self._generar_salto_de_linea()

    def _generar_escribir_valor(self, nodo, contexto):
        if nodo[0] in ('string', 'string_from'):
            self._generar_escribir_texto_literal(self._texto_de_nodo_string(nodo))
            return

        if nodo[0] == 'var':
            info = self._buscar_variable(nodo[1], contexto)
            if info['forma'] is not None:
                self._generar_imprimir_arreglo(info)
                return

        if (nodo[0] == 'llamada' and self._forma_retorno.get(nodo[1]) is not None) or \
                nodo[0] in ('array_slice', 'array_literal', 'array_repeat'):
            # Arreglo que no esta en una variable: se imprime desde su direccion
            tipo_elemento = (self._elemento_retorno.get(nodo[1]) if nodo[0] == 'llamada'
                             else self._tipo_elemento_origen(nodo, contexto))
            if nodo[0] in ('array_literal', 'array_repeat'):
                planos = self._aplanar_valores(nodo)
                tipo_elemento = self._tipo_expresion(planos[0], contexto) if planos else 'i32'
            forma = self._generar_puntero_arreglo(nodo, contexto)
            if forma is None:
                raise ValueError('arreglo no soportado en println!')
            self.texto.append('    str x0, [sp, -16]!')
            self._generar_imprimir_arreglo_desde_puntero(forma, tipo_elemento or 'i32')
            self.texto.append('    add sp, sp, #16')
            return

        tipo = self._tipo_expresion(nodo, contexto)
        if tipo == 'None':
            self._generar_escribir_texto_literal('None')
        elif tipo == 'Vec':
            self._generar_expresion(nodo, contexto)     # x0 = bloque de split
            self.texto.append('    bl imprimir_vec_strings')
            self._usa_imprimir_vec = True
        elif tipo == 'String':
            self._generar_expresion(nodo, contexto)     # x0 = puntero, x1 = largo
            self.texto.append('    mov x2, x1')
            self.texto.append('    mov x1, x0')
            self.texto.append('    mov x0, #1')
            self.texto.append(f'    mov x8, #{SYSCALL_WRITE}')
            self.texto.append('    svc #0')
        else:
            self._generar_expresion(nodo, contexto)     # deja el valor en x0
            self._generar_imprimir_escalar_x0(tipo)

    def _generar_imprimir_escalar_x0(self, tipo):
        if tipo == 'bool':
            self.texto.append('    bl imprimir_bool')
            self._usa_imprimir_bool = True
        elif tipo == 'char':
            self.texto.append('    bl imprimir_char')
            self._usa_imprimir_char = True
        elif tipo == 'f64':
            self.texto.append('    bl imprimir_f64')
            self._usa_imprimir_f64 = True
            self._usa_imprimir_entero = True
        else:
            self.texto.append('    bl imprimir_entero')
            self._usa_imprimir_entero = True

    def _generar_imprimir_arreglo(self, info):
        # [a, b, c] o [[a, b], [c, d]]: la forma se conoce en tiempo de compilacion
        # Se desenrolla leyendo cada elemento desde su posicion en el stack
        forma = info['forma']
        elemento = info['tipo']
        base = info['offset']
        strides = self._strides(forma)

        def recorrer(nivel, desplazamiento):
            self._generar_escribir_texto_literal('[')
            for i in range(forma[nivel]):
                if i > 0:
                    self._generar_escribir_texto_literal(', ')
                posicion = desplazamiento + i * strides[nivel]
                if nivel < len(forma) - 1:
                    recorrer(nivel + 1, posicion)
                elif elemento == 'char':
                    self._generar_escribir_texto_literal('"')
                    self._cargar_variable('x0', base + posicion * 8)
                    self._generar_imprimir_escalar_x0('char')
                    self._generar_escribir_texto_literal('"')
                else:
                    self._cargar_variable('x0', base + posicion * 8)
                    self._generar_imprimir_escalar_x0(elemento)
            self._generar_escribir_texto_literal(']')

        recorrer(0, 0)

    def _generar_imprimir_arreglo_desde_puntero(self, forma, elemento):
        # Igual que _generar_imprimir_arreglo pero la direccion del elemento 0 esta en [sp]
        strides = self._strides(forma)

        def cargar(posicion):
            self.texto.append('    ldr x1, [sp]')
            if posicion:
                self._cargar_inmediato('x2', posicion * 8)
                self.texto.append('    sub x1, x1, x2')
            self.texto.append('    ldr x0, [x1]')

        def recorrer(nivel, desplazamiento):
            self._generar_escribir_texto_literal('[')
            for i in range(forma[nivel]):
                if i > 0:
                    self._generar_escribir_texto_literal(', ')
                posicion = desplazamiento + i * strides[nivel]
                if nivel < len(forma) - 1:
                    recorrer(nivel + 1, posicion)
                elif elemento == 'char':
                    self._generar_escribir_texto_literal('"')
                    cargar(posicion)
                    self._generar_imprimir_escalar_x0('char')
                    self._generar_escribir_texto_literal('"')
                else:
                    cargar(posicion)
                    self._generar_imprimir_escalar_x0(elemento)
            self._generar_escribir_texto_literal(']')

        recorrer(0, 0)

    def _emitir_literal_string(self, texto):
        etiqueta = self.nueva_etiqueta('str')[1:]   # sin el punto: va al .data, no es una etiqueta local
        datos = texto.encode('utf-8')
        escapado = ''.join(
            chr(b) if 32 <= b < 127 and b not in (34, 92) else f'\\{b:03o}'
            for b in datos
        )
        self.datos.append(f'{etiqueta}: .ascii "{escapado}"')
        return etiqueta, len(datos)

    def _texto_de_nodo_string(self, nodo):
        return nodo[1] if nodo[0] == 'string' else nodo[1][1]

    def _generar_escribir_texto_literal(self, texto):
        etiqueta, longitud = self._emitir_literal_string(texto)
        self.texto.append(f'    adr x1, {etiqueta}')
        self._cargar_inmediato('x2', longitud)
        self.texto.append('    mov x0, #1')
        self.texto.append(f'    mov x8, #{SYSCALL_WRITE}')
        self.texto.append('    svc #0')

    def _generar_salto_de_linea(self):
        self.texto.append('    adr x1, salto_de_linea')
        self.texto.append('    mov x2, #1')
        self.texto.append('    mov x0, #1')
        self.texto.append(f'    mov x8, #{SYSCALL_WRITE}')
        self.texto.append('    svc #0')
        self._usa_salto_de_linea = True

    def _generar_llamada_usuario(self, nombre, argumentos, contexto):
        # Cada argumento se evalua y se guarda en el stack de inmediato (un String ocupa dos entradas: puntero y largo) 
        # y al final se sacan en orden inverso para dejarlos en x0, x1, x2...
        if nombre not in self._tipos_funcion:
            raise ValueError(f"la funcion '{nombre}' no existe")
        total = 0
        tipos_parametros = self._tipos_parametros.get(nombre, [])
        formas_parametros = self._formas_parametros.get(nombre, [])
        for posicion, argumento in enumerate(argumentos):
            es_arreglo = posicion < len(formas_parametros) and formas_parametros[posicion] is not None
            if es_arreglo:
                # Los arreglos viajan como la direccion de su elemento 0; la funcion llamada hace su propia copia
                if self._generar_puntero_arreglo(argumento, contexto) is None:
                    raise ValueError('argumento de tipo arreglo no soportado')
                self.texto.append('    str x0, [sp, -16]!')
                total += 1
                continue
            self._generar_expresion(argumento, contexto)
            if posicion < len(tipos_parametros):
                self._convertir_a_tipo(self._tipo_expresion(argumento, contexto), tipos_parametros[posicion])
            self.texto.append('    str x0, [sp, -16]!')
            total += 1
            if self._tipo_expresion(argumento, contexto) == 'String':
                self.texto.append('    str x1, [sp, -16]!')
                total += 1

        for k in reversed(range(total)):
            if k < len(self.REGISTROS_PARAMETRO):
                self.texto.append(f'    ldr {self.REGISTROS_PARAMETRO[k]}, [sp], 16')
            else:
                self.texto.append('    add sp, sp, #16')

        self.texto.append(f'    bl {nombre}')