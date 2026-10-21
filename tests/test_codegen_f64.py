import subprocess
import os

from backend.parser import parsear
from backend.semantic import AnalizadorSemantico
from backend.codegen import GeneradorCodigo

codigo = """
fn media(a: f64, b: f64) -> f64 {
    return (a + b) / 2.0;
}

fn cuadrado(x: f64) -> f64 {
    return x * x;
}

fn entero_a_f64() -> f64 {
    return 3;
}

fn main() {
    let a: f64 = 3.14;
    let b: f64 = 2.5;
    println!(a);
    println!("{}", a + b);
    println!(a - b);
    println!(a * 2.0);
    println!(10.0 / 4.0);
    println!(7.5 % 2.0);

    let c = 10;
    let d: f64 = 2.5;
    println!(c + d);
    println!(c * 5);
    println!(c / 4);

    let e: f64 = 5;
    println!(e);

    let p: f64;
    println!(p);
    println!(-1.5);
    println!(-0.25);
    println!(100.0);

    println!(a > b);
    println!(a == 3.14);
    println!(b >= 2.5);
    println!(a < b);
    println!(c > d);
    println!(a != b);

    println!(media(2.0, 3.0));
    println!(cuadrado(1.5));
    println!(media(1, 2));
    println!(entero_a_f64());

    let mut acum: f64 = 0.0;
    let mut i = 0;
    while i < 4 {
        acum += 0.5;
        i += 1;
    }
    println!(acum);
    acum *= 3.0;
    println!(acum);

    let arr = [1.5, 2.5, 3.0];
    println!(arr);
    println!(arr[1] + arr[2]);

    let mut mezcla: [f64; 2] = [1.5, 2];
    mezcla[1] = 4;
    println!(mezcla);

    println!(typeof(a));
    println!("valor: {} y {}", a, b);
    println!(1234567.891);
    println!(0.000001);
    let n = -a;
    println!(n);
}
"""

ESPERADO = '3.14\n5.64\n0.64\n6.28\n2.5\n1.5\n12.5\n50\n2\n5.0\n0.0\n-1.5\n-0.25\n100.0\ntrue\ntrue\ntrue\nfalse\ntrue\ntrue\n2.5\n2.25\n1.5\n3.0\n2.0\n6.0\n[1.5, 2.5, 3.0]\n5.5\n[1.5, 4.0]\nf64\nvalor: 3.14 y 2.5\n1234567.891\n0.000001\n-3.14\n'

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