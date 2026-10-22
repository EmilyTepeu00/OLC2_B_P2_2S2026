import subprocess
import os

from backend.parser import parsear
from backend.semantic import AnalizadorSemantico
from backend.codegen import GeneradorCodigo

codigo = """
fn main() {
    let texto = String::from("Hola Mundo");
    println!(texto.contains("Mundo"));
    println!(texto.contains("mundo"));
    println!(texto.contains(""));
    println!(texto.contains("Hola Mundo!"));

    println!(texto.replace("Mundo", "Rust"));
    println!(texto.replace("o", "00"));
    println!(texto.replace("Hola", ""));
    println!(texto.replace("zzz", "x"));

    println!(texto.to_uppercase());
    println!(texto.to_lowercase());

    let nuevo = texto.replace("Mundo", "Compiladores");
    println!(nuevo);
    println!(nuevo.len());
    println!(nuevo.to_uppercase().len());
    println!(texto.replace("Mundo", "x").to_uppercase());
    println!("{} / {}", texto.to_lowercase(), nuevo.to_uppercase());

    println!(texto.split(" "));

    let csv = String::from("a,b,,c");
    let p = csv.split(",");
    println!(p);
    println!(p.len());
    println!(p[0]);
    println!(p[3]);
    let mut i = 0;
    while i < p.len() {
        println!(p[i]);
        i += 1;
    }

    println!(String::from("uno--dos--tres").split("--"));
    println!(String::from("abc").split("x"));
    println!(String::from("x-").split("-"));
}
"""

ESPERADO = 'true\nfalse\ntrue\nfalse\nHola Rust\nH00la Mund00\n Mundo\nHola Mundo\nHOLA MUNDO\nhola mundo\nHola Compiladores\n17\n17\nHOLA X\nhola mundo / HOLA COMPILADORES\n["Hola", "Mundo"]\n["a", "b", "", "c"]\n4\na\nc\na\nb\n\nc\n["uno", "dos", "tres"]\n["abc"]\n["x", ""]\n'

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