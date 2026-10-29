# MiniDesign v0.4 — Modelo de documento y motor de composición

## Contexto del proyecto

Estamos desarrollando **MiniDesign**, una aplicación de autoedición inspirada en NewsMaster 1.5 para el ecosistema MiniCPU/MiniGPU.

El proyecto ya dispone de un motor gráfico funcional, desarrollado en C11, anteriormente llamado MiniMaster GFX.

La versión actual (v0.3) incluye:

- Display list de comandos gráficos.
- Renderer CPU de referencia con framebuffer RGB565.
- Primitivas `CLEAR`, `SET_CLIP`, `FILL_RECT`, `DRAW_LINE`, `GLYPH_RUN` y `BLIT`.
- `GLYPH_RUN` independiente del formato original de las fuentes.
- MiniFont, con soporte inicial para fuentes bitmap monocromas de 1 bpp.
- `BLIT` con escalado nearest-neighbor, transparencia, clipping y recursos bitmap identificados por ID.
- Conversores de fuentes, ilustraciones e iconos de NewsMaster.
- Ejemplos y pruebas existentes.

**Trabaja sobre el código real de v0.3. No reimplementes las funcionalidades existentes ni rompas sus interfaces sin una razón justificada.**

El objetivo de v0.4 es comenzar a construir la aplicación de autoedición sobre ese motor gráfico.

## Objetivo principal

Implementar un primer modelo de documento y un motor de composición (*layout*) capaces de producir automáticamente una página con:

- Tamaño de papel A4.
- Márgenes configurables.
- Dos o más columnas de texto.
- Título y párrafos.
- Una ilustración bitmap insertada en el documento.
- Flujo automático del texto alrededor de la ilustración.
- Continuación automática del texto entre columnas y, cuando sea necesario, entre páginas.

El resultado debe poder renderizarse utilizando las primitivas existentes de MiniGFX, sin incorporar conocimientos sobre documentos dentro del renderer.

## 1. Arquitectura

Separar claramente las siguientes capas:

```text
MiniDesign
  ├── Document
  │    ├── Pages / Page Settings
  │    ├── Stories
  │    ├── Paragraphs
  │    ├── Text Styles
  │    └── Graphic Objects
  │
  ├── Layout
  │    ├── Page Geometry
  │    ├── Column Flow
  │    ├── Line Breaking
  │    ├── Glyph Positioning
  │    └── Graphic Exclusion
  │
  ├── Viewport
  │    ├── Zoom
  │    └── Coordinate Transform
  │
  └── Editor (futuro)
           │
           ▼
        MiniGFX
           │
       Display List
           │
       Renderer CPU
       Renderer MiniGPU (futuro)
```

Requisitos arquitectónicos:

- El documento no depende de la resolución física de la pantalla.
- El layout se calcula en CPU.
- La display list contiene primitivas gráficas, no conceptos tipográficos de alto nivel.
- MiniGFX no debe conocer páginas, párrafos, columnas ni formatos de documento.
- Las fuentes deben resolverse a través del Font Manager existente.
- Las imágenes deben accederse mediante el sistema de recursos bitmap.
- El layout es información derivada y no debe tratarse como el contenido persistente del documento.

Mantener compatibilidad con C11 y evitar dependencias externas innecesarias.

## 2. Modelo de documento

Implementar una representación en memoria de un documento.

Utilizar coordenadas internas enteras con una resolución de **1/720 de pulgada**, independientes de los píxeles de pantalla.

Definir las estructuras necesarias para representar:

- `Document`
- `PageSettings`
- `Page`
- `TextStory`
- `Paragraph`
- `ParagraphStyle`
- `CharacterStyle`
- `GraphicObject`
- `TextFrame` o región de flujo de texto

El documento debe admitir diferentes tamaños físicos de papel, empezando por A4.

Una historia de texto (*story*) debe poder contener varios párrafos y fluir por múltiples columnas y páginas.

Evitar el modelo en el que cada línea de texto se almacena como un objeto independiente con coordenadas absolutas.

Prever la posibilidad de añadir posteriormente estilos por rangos de caracteres, varias historias independientes, páginas maestras y regiones de texto encadenadas.

No es necesario implementar todavía edición interactiva ni persistencia en disco.

## 3. Composición de texto

Implementar un primer motor de composición que:

1. Lea el contenido de una historia de texto.
2. Resuelva la fuente y sus métricas.
3. Calcule la anchura disponible en cada línea.
4. Divida el texto en líneas respetando los límites de palabras.
5. Aplique alineación izquierda, inicialmente.
6. Calcule el interlineado usando las métricas de fuente y el estilo de párrafo.
7. Distribuya las líneas verticalmente.
8. Continúe automáticamente en la columna siguiente.
9. Cree páginas adicionales cuando se agote el espacio disponible.

No utilizar anchuras de caracteres constantes: las fuentes son proporcionales.

El espaciado horizontal debe respetar el avance real del glifo y permitir `letter_spacing` como propiedad del estilo, sin aplicar una separación fija a todas las fuentes.

El resultado del layout debe contener glifos posicionados y regiones visuales que posteriormente se convertirán en comandos `GLYPH_RUN`.

Separar el cálculo del layout del renderizado.

## 4. Columnas y paginación

Cada página debe admitir:

- Márgenes superior, inferior, izquierdo y derecho.
- Número de columnas.
- Separación entre columnas.
- Área útil de composición.

Para v0.4 implementar dos columnas, pero diseñar las estructuras para admitir un número configurable.

El texto debe continuar automáticamente entre columnas y páginas, sin que el documento tenga que especificar manualmente dónde termina cada columna.

Evitar que el resultado dependa de la resolución de pantalla o del nivel de zoom.

## 5. Imágenes y exclusión de texto

Incorporar objetos gráficos que referencien recursos bitmap compatibles con `BLIT`.

Cada objeto debe tener:

- Identificador de recurso.
- Posición y dimensiones en unidades del documento.
- Rectángulo de exclusión de texto.
- Margen opcional de separación respecto al texto.

Implementar inicialmente exclusión rectangular.

El motor de layout debe adaptar la anchura de las líneas disponibles para evitar que el texto invada el rectángulo ocupado por la imagen.

La exclusión debe ser parte del cálculo de layout, no un efecto visual aplicado después de colocar el texto.

La ilustración debe renderizarse mediante `BLIT`.

No es necesario implementar todavía contornos de exclusión irregulares ni rotaciones.

## 6. Viewport y renderizado

Implementar una capa de viewport que transforme coordenadas del documento a coordenadas de pantalla.

Debe admitir:

- Zoom configurable.
- Desplazamiento horizontal y vertical.
- Conversión de unidades del documento a píxeles.
- Recorte al área visible.

El renderer debe poder generar vistas a:

- 320×240.
- 640×480.

Una página A4 completa debe conservar sus proporciones físicas al representarse en pantalla.

Las coordenadas de la página y las decisiones de salto de línea no deben cambiar por utilizar una resolución diferente.

La generación de display lists debe reutilizar las primitivas existentes de MiniGFX.

## 7. Demostración obligatoria

Crear un ejemplo ejecutable que genere programáticamente un documento con:

- Una página A4.
- Márgenes.
- Dos columnas.
- Título.
- Varios párrafos de texto suficientemente largos.
- Una ilustración extraída de los recursos disponibles.
- Texto que rodee la ilustración.
- Continuación del texto en la segunda columna.

Si el texto desborda la página, verificar que se crea una página adicional.

Exportar capturas PNG o PPM del resultado a 320×240 y 640×480.

El ejemplo debe utilizar el modelo de documento y el motor de layout. No debe colocar manualmente cada línea de texto en coordenadas predeterminadas.

## 8. Pruebas

Añadir pruebas automáticas para verificar:

- Conversión de dimensiones físicas a unidades internas.
- Cálculo de márgenes y columnas.
- Distribución de palabras en líneas.
- Uso de avances proporcionales de los glifos.
- Interlineado.
- Continuidad del texto entre columnas.
- Creación de páginas adicionales.
- Exclusión rectangular de imágenes.
- Independencia del layout respecto al zoom y resolución.
- Ausencia de líneas o glifos fuera de sus áreas válidas, salvo desbordamientos expresamente controlados.

Mantener todas las pruebas de v0.3.

## 9. Organización de archivos sugerida

```text
include/
    gfx.h
    minifont.h
    document.h
    layout.h
    viewport.h

src/
    display_list.c
    renderer_cpu.c
    minifont.c
    document.c
    layout.c
    viewport.c
    document_render.c

examples/
    page_demo.c

tests/
    test_document.c
    test_layout.c
    test_viewport.c

tools/
    shp2png.py
    icn2png.py
```

Adaptar esta propuesta a la organización real del repositorio, evitando reorganizaciones innecesarias.

## 10. Restricciones importantes

No implementar todavía:

- Interfaz gráfica interactiva.
- Edición de texto con teclado y ratón.
- Guardado y carga de documentos.
- Fuentes vectoriales.
- Justificación tipográfica avanzada.
- Kerning complejo.
- Silabeo automático.
- Figuras de exclusión no rectangulares.
- Renderer MiniGPU.

Sin embargo, procurar que la arquitectura permita incorporar esas funcionalidades en versiones posteriores.

No implementar un editor de cajas de texto independientes como sustituto del flujo automático.

No modificar la semántica de `GLYPH_RUN` ni de `BLIT` para introducir operaciones de composición de páginas.

## 11. Entregables

Proporcionar:

1. Código fuente C11 completo de los módulos nuevos.
2. Integración con el código existente.
3. Makefile actualizado.
4. Pruebas automáticas.
5. Ejemplo de documento compuesto.
6. Imágenes de demostración.
7. README con arquitectura, limitaciones y comandos de compilación.
8. Resumen explícito de archivos nuevos y modificados.

Compilar, ejecutar las pruebas y comprobar el resultado visual antes de dar el trabajo por terminado.

Cuando existan decisiones ambiguas, priorizar soluciones simples, deterministas y compatibles con el futuro backend MiniGPU.

**Criterio de aceptación principal:** modificar la cantidad de texto o el tamaño de la imagen debe provocar automáticamente una nueva composición de las líneas, columnas y páginas, sin tener que modificar manualmente las coordenadas de los glifos.