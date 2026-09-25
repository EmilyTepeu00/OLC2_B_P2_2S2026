from backend.parser import parsear
from backend.semantic import AnalizadorSemantico
from backend.interpreter import Interprete

codigo = """
fn main() {
    let matrix: [[i32; 3]; 2] = [
        [1, 2, 3],
        [4, 5, 6]
    ];

    println!(matrix);
    println!("{}", matrix[0][0]);
    println!("{}", matrix[1][2]);

    matrix[1][2] = 7;
    println!("{}", matrix[1][2]);
    println!(matrix);

    let cubo: [[[i32; 2]; 2]; 2] = [
        [[1, 2], [3, 4]],
        [[5, 6], [7, 8]]
    ];

    println!("{}", cubo[0][1][0]);
    cubo[0][1][0] = 99;
    println!("{}", cubo[0][1][0]);
}
"""

ast, errores_parseo, errores_lexicos, lineas, columnas = parsear(codigo)

if errores_lexicos:
    print("Errores lexicos:")
    for e in errores_lexicos:
        print(f"  {e}")

if errores_parseo:
    print("Errores de parseo:")
    for e in errores_parseo:
        print(f"  {e['mensaje']}")
else:
    analizador = AnalizadorSemantico()
    errores = analizador.analizar(ast, lineas=lineas, columnas=columnas)

    if errores:
        print("Errores semanticos (no deberia haber ninguno):")
        for e in errores:
            print(f"  {e}")
    else:
        print("Semantico OK: 0 errores con arreglos multidimensionales\n")

        interprete = Interprete()
        salida, errores_ejecucion = interprete.ejecutar(ast, lineas=lineas)

        print("=== EJECUCION ===\n")
        if errores_ejecucion:
            print("Errores de ejecucion:")
            for e in errores_ejecucion:
                print(f"  {e}")
        else:
            print("Salida:")
            for linea in salida:
                print(f"  {linea}")

            esperado = [
                "[[1, 2, 3], [4, 5, 6]]",
                "1",
                "6",
                "7",
                "[[1, 2, 3], [4, 5, 7]]",
                "3",
                "99",
            ]
            if [str(l) for l in salida] == esperado:
                print("\nOK: la salida coincide con lo esperado")
            else:
                print("\nATENCION: la salida no coincide con lo esperado")
                print(f"  Esperado: {esperado}")
                print(f"  Obtenido: {[str(l) for l in salida]}")