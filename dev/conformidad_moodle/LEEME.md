# Conformidad con Moodle (para probar a mano, opcional)

Generado por `dev/generar_conformidad_moodle.py`. Importa `conformidad_moodle.xml` en un curso de pruebas
(Banco de preguntas → Importar → «Formato XML de Moodle», categoría nueva) **dejando «Detenerse en error = Sí»**:
deben importarse las **10 preguntas**. Con la 1.9 este archivo no se importaba (P03). Al terminar, borra la
categoría «PRUEBA-conformidad (borrar)».

Qué debe verse en la vista previa de cada pregunta:

| Pregunta | Qué comprueba | Debe verse |
|---|---|---|
| P01 | opción única, con retroalimentación | «Ciudad de Panamá» correcta; la retroalimentación al responder |
| P02 | varias correctas (3 de 6) | C, Rust y Go correctas; marcar todas no da la nota completa |
| P03 | 12 correctas y 13 incorrectas | se importa (antes rechazaba TODO el archivo); correctas 10 % o 5 %, incorrectas -10 % o -5 % |
| P04 | verdadero/falso | «Verdadero» correcta |
| P05 | emparejamiento | las 4 parejas |
| P06 | «Completar»: 2 huecos, 2,5 puntos | lista A: `TCP/IP`, `UDP`, `10 / 2`. Lista B: `dijo "hola"`, `{llave}`, `a~b`, `c#d`, `e}f`, `g\h`, `R&D`, `x < y` **sin ninguna barra sobrante** |
| P07 | respuesta corta | «Fotosíntesis» y «Fotosintesis» aceptadas |
| P08 | numérica | 60 |
| P09 | ensayo | cuadro de texto libre |
| P10 | imagen en base64 y fórmula | cuadrado rojo visible; `x² + 1` con MathJax; en la retroalimentación `3² + 1 = 10` |
