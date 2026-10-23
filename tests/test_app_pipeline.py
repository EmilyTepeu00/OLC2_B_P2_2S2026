from backend.app import app

codigo_ok = """
fn sumar(a: i32, b: i32) -> i32 {
    return a + b;
}

fn main() {
    let x: i32 = 10;
    let resultado = sumar(x, 5);
    println!("Resultado: {}", resultado);

    let numeros = [1, 2, 3, 4, 5];
    println!("Primer elemento: {}", numeros[0]);

    let saludo = String::from("Hola desde la API");
    println!(saludo);
}
"""

codigo_con_error = """
fn main() {
    let x: i32 = "esto no es un entero";
    println!(x);
}
"""

cliente = app.test_client()

print('=== CASO 1: programa valido ===\n')
respuesta = cliente.post('/execute', json={'codigo': codigo_ok})
datos = respuesta.get_json()
print('HTTP status:', respuesta.status_code)
print('Errores:', datos.get('errores'))
print('Salida:', datos.get('salida'))
print('Tiempo:', datos.get('tiempo'))
print('Cantidad de simbolos:', len(datos.get('symbols', [])))
print('\n--- Primeras 15 lineas del codigo ARM64 generado ---')
print('\n'.join(datos.get('codigo_arm64', '').splitlines()[:15]))

esperado = ['Resultado: 15', 'Primer elemento: 1', 'Hola desde la API']
if datos.get('salida') == esperado:
    print('\nOK: la salida del endpoint coincide con lo esperado')
else:
    print(f'\nATENCION: no coincide. Esperado: {esperado}')

print('\n\n=== CASO 2: programa con error de tipos ===\n')
respuesta2 = cliente.post('/execute', json={'codigo': codigo_con_error})
datos2 = respuesta2.get_json()
print('HTTP status:', respuesta2.status_code)
print('Errores:', [e.get('formato') for e in datos2.get('errores', [])])
# Resiliencia: el error se reporta, la sentencia con error se omite y el resto del programa se ejecuta igual (x queda con su valor por defecto 0)
print('Salida (deberia ser [\'0\']):', datos2.get('salida'))
if datos2.get('salida') == ['0'] and len(datos2.get('errores', [])) == 1:
    print('OK: se reporto el error y el programa siguio ejecutando')
else:
    print('FALLO: se esperaba 1 error y la salida [\'0\']')
    raise SystemExit(1)