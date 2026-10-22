import subprocess
import os

from backend.parser import parsear
from backend.semantic import AnalizadorSemantico
from backend.codegen import GeneradorCodigo

codigo = """
fn saludar(nombre: String) {
    println!("Hola " + nombre);
}

fn main() {
    let a = String::from("Hola");
    let b = String::from(" Mundo");
    let c = a + b;
    println!(c);
    println!(a);
    println!(c.len());

    let d = c + String::from("!");
    println!(d);

    let r = 3 * String::from("ab");
    println!(r);
    let e = 0 * String::from("zz");
    println!("[{}]", e);

    println!(String::from("a") == String::from("a"));
    println!(a == b);
    println!(a != b);
    println!(String::from("abc") < String::from("abd"));
    println!(String::from("abc") < String::from("ab"));
    println!(String::from("ab") < String::from("abc"));
    println!(String::from("b") > String::from("abc"));
    println!(a <= a);
    println!(a >= b);

    saludar(String::from("Ana"));

    let mut acum = String::from("");
    let mut i = 0;
    while i < 3 {
        acum = acum + String::from("ab");
        i += 1;
    }
    println!(acum);
    println!(acum.len());

    println!("{} y {}", a + b, 2 * String::from("x"));
}
"""

ESPERADO = 'Hola Mundo\nHola\n10\nHola Mundo!\nababab\n[]\ntrue\nfalse\ntrue\ntrue\nfalse\ntrue\ntrue\ntrue\ntrue\nHola Ana\nababab\n6\nHola Mundo y xx\n'

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