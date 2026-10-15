import subprocess
import os

from backend.parser import parsear
from backend.semantic import AnalizadorSemantico
from backend.codegen import GeneradorCodigo

codigo = """
fn marca(etiqueta: String) -> bool {
    println!("marca: {}", etiqueta);
    return true;
}

fn saludo() -> String {
    return String::from("hola");
}

fn hanoi_move(n: i32, origen: char, auxiliar: char, destino: char) {
    if n == 1 {
        println!("mover disco 1 de {} a {}", origen, destino);
    } else {
        hanoi_move(n - 1, origen, destino, auxiliar);
        println!("mover disco {} de {} a {}", n, origen, destino);
        hanoi_move(n - 1, auxiliar, origen, destino);
    }
}

fn main() {
    let grande = 100000;
    let negativo = -grande;
    println!("{} {}", grande, negativo);
    let ok = true;
    println!("{} {}", ok, !ok);
    println!("{}", 3 > 4);

    let c = 'A';
    println!("char: {}", c);
    let z = 'é';
    println!("{}", z);

    let vacio_s: String;
    let vacio_b: bool;
    println!("[{}] [{}]", vacio_s, vacio_b);

    let r = marca(String::from("etiqueta literal"));
    let s = saludo();
    println!("{} {}", s, s.len());
    let nombre = String::from("Ana");
    marca(nombre);

    println!(typeof(nombre));
    println!(typeof(c));
    println!(typeof(ok));
    println!(typeof(grande));

    let nums = [1, 2, 3];
    println!(nums);
    println!("{:?}", nums);
    let flags = [true, false];
    println!(flags);
    let letras = ['a', 'b'];
    println!(letras);
    let m = [[1, 2], [3, 4]];
    println!(m);
    println!(1, 2, 3);

    hanoi_move(2, 'A', 'B', 'C');
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

    esperado = '100000 -100000\ntrue false\nfalse\nchar: A\né\n[] [false]\nmarca: etiqueta literal\nhola 4\nmarca: Ana\nString\nchar\nbool\ni32\n[1, 2, 3]\n[1, 2, 3]\n[true, false]\n["a", "b"]\n[[1, 2], [3, 4]]\n1 2 3\nmover disco 1 de A a B\nmover disco 2 de A a C\nmover disco 1 de B a C\n'
    if resultado.stdout == esperado and resultado.returncode == 0:
        print('\nOK: la salida coincide con lo esperado')
    else:
        print(f'\nATENCION: no coincide. Esperado: {esperado!r}')

limpiar()