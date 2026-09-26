# --- GENERADOR DE CODIGO ARM64 (AArch64) ---
# Recorre el mismo AST que ya usa interpreter.py, pero en vez de ejecutar cada nodo, emite las instrucciones de ensamblador equivalentes

SYSCALL_EXIT = 93


class GeneradorCodigo:
    def __init__(self):
        self.texto = []     # lineas que van dentro de .section .text
        self.datos = []     # lineas que van dentro de .section .data
        self.errores = []
        self._contador_etiquetas = 0
        self._contador_strings = 0

    def nueva_etiqueta(self, prefijo='L'):
        self._contador_etiquetas += 1
        return f'{prefijo}{self._contador_etiquetas}'

    def nueva_etiqueta_string(self):
        self._contador_strings += 1
        return f'str{self._contador_strings}'

    def generar(self, ast):
        """Punto de entrada. Devuelve (codigo_asm: str, errores: list)"""
        self.texto = []
        self.datos = []
        self.errores = []

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

    def _ensamblar_archivo_final(self):
        lineas = []

        lineas.append('.section .data')
        if self.datos:
            lineas.extend(self.datos)
        else:
            lineas.append('    # (sin literales de datos todavia)')
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
        lineas.append('')

        return '\n'.join(lineas)

    def _generar_funcion(self, nodo):
        # nodo = ('funcion', nombre, parametros, tipo_retorno, cuerpo)
        nombre = nodo[1]
        cuerpo = nodo[4]

        self.texto.append(f'{nombre}:')
        # Prologo: guardamos frame pointer (x29) y link register (x30)
        self.texto.append('    stp x29, x30, [sp, -16]!')
        self.texto.append('    mov x29, sp')

        for sentencia in cuerpo:
            self._generar_sentencia(sentencia)

        # Epilogo: restauramos y retornamos
        self.texto.append('    ldp x29, x30, [sp], 16')
        self.texto.append('    ret')
        self.texto.append('')

    def _generar_sentencia(self, sentencia):
        tipo = sentencia[0]
        self.texto.append(f'    # TODO: sentencia "{tipo}" aun no implementada')