# OxigenNative

Compilador de **OxigenNative**, un lenguaje de programación académico con sintaxis inspirada en Rust. Es el **Proyecto 2** del curso **Organización de Lenguajes y Compiladores 2**. Continúa el trabajo del Proyecto 1 (OxigenScript), pero en lugar de interpretar el código, lo compila.

A diferencia de un intérprete, que ejecuta el programa directamente mientras lo lee, un compilador lo traduce a otro lenguaje. Aquí, el código escrito en OxigenNative se traduce a **ensamblador ARM64**, el lenguaje de bajo nivel de los procesadores ARM. Ese ensamblador se convierte en un programa ejecutable real y se corre dentro del servidor con QEMU, un emulador que permite ejecutar programas ARM64 en una computadora normal.

El recorrido completo de un programa es:

1. Se revisa que el código esté bien escrito y que tenga sentido (variables declaradas, tipos compatibles, etc.).
2. Se traduce a ensamblador ARM64.
3. El ensamblador se convierte en un ejecutable.
4. El ejecutable se corre con QEMU y se captura lo que imprime.

Todo se usa desde una página web con un editor de código donde se puede escribir un programa o abrir uno existente, guardarlo y ejecutarlo. La pantalla muestra:

- **Consola de salida**: el resultado de la ejecución del programa.
- **Código ARM64 generado**: el ensamblador que produjo el compilador, el mismo que se ejecuta en el servidor.
- **Reportes**, en pestañas:
  - **Errores**: los problemas encontrados en el código, indicando el tipo (léxico, sintáctico o semántico), la descripción, la línea y la columna.
  - **Tabla de símbolos**: las variables, funciones y structs declarados, con su tipo, su ámbito y su valor.
  - **AST**: una imagen del árbol que representa la estructura del programa.

## Cómo correrlo

> Para ejecutar los programas generados hacen falta, además de Python y Node.js, las herramientas de ARM64 instaladas en Linux: el ensamblador y enlazador `aarch64-linux-gnu` (paquete `binutils-aarch64-linux-gnu`) y `qemu-aarch64` (paquete `qemu-user`). Para el reporte del AST también debe estar instalado Graphviz.

Primera vez, desde la raíz del repositorio:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd frontend
npm install
```

Para ejecutarlo se usan dos terminales.

Backend:

```bash
PYTHONPATH=. python3 backend/app.py
```

Frontend:

```bash
cd frontend
npm run dev
```

Después se abre en el navegador `http://localhost:5173`.
