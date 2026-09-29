import subprocess
import os

from backend.parser import parsear
from backend.semantic import AnalizadorSemantico
from backend.codegen import GeneradorCodigo

codigo = """
fn main() {
    let x: i32 = 42;
    println!(x);

    let mut y = 7;
    println!("{}", y);

    y = 100;
    println!(y);

    let a = 5 + 3 * 2;
    println!(a);

    let b = (10 - 4) / 2;
    println!(b);

    let c = 17 % 5;
    println!(c);

    let d = 5 > 3;
    println!(d);

    let e = (2 == 2) && (3 < 1);
    println!(e);

    let f = (1 > 5) || (2 <= 2);
    println!(f);

    let mut g = 10;
    g += 5;
    g *= 2;
    g -= 3;
    println!(g);

    let x = 10;
    if x > 5 {
        let y = 1;
        println!(y);
    } else if x > 20 {
        println!(2);
    } else {
        println!(3);
    }
    println!(x);

    let s = 1;
    if s == 1 {
        let s = 2;
        println!(s);
    }
    println!(s);

    let t = 5;
    let t = t + 1;
    println!(t);

    let z: i32;
    println!(z);

    let mut i = 0;
    while i < 3 {
        println!(i);
        i += 1;
    }

    let mut n = 0;
    loop {
        n += 1;
        if n == 2 {
            continue;
        }
        if n > 4 {
            break;
        }
        println!(n);
    }

    let mut a1 = 0;
    'outer: loop {
        let mut b1 = 0;
        loop {
            b1 += 1;
            a1 += 1;
            if b1 == 2 {
                break 'outer;
            }
        }
    }
    println!(a1);

    let mut c1 = 0;
    let mut total = 0;
    'o2: loop {
        c1 += 1;
        if c1 > 3 {
            break;
        }
        let mut d1 = 0;
        loop {
            d1 += 1;
            if d1 > 2 {
                continue 'o2;
            }
            total += 1;
        }
    }
    println!(total);

    let numero = 32;
    match numero {
        1 => println!(100),
        2 => println!(200),
        _ => println!(999),
    }

    let otro = 2;
    match otro {
        1 => println!(100),
        2 => println!(200),
        _ => println!(999),
    }
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

    esperado = '42\n7\n100\n11\n3\n2\n1\n0\n1\n27\n1\n10\n2\n1\n6\n0\n0\n1\n2\n1\n3\n4\n2\n6\n999\n200\n'
    if resultado.stdout == esperado and resultado.returncode == 0:
        print('\nOK: la salida coincide con lo esperado (42 / 7 / 100)')
    else:
        print(f'\nATENCION: no coincide. Esperado: {esperado!r}')

limpiar()