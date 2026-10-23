# --- ANALISIS SEMANTICO ---
# TABLA DE SIMBOLOS Y VALIDACION DE TIPOS

NUMERICOS = ('i32', 'f64')

class Simbolo:
    def __init__(self, nombre, tipo_simbolo, tipo_dato, mutable=False, valor=None):
        self.nombre = nombre
        self.tipo_simbolo = tipo_simbolo  # 'variable', 'funcion', 'estructura'
        self.tipo_dato = tipo_dato        # 'i32', 'f64', 'bool', 'char', 'String', '[i32]', 'None'
        self.mutable = mutable
        self.valor = valor
        self.parametros = None      # Para funciones
        self.tipo_retorno = None    # Para funciones
        self.linea = None           # Linea real donde se declaro (para la de tabla de simbolos)
        self.forma = None           # Dimensiones si es un arreglo de tamaño conocido: [filas, columnas, ...]
        self.tipo_texto = None      # Tipo como se escribe en el codigo ([i32; 5]) para el reporte

class TablaSimbolos:
    def __init__(self, padre=None, nombre_ambito='global'):
        self.simbolos = {}
        self.historial = []
        self.padre = padre
        self.hijos = []
        self.nombre_ambito = nombre_ambito  # 'global' o el nombre de la funcion a la que pertenece este scope

    def agregar(self, nombre, simbolo, permitir_sombreado=True):
        # se puede sobreescribir en el mismo ambito, para funciones y structs
        #  se llama con permitir_sombreado=False.
        if nombre in self.simbolos and not permitir_sombreado:
            return False, f"Simbolo ya declarado: {nombre}"
        self.simbolos[nombre] = simbolo  # la que usan las busquedas normales (obtener)
        self.historial.append(simbolo)   # la que usa el reporte de tabla de simbolos
        return True, None

    def obtener(self, nombre):
        if nombre in self.simbolos:
            return self.simbolos[nombre], None
        if self.padre:
            return self.padre.obtener(nombre)
        return None, f"Simbolo no encontrado: {nombre}"

    def crear_hijo(self):
        hijo = TablaSimbolos(self, nombre_ambito=self.nombre_ambito)
        self.hijos.append(hijo)
        return hijo

class AnalizadorSemantico:
    EMBEBIDAS = ('println', 'typeof', 'random', 'len', 'contains',
                 'replace', 'split', 'to_uppercase', 'to_lowercase', 'reverse')

    def __init__(self):
        self.tabla_global = TablaSimbolos()
        self.tabla_actual = self.tabla_global
        self.errores = []
        self.lineas = {}                    # id(nodo) -> numero de linea (viene del parser)
        self.columnas = {}                  # id(nodo) -> columna (viene del parser)
        self.linea_actual = 0               # ultima linea conocida, se actualiza al recorrer sentencias
        self.columna_actual = None          # ultima columna conocida
        self.structs = {}                   # nombre_struct -> {nombre_campo: tipo_campo}
        self.sentencias_omitidas = set()    # id(sentencia) que el generador de codigo no debe emitir
        self.sentencia_actual = None
        self.funcion_actual = None

    def _linea_de(self, nodo):
        # Devuelve la linea real de un nodo si esta registrada o la ultima linea conocida y actualiza self.columna_actual
        if isinstance(nodo, tuple) and id(nodo) in self.lineas:
            self.linea_actual = self.lineas[id(nodo)]
            self.columna_actual = self.columnas.get(id(nodo))
        return self.linea_actual

    def _posicion(self, nodo):
        # (linea, columna) del nodo si el parser la registró, si no la de la sentencia actual
        if isinstance(nodo, tuple) and id(nodo) in self.lineas:
            return self.lineas[id(nodo)], self.columnas.get(id(nodo))
        return self.linea_actual, self.columna_actual

    def _error(self, mensaje, nodo=None, fatal=False):
        linea, columna = self._posicion(nodo)
        self.errores.append({
            'tipo': 'Semantico',
            'linea': linea,
            'columna': columna,
            'mensaje': mensaje,
        })
        if fatal and self.sentencia_actual is not None:
            self.sentencias_omitidas.add(id(self.sentencia_actual))

    def _normalizar_tipo(self, tipo):
        # "[T; N]" llega del parser como la tupla ('array', T, N), donde T puede tambien otra tupla ('array', ...) para arreglos multidimensionales
        if isinstance(tipo, tuple) and tipo[0] == 'array':
            return f'[{self._normalizar_tipo(tipo[1])}]'
        return tipo

    def _texto_tipo(self, tipo):
        # Tipo legible para el reporte: ('array', 'i32', 5) -> "[i32; 5]"
        if isinstance(tipo, tuple) and tipo[0] == 'array':
            return f'[{self._texto_tipo(tipo[1])}; {tipo[2]}]'
        return tipo

    def _forma_de_tipo(self, tipo):
        forma = []
        while isinstance(tipo, tuple) and tipo[0] == 'array':
            forma.append(tipo[2])
            tipo = tipo[1]
        return forma or None

    def _forma_de_valor(self, valor):
        forma = []
        actual = valor
        while isinstance(actual, tuple) and actual[0] in ('array_literal', 'array_repeat'):
            if actual[0] == 'array_literal':
                forma.append(len(actual[1]))
                actual = actual[1][0] if actual[1] else None
            else:
                forma.append(actual[2])
                actual = actual[1]
        return forma or None

    def analizar(self, ast, lineas=None, columnas=None):
        self.errores = []
        self.lineas = lineas or {}
        self.columnas = columnas or {}
        self.linea_actual = 0
        self.columna_actual = None
        self.structs = {}
        self.sentencias_omitidas = set()
        programa = ast

        # PRIMERA PASADA: registrar todas las funciones y structs
        for funcion in programa[1]:
            if funcion[0] == 'struct':
                self.structs[funcion[1]] = dict(funcion[2])
            elif funcion[0] == 'funcion':
                self._registrar_funcion(funcion)

        # SEGUNDA PASADA: analizar el cuerpo de las funciones
        for funcion in programa[1]:
            if funcion[0] == 'funcion':
                self._analizar_funcion(funcion)

        return self.errores

    def _registrar_funcion(self, nodo_funcion):
        nombre = nodo_funcion[1]
        parametros = nodo_funcion[2]
        tipo_retorno = nodo_funcion[3] if len(nodo_funcion) > 3 else None

        simbolo = Simbolo(nombre, 'funcion', self._normalizar_tipo(tipo_retorno))
        simbolo.parametros = parametros
        simbolo.tipo_retorno = self._normalizar_tipo(tipo_retorno)
        simbolo.tipo_texto = self._texto_tipo(tipo_retorno)
        simbolo.forma = self._forma_de_tipo(tipo_retorno)
        simbolo.linea = self._linea_de(nodo_funcion)

        ok, error = self.tabla_global.agregar(nombre, simbolo, permitir_sombreado=False)
        if not ok:
            self._error(f"La función '{nombre}' ya fue declarada.", nodo_funcion)

    def _analizar_funcion(self, nodo_funcion):
        nombre = nodo_funcion[1]
        parametros = nodo_funcion[2]
        cuerpo = nodo_funcion[4] if len(nodo_funcion) > 4 else []
        linea_funcion = self._linea_de(nodo_funcion)
        self.funcion_actual = nombre
        self.sentencia_actual = None

        # Crear ambito para la funcion
        nueva_tabla = TablaSimbolos(self.tabla_global, nombre_ambito=nombre)
        self.tabla_global.hijos.append(nueva_tabla)
        self.tabla_actual = nueva_tabla

        # Registrar parametros como variables
        for nom_param, tipo_param in parametros:
            # El tipo "[T; N]" llega del parser como la tupla y se normaliza a "[T]" que usa el tipo INFERIDO de un arreglo literal
            simbolo = Simbolo(nom_param, 'variable', self._normalizar_tipo(tipo_param), True)
            simbolo.forma = self._forma_de_tipo(tipo_param)
            simbolo.tipo_texto = self._texto_tipo(tipo_param)
            simbolo.linea = linea_funcion
            self.tabla_actual.agregar(nom_param, simbolo)

        # Analizar cuerpo
        self.linea_actual = linea_funcion
        for sentencia in cuerpo:
            self._analizar_sentencia(sentencia)

        # Volver al ambito anterior
        self.tabla_actual = self.tabla_actual.padre

    def _analizar_sentencia(self, sentencia):
        if not isinstance(sentencia, tuple) or not sentencia:
            return
        anterior = self.sentencia_actual
        self.sentencia_actual = sentencia
        self._linea_de(sentencia)  # actualiza self.linea_actual para los errores de esta sentencia
        tipo = sentencia[0]
        if tipo == 'let':
            self._analizar_let(sentencia)
        elif tipo == 'asignar':
            self._analizar_asignacion(sentencia)
        elif tipo == 'asignar_indice':
            self._analizar_asignar_indice(sentencia)
        elif tipo == 'asignar_campo':
            self._analizar_expresion(sentencia[1])
            self._analizar_expresion(sentencia[3])
        elif tipo == 'if':
            self._analizar_if(sentencia)
        elif tipo == 'while':
            self._analizar_while(sentencia)
        elif tipo == 'loop':
            self._analizar_loop(sentencia)
        elif tipo == 'match':
            self._analizar_match(sentencia)
        elif tipo == 'bloque':
            self._analizar_bloque(sentencia)
        elif tipo == 'return':
            self._analizar_retorno(sentencia)
        elif tipo in ('break', 'continue', 'error_stmt'):
            pass
        else:
            # Sentencia de tipo expresion: llamada, binop, etc.
            self._analizar_expresion(sentencia)
        self.sentencia_actual = anterior

    def _analizar_let(self, nodo_let):
        nombre = nodo_let[1]
        tipo_original = nodo_let[2]
        valor = nodo_let[3]
        mutable = nodo_let[4]

        # El tipo declarado como "[T; N]" llega al parser como la tupla
        # El tipo inferido de un arreglo literal se calcula como el string "[T]"
        tipo = self._normalizar_tipo(tipo_original)
        forma = self._forma_de_tipo(tipo_original)

        # Si tiene valor, validar la expresion y obtener su tipo
        tipo_valor = None
        if valor is not None:
            self._analizar_expresion(valor)
            tipo_valor = self._obtener_tipo_expresion(valor)
            if forma is None:
                forma = self._forma_de_valor(valor) or self._forma_de_expresion(valor)

        # Si no tiene tipo, inferir del valor
        if tipo is None and valor is not None:
            tipo = tipo_valor

        # Si tiene tipo y valor, validar compatibilidad
        if tipo is not None and valor is not None and tipo_valor is not None and tipo_valor != 'None':
            if not self._es_asignable(tipo, tipo_valor):
                self._error(
                    f"No es posible asignar un valor de tipo {tipo_valor} a una variable de tipo {tipo}.",
                    valor, fatal=True)

        simbolo = Simbolo(nombre, 'variable', tipo, mutable, valor)
        simbolo.forma = forma
        simbolo.tipo_texto = self._texto_tipo(tipo_original) if tipo_original is not None else tipo
        simbolo.linea = self.linea_actual
        self.tabla_actual.agregar(nombre, simbolo)

    def _analizar_asignacion(self, nodo_asign):
        nombre = nodo_asign[1]
        valor = nodo_asign[2]

        # Verificar que la variable exista
        simbolo, error = self.tabla_actual.obtener(nombre)
        if error or simbolo.tipo_simbolo != 'variable':
            self._error(f"La variable '{nombre}' no ha sido declarada.", fatal=True)
            self._analizar_expresion(valor)
            return

        # Verificar que sea mutable
        if not simbolo.mutable:
            self._error(
                f"No es posible modificar la variable '{nombre}' porque fue declarada como inmutable.",
                fatal=True)
            return

        # Validar la expresion
        self._analizar_expresion(valor)

        # Validar compatibilidad de tipos
        tipo_var = simbolo.tipo_dato
        tipo_valor = self._obtener_tipo_expresion(valor)

        if tipo_var not in (None, 'None') and tipo_valor not in (None, 'None'):
            if not self._es_asignable(tipo_var, tipo_valor):
                self._error(
                    f"No es posible asignar un valor de tipo {tipo_valor} a una variable de tipo {tipo_var}.",
                    valor, fatal=True)

    def _analizar_asignar_indice(self, sentencia):
        base, indice, valor = sentencia[1], sentencia[2], sentencia[3]
        acceso = ('array_access', base, indice)
        nombre, indices = self._descomponer_acceso(acceso)
        if nombre is not None:
            simbolo, error = self.tabla_actual.obtener(nombre)
            if error:
                self._error(f"La variable '{nombre}' no ha sido declarada.", fatal=True)
                return
            # No se exige "mut" para modificar un elemento
            self._verificar_limites(nombre, indices, acceso)
        for indice_nodo in (indices or [indice]):
            self._analizar_expresion(indice_nodo)
        self._analizar_expresion(valor)

    def _analizar_if(self, nodo_if):
        condicion = nodo_if[1]
        cuerpo_entonces = nodo_if[2]
        cuerpo_sino = nodo_if[3] if len(nodo_if) > 3 else None

        # Validar que la condicion sea bool
        self._analizar_expresion(condicion)
        tipo_cond = self._obtener_tipo_expresion(condicion)
        if tipo_cond is not None and tipo_cond != 'bool':
            self._error(f"La condición del if debe ser de tipo bool, pero es {tipo_cond}.", condicion)

        # Nuevo ambito para el bloque
        self.tabla_actual = self.tabla_actual.crear_hijo()
        for sentencia in cuerpo_entonces:
            self._analizar_sentencia(sentencia)
        self.tabla_actual = self.tabla_actual.padre

        if cuerpo_sino:
            if isinstance(cuerpo_sino, tuple) and cuerpo_sino[0] == 'if':
                self._analizar_sentencia(cuerpo_sino)
            else:
                self.tabla_actual = self.tabla_actual.crear_hijo()
                for sentencia in cuerpo_sino:
                    self._analizar_sentencia(sentencia)
                self.tabla_actual = self.tabla_actual.padre

    def _analizar_while(self, nodo_while):
        condicion = nodo_while[1]
        cuerpo = nodo_while[2]

        # Validar que la condicion sea bool
        self._analizar_expresion(condicion)
        tipo_cond = self._obtener_tipo_expresion(condicion)
        if tipo_cond is not None and tipo_cond != 'bool':
            self._error(f"La condición del while debe ser de tipo bool, pero es {tipo_cond}.", condicion)

        self.tabla_actual = self.tabla_actual.crear_hijo()
        for sentencia in cuerpo:
            self._analizar_sentencia(sentencia)
        self.tabla_actual = self.tabla_actual.padre

    def _analizar_loop(self, nodo_loop):
        cuerpo = nodo_loop[2]
        self.tabla_actual = self.tabla_actual.crear_hijo()
        for sentencia in cuerpo:
            self._analizar_sentencia(sentencia)
        self.tabla_actual = self.tabla_actual.padre

    def _analizar_match(self, nodo_match):
        expresion = nodo_match[1]
        casos = nodo_match[2]
        self._analizar_expresion(expresion)
        tiene_comodin = any(caso[1] == 'default' for caso in casos)
        if not tiene_comodin:
            self._error("El match debe incluir el caso comodín '_'.", expresion)
        for caso in casos:
            self.tabla_actual = self.tabla_actual.crear_hijo()
            for sentencia in caso[2]:
                self._analizar_sentencia(sentencia)
            self.tabla_actual = self.tabla_actual.padre

    def _analizar_bloque(self, nodo_bloque):
        cuerpo = nodo_bloque[1]
        self.tabla_actual = self.tabla_actual.crear_hijo()
        for sentencia in cuerpo:
            self._analizar_sentencia(sentencia)
        self.tabla_actual = self.tabla_actual.padre

    def _analizar_retorno(self, nodo_retorno):
        valor = nodo_retorno[1]
        if valor:
            self._analizar_expresion(valor)

    def _analizar_llamada(self, nodo_llamada):
        nombre = nodo_llamada[1]
        argumentos = nodo_llamada[2]

        # Funciones embebidas: solo se validan sus argumentos
        if nombre in self.EMBEBIDAS:
            for arg in argumentos:
                self._analizar_expresion(arg)
            return

        for arg in argumentos:
            self._analizar_expresion(arg)

        # Verificar que la funcion exista
        simbolo, error = self.tabla_global.obtener(nombre)
        if error or simbolo.tipo_simbolo != 'funcion':
            self._error(f"La función '{nombre}' no ha sido declarada.", nodo_llamada, fatal=True)
            return

        # Validar numero de argumentos
        if simbolo.parametros is not None and len(argumentos) != len(simbolo.parametros):
            self._error(
                f"La función '{nombre}' esperaba {len(simbolo.parametros)} argumentos, "
                f"pero recibió {len(argumentos)}.",
                nodo_llamada, fatal=True)

    def _analizar_variable(self, nodo_var):
        nombre = nodo_var[1]
        simbolo, error = self.tabla_actual.obtener(nombre)
        if error or simbolo.tipo_simbolo != 'variable':
            self._error(f"La variable '{nombre}' no ha sido declarada.", nodo_var, fatal=True)

    def _es_literal_cadena(self, nodo):
        return isinstance(nodo, tuple) and nodo[0] == 'string'

    def _error_operador(self, operador, izquierda, derecha, tipo_izq, tipo_der, nodo):
        # Un literal "texto" mezclado con un numero usa el mensaje de "tipos incompatibles" del enunciado
        if self._es_literal_cadena(derecha) and tipo_izq in NUMERICOS:
            self._error(
                f"Tipos incompatibles. No es posible utilizar un valor de tipo {tipo_der} "
                f"donde se esperaba un valor de tipo {tipo_izq}.", nodo)
        elif self._es_literal_cadena(izquierda) and tipo_der in NUMERICOS:
            self._error(
                f"Tipos incompatibles. No es posible utilizar un valor de tipo {tipo_izq} "
                f"donde se esperaba un valor de tipo {tipo_der}.", nodo)
        else:
            self._error(
                f"No es posible aplicar el operador '{operador}' entre los tipos {tipo_izq} y {tipo_der}.", nodo)

    def _analizar_binario(self, nodo_binario):
        operador = nodo_binario[1]
        izquierda = nodo_binario[2]
        derecha = nodo_binario[3]

        # Primero las sub expresiones (asi los errores salen en el orden en que aparecen)
        self._analizar_expresion(izquierda)
        self._analizar_expresion(derecha)

        tipo_izq = self._obtener_tipo_expresion(izquierda)
        tipo_der = self._obtener_tipo_expresion(derecha)

        # Si un lado ya es None o desconocido, el error ya se reporto antes
        if tipo_izq in (None, 'None') or tipo_der in (None, 'None'):
            return
        if self._tipo_binario(operador, tipo_izq, tipo_der) == 'None':
            self._error_operador(operador, izquierda, derecha, tipo_izq, tipo_der, nodo_binario)

    def _analizar_unario(self, nodo_unario):
        operador = nodo_unario[1]
        operando = nodo_unario[2]
        self._analizar_expresion(operando)
        tipo_op = self._obtener_tipo_expresion(operando)
        if tipo_op in (None, 'None'):
            return
        if operador == '!' and tipo_op != 'bool':
            self._error(f"No es posible aplicar el operador '!' al tipo {tipo_op}.", nodo_unario)
        elif operador == '-' and tipo_op not in NUMERICOS:
            self._error(f"No es posible aplicar el operador '-' al tipo {tipo_op}.", nodo_unario)

    def _descomponer_acceso(self, nodo):
        # matrix[1][2] -> ('matrix', [1, 2]); (None, None) si la base no es una variable
        indices = []
        actual = nodo
        while isinstance(actual, tuple) and actual[0] == 'array_access':
            indices.append(actual[2])
            actual = actual[1]
        if not (isinstance(actual, tuple) and actual[0] == 'var'):
            return None, None
        indices.reverse()
        return actual[1], indices

    def _verificar_limites(self, nombre, indices, nodo):
        # Solo se puede verificar en compilacion cuando el indice es un literal y la forma del arreglo se conoce
        simbolo, error = self.tabla_actual.obtener(nombre)
        if error or not simbolo.forma:
            return
        for nivel, indice in enumerate(indices):
            if nivel >= len(simbolo.forma):
                break
            valor = None
            if isinstance(indice, tuple) and indice[0] == 'literal' and isinstance(indice[1], int):
                valor = indice[1]
            elif (isinstance(indice, tuple) and indice[0] == 'unop' and indice[1] == '-'
                  and indice[2][0] == 'literal' and isinstance(indice[2][1], int)):
                valor = -indice[2][1]
            if valor is not None and (valor < 0 or valor >= simbolo.forma[nivel]):
                self._error("Índice fuera de los límites del arreglo.", nodo, fatal=True)
                return

    def _analizar_expresion(self, expr):
        if not isinstance(expr, tuple) or not expr:
            return
        tipo = expr[0]
        if tipo == 'var':
            self._analizar_variable(expr)
        elif tipo == 'llamada':
            self._analizar_llamada(expr)
        elif tipo == 'binop':
            self._analizar_binario(expr)
        elif tipo == 'unop':
            self._analizar_unario(expr)
        elif tipo in ('literal', 'string', 'bool', 'char'):
            pass
        elif tipo == 'string_from':
            self._analizar_expresion(expr[1])
        elif tipo == 'array_literal':
            for elem in expr[1]:
                self._analizar_expresion(elem)
        elif tipo == 'array_repeat':
            self._analizar_expresion(expr[1])
        elif tipo == 'array_access':
            nombre, indices = self._descomponer_acceso(expr)
            if nombre is not None:
                simbolo, error = self.tabla_actual.obtener(nombre)
                if error:
                    self._error(f"La variable '{nombre}' no ha sido declarada.", expr, fatal=True)
                    return
                for indice in indices:
                    self._analizar_expresion(indice)
                    tipo_indice = self._obtener_tipo_expresion(indice)
                    if tipo_indice not in (None, 'None', 'i32'):
                        self._error(f"El índice de un arreglo debe ser de tipo i32, pero es {tipo_indice}.",
                                    indice, fatal=True)
                self._verificar_limites(nombre, indices, expr)
            else:
                self._analizar_expresion(expr[1])
                self._analizar_expresion(expr[2])
        elif tipo == 'array_slice':
            self._analizar_expresion(expr[1])
            self._analizar_expresion(expr[2])
            self._analizar_expresion(expr[3])
        elif tipo == 'struct_init':
            nombre_struct = expr[1]
            campos_dados = expr[2]
            campos_decl = self.structs.get(nombre_struct)
            if campos_decl is None:
                self._error(f"El struct '{nombre_struct}' no ha sido declarado.", expr, fatal=True)
            else:
                nombres_dados = set()
                for campo, val_expr in campos_dados:
                    self._analizar_expresion(val_expr)
                    nombres_dados.add(campo)
                    if campo not in campos_decl:
                        self._error(f"El struct '{nombre_struct}' no tiene el campo '{campo}'.", expr)
                    else:
                        tipo_campo = self._normalizar_tipo(campos_decl[campo])
                        tipo_val = self._obtener_tipo_expresion(val_expr)
                        if tipo_val is not None and not self._es_asignable(tipo_campo, tipo_val):
                            self._error(
                                f"No es posible asignar un valor de tipo {tipo_val} al campo '{campo}' "
                                f"de tipo {tipo_campo}.", val_expr)
                faltantes = set(campos_decl.keys()) - nombres_dados
                if faltantes:
                    self._error(f"Faltan campos al inicializar '{nombre_struct}': {', '.join(sorted(faltantes))}.",
                                expr)
        elif tipo == 'field_access':
            self._analizar_expresion(expr[1])
            tipo_base = self._obtener_tipo_expresion(expr[1])
            if tipo_base is not None and tipo_base in self.structs:
                if expr[2] not in self.structs[tipo_base]:
                    self._error(f"El struct '{tipo_base}' no tiene el campo '{expr[2]}'.", expr)

    def _forma_de_expresion(self, expr):
        # Forma de un arreglo que viene de una variable, de una llamada o de un slice con limites literales
        if not isinstance(expr, tuple):
            return None
        if expr[0] == 'var':
            simbolo, error = self.tabla_actual.obtener(expr[1])
            return simbolo.forma if not error else None
        if expr[0] == 'llamada':
            simbolo, error = self.tabla_global.obtener(expr[1])
            return simbolo.forma if not error and simbolo.tipo_simbolo == 'funcion' else None
        if expr[0] == 'array_slice':
            base = self._forma_de_expresion(expr[1])
            ini, fin = expr[2], expr[3]
            if base and ini[0] == 'literal' and fin[0] == 'literal':
                return [max(fin[1] - ini[1], 0)] + base[1:]
        return None

    # TIPO RESULTANTE DE UN OPERADOR BINARIO 
    # 'None' si la combinacion no es valida
    def _tipo_binario(self, operador, tipo_izq, tipo_der):
        if operador == '+':
            if tipo_izq == 'String' and tipo_der == 'String':
                return 'String'
            if tipo_izq in NUMERICOS and tipo_der in NUMERICOS:
                return 'f64' if 'f64' in (tipo_izq, tipo_der) else 'i32'
            return 'None'
        if operador in ('-', '/', '%'):
            if tipo_izq in NUMERICOS and tipo_der in NUMERICOS:
                return 'f64' if 'f64' in (tipo_izq, tipo_der) else 'i32'
            return 'None'
        if operador == '*':
            if tipo_izq in NUMERICOS and tipo_der in NUMERICOS:
                return 'f64' if 'f64' in (tipo_izq, tipo_der) else 'i32'
            if (tipo_izq, tipo_der) in (('i32', 'String'), ('String', 'i32')):
                return 'String'
            return 'None'
        if operador in ('==', '!=', '>', '<', '>=', '<='):
            validos = (
                (tipo_izq in NUMERICOS and tipo_der in NUMERICOS)
                or (tipo_izq, tipo_der) in (('i32', 'char'), ('char', 'i32'), ('char', 'char'),
                                            ('bool', 'bool'), ('String', 'String'))
            )
            return 'bool' if validos else 'None'
        if operador in ('&&', '||'):
            return 'bool' if tipo_izq == 'bool' and tipo_der == 'bool' else 'None'
        return 'None'

    # OBTENER EL TIPO DE LA EXPRESION
    def _obtener_tipo_expresion(self, expr):
        if not isinstance(expr, tuple) or not expr:
            return None
        tipo = expr[0]
        if tipo == 'literal':
            return 'i32' if isinstance(expr[1], int) else 'f64'
        elif tipo in ('string', 'string_from'):
            return 'String'
        elif tipo == 'bool':
            return 'bool'
        elif tipo == 'char':
            return 'char'
        elif tipo == 'array_literal':
            if expr[1]:
                tipo_elem = self._obtener_tipo_expresion(expr[1][0])
                return f'[{tipo_elem}]' if tipo_elem else None
            return None
        elif tipo == 'array_repeat':
            tipo_elem = self._obtener_tipo_expresion(expr[1])
            return f'[{tipo_elem}]' if tipo_elem else None
        elif tipo == 'array_access':
            tipo_base = self._obtener_tipo_expresion(expr[1])
            if isinstance(tipo_base, str) and tipo_base.startswith('[') and tipo_base.endswith(']'):
                return tipo_base[1:-1]
            if tipo_base == 'array':
                return 'String'  # pieza de un split
            return None
        elif tipo == 'array_slice':
            return self._obtener_tipo_expresion(expr[1])
        elif tipo == 'struct_init':
            return expr[1]  # el "tipo" de una instancia es el nombre del struct
        elif tipo == 'field_access':
            tipo_base = self._obtener_tipo_expresion(expr[1])
            if tipo_base and tipo_base in self.structs:
                return self._normalizar_tipo(self.structs[tipo_base].get(expr[2]))
            return None
        elif tipo == 'var':
            simbolo, error = self.tabla_actual.obtener(expr[1])
            if not error:
                return simbolo.tipo_dato
            return None
        elif tipo == 'binop':
            tipo_izq = self._obtener_tipo_expresion(expr[2])
            tipo_der = self._obtener_tipo_expresion(expr[3])
            if tipo_izq is None or tipo_der is None:
                return None
            if 'None' in (tipo_izq, tipo_der):
                return 'None'
            return self._tipo_binario(expr[1], tipo_izq, tipo_der)
        elif tipo == 'unop':
            tipo_op = self._obtener_tipo_expresion(expr[2])
            if tipo_op is None:
                return None
            if expr[1] == '!':
                return 'bool' if tipo_op == 'bool' else 'None'
            return tipo_op if tipo_op in NUMERICOS else 'None'
        elif tipo == 'llamada':
            nombre = expr[1]
            if nombre in ('len', 'random'):
                return 'i32'
            elif nombre == 'println':
                return None
            elif nombre in ('typeof', 'to_uppercase', 'to_lowercase', 'replace'):
                return 'String'
            elif nombre == 'contains':
                return 'bool'
            elif nombre in ('split', 'reverse'):
                return 'array'
            else:
                simbolo, error = self.tabla_global.obtener(nombre)
                if not error:
                    return simbolo.tipo_retorno
        return None

    # VERIFICAR SI UN VALOR DE tipo_valor SE PUEDE GUARDAR EN UNA VARIABLE DE tipo_destino
    def _es_asignable(self, tipo_destino, tipo_valor):
        if tipo_destino is None or tipo_valor is None:
            return True
        if tipo_destino == tipo_valor:
            return True
        # i32 se promueve a f64
        if tipo_destino == 'f64' and tipo_valor == 'i32':
            return True
        return False

    # VERIFICAR SI LOS TIPOS SON COMPATIBLES (se conserva para quien lo use desde fuera)
    def _son_tipos_compatibles(self, tipo1, tipo2):
        if tipo1 is None or tipo2 is None:
            return True
        if tipo1 == tipo2:
            return True
        if {tipo1, tipo2} in ({'f64', 'i32'}, {'i32', 'char'}):
            return True
        return False