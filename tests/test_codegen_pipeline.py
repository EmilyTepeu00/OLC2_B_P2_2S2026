import subprocess
import os

from backend.parser import parsear
from backend.semantic import AnalizadorSemantico
from backend.codegen import GeneradorCodigo

codigo = """
fn main() {
}
"""

RUTA_S = 'salida_test.s'
RUTA_O = 'salida_test.o'
RUTA_BIN = 'salida_test'


def limpiar():
    for ruta in (RUTA_S, RUTA_O, RUTA_BIN):
        if os.path.exists(ruta):
            os.remove(ruta)


ast, errores_parseo, errores_lexicos, lineas, columnas = parsear(codigo)

if errores_lexicos or errores_parseo:
    print('Errores de lexico/parseo (no deberia haber ninguno):')
    for e in errores_lexicos:
        print(f'  {e}')
    for e in errores_parseo:
        print(f'  {e}')
    raise SystemExit(1)

analizador = AnalizadorSemantico()
errores_semanticos = analizador.analizar(ast, lineas=lineas, columnas=columnas)

if errores_semanticos:
    print('Errores semanticos (no deberia haber ninguno):')
    for e in errores_semanticos:
        print(f'  {e}')
    raise SystemExit(1)

generador = GeneradorCodigo()
codigo_asm, errores_codegen = generador.generar(ast)

if errores_codegen:
    print('Errores de codegen (no deberia haber ninguno):')
    for e in errores_codegen:
        print(f'  {e}')
    raise SystemExit(1)

print('=== CODIGO ARM64 GENERADO ===\n')
print(codigo_asm)

limpiar()
with open(RUTA_S, 'w') as f:
    f.write(codigo_asm)

print('=== ENSAMBLANDO, ENLAZANDO Y EJECUTANDO CON QEMU ===\n')

pasos = [
    ['aarch64-linux-gnu-as', RUTA_S, '-o', RUTA_O],
    ['aarch64-linux-gnu-ld', '-static', RUTA_O, '-o', RUTA_BIN],
]

exito = True
for paso in pasos:
    resultado = subprocess.run(paso, capture_output=True, text=True)
    if resultado.returncode != 0:
        print(f'FALLO en: {" ".join(paso)}')
        print(resultado.stderr)
        exito = False
        break

if exito:
    resultado = subprocess.run(['qemu-aarch64', f'./{RUTA_BIN}'], capture_output=True, text=True)
    print(f'Codigo de salida: {resultado.returncode}')
    print(f'Stdout: {resultado.stdout!r}')
    print(f'Stderr: {resultado.stderr!r}')

    if resultado.returncode == 0:
        print('\nOK: el pipeline completo (compilador propio -> ARM64 -> QEMU) funciona')
    else:
        print('\nATENCION: el binario corrio pero con codigo de salida distinto de 0')

limpiar()