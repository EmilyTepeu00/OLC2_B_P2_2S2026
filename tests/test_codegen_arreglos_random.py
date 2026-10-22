import subprocess
import os

from backend.parser import parsear
from backend.semantic import AnalizadorSemantico
from backend.codegen import GeneradorCodigo

codigo = """
fn main() {
    let mut numeros = [10, 20, 30];
    numeros.reverse();
    println!(numeros);

    let mut cinco = [1, 2, 3, 4, 5];
    cinco.reverse();
    println!(cinco);
    cinco.reverse();
    println!(cinco[0]);

    let mut m: [[i32; 2]; 3] = [[1, 2], [3, 4], [5, 6]];
    m.reverse();
    println!(m);

    let mut f = [1.5, 2.5, 3.5, 4.5];
    f.reverse();
    println!(f);

    println!(numeros.contains(20));
    println!(numeros.contains(99));
    println!(f.contains(2.5));
    println!(f.contains(7.5));
    println!(f.contains(2));
    let letras = ['a', 'b', 'c'];
    println!(letras.contains('b'));
    println!(letras.contains('z'));
    let flags = [true, false];
    println!(flags.contains(false));
    println!(m.contains(4));

    println!(random(5, 5));
    println!(random(-2, -2));

    let mut fuera = 0;
    let mut i = 0;
    while i < 200 {
        let r = random(1, 10);
        if r < 1 || r > 10 {
            fuera += 1;
        }
        i += 1;
    }
    println!(fuera);

    let mut cuenta = [0, 0, 0];
    let mut j = 0;
    while j < 300 {
        let v = random(0, 2);
        cuenta[v] = cuenta[v] + 1;
        j += 1;
    }
    println!(cuenta[0] > 0 && cuenta[1] > 0 && cuenta[2] > 0);
    println!(cuenta[0] + cuenta[1] + cuenta[2]);

    let n = random(-3, 3);
    println!(n >= -3 && n <= 3);
    println!(typeof(random(1, 2)));
}
"""

ESPERADO = '[30, 20, 10]\n[5, 4, 3, 2, 1]\n1\n[[5, 6], [3, 4], [1, 2]]\n[4.5, 3.5, 2.5, 1.5]\ntrue\nfalse\ntrue\nfalse\nfalse\ntrue\nfalse\ntrue\ntrue\n5\n-2\n0\ntrue\n300\ntrue\ni32\n'

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

    esperado = ESPERADO
    if resultado.stdout == esperado and resultado.returncode == 0:
        print('\nOK: la salida coincide con lo esperado')
    else:
        print(f'\nATENCION: no coincide. Esperado: {esperado!r}')

limpiar()