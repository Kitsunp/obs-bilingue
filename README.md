# OBS Bilingüe

Fuente nativa para **subtitular voz en directo en OBS Studio**. Reconoce el idioma
automáticamente, permite colores por idioma y ofrece traducción opcional al español.
El audio y el texto se procesan localmente. No genera voz.

[**Descargar instalador para Windows x64**](https://github.com/Kitsunp/obs-bilingue/releases/download/v0.4.1/OBS-Bilingue-0.4.1-Windows-x64-Setup.exe)

[**Actualizar una instalación existente a 0.4.3: audio aislado por escena**](https://github.com/Kitsunp/obs-bilingue/releases/download/v0.4.3/OBS-Bilingue-0.4.3-Windows-x64-Update.exe).
Esta actualización pequeña solo sustituye el plugin nativo. Conserva el motor, los
modelos y la configuración. Cierra OBS antes de ejecutarla; el actualizador bloquea
la instalación si OBS sigue abierto y no cierra procesos automáticamente.
Para una instalación nueva, instala primero 0.4.1 y después aplica 0.4.3.

**Versión preliminar para Windows x64 y GPU NVIDIA.** El canto, las expresiones
muy alargadas, el ruido y los cambios rápidos de idioma todavía pueden producir
omisiones o errores. No se garantiza un retraso máximo de un segundo ni se ha
certificado la estabilidad durante varias horas.

## Instalar

1. Descarga **OBS-Bilingue-0.4.1-Windows-x64-Setup.exe** desde
   [Releases](https://github.com/Kitsunp/obs-bilingue/releases/tag/v0.4.1).
2. Cierra OBS, abre el instalador y pulsa **Instalar**. El EXE pequeño comprueba lo
   instalado y descarga solo los componentes incompletos, con SHA-256. Los modelos
   ocupan cientos de MB y no van dentro del EXE. La traducción es opcional.
   No requiere instalar Python, uv ni CUDA Toolkit. No modifica el Python, CUDA,
   los controladores ni el PATH del sistema.
   Windows puede pedir permiso de administrador. Esta versión no tiene firma digital
   de editor y puede mostrar SmartScreen al ejecutarla; consulta [la explicación y
   verificación de la descarga](docs/INSTALL.md#smartscreen-y-firma-digital).
3. Abre OBS y añade **Fuentes → + → Bilingue - Subtitulos de voz en directo**.
   En sus propiedades elige **Escena: nombre (solo sus fuentes)** para subtitular
   únicamente las entradas de audio visibles de esa escena, incluidos grupos y escenas
   anidadas. Así puedes subtitular el vídeo y dejar fuera Discord y los micrófonos globales.
   **Mezcla del directo de OBS (escenas, microfono y escritorio)** escucha toda la mezcla
   de la pista elegida, incluidas las entradas globales.
   También puedes elegir un micrófono, escritorio o fuente multimedia individual.

La mezcla respeta los silencios, volúmenes y pistas de OBS. No equivale al audio de
una sola escena: incluye las fuentes globales que llegan a la pista elegida. Con
**Pista de mezcla OBS = 0**, sigue la pista principal del directo activo; si no hay
directo, la de la grabación activa; sin ambos, usa la pista 1. Puedes fijar una pista
entre 1 y 6. Las fuentes configuradas antes de actualizar conservan su elección;
cambia esa propiedad para activar la captura de la mezcla. Solo se capturan fuentes
que OBS ya esté procesando y enviando a esa pista.

El aislamiento por escena funciona con fuentes de audio OBS: por ejemplo, Multimedia,
Navegador con audio controlado por OBS o Captura de audio de aplicación. Una captura
de ventana/pantalla solo aporta imagen. Si añades Audio del escritorio a la escena,
esa única entrada puede contener varios programas y el plugin los recibirá juntos.
Una escena seleccionada que no esté activa en el programa queda en silencio. Véase
[el funcionamiento y las pruebas del aislamiento](docs/SCENE_AUDIO.md).

Mostrar la fuente inicia el motor; ocultarla desconecta la captura y libera los
procesos administrados tras unos segundos. Se puede probar sin emitir ni grabar.
Reutiliza una sola fuente de captura en otras escenas para no duplicar el audio.

El instalador ofrece el componente de traducción al español. Aunque se instale,
la traducción empieza desactivada y su modelo solo se carga al activarla.
La instalación normal usa la carpeta de plugins de OBS dentro de ProgramData.
Se incluyen las dos disposiciones de DLL para OBS 32 y OBS 33; la validación
de integración se realiza con OBS 32.2.2. Para OBS portátil consulta
[la guía de instalación](docs/INSTALL.md).

## Configuración en OBS

- Fuente, tamaño, estilo, color y fondo; duración, apilado y límite de filas/líneas.
- Reglas de colores mediante lista de idiomas y selector visual, sin duplicados.
  Las reglas no limitan el reconocimiento. Sin regla se utiliza el color predeterminado.
- Vista previa privada; los fragmentos de una misma fila pueden tener diferentes colores.
- Traducción al español con color y tipografía propios o compartidos con el original.
  Puede reutilizar el color de la regla de español. El español reconocido no se duplica.

## Requisitos y límites

Windows x64, OBS Studio con fuente Navegador y una GPU NVIDIA compatible con el
runtime CUDA 13 distribuido por NVIDIA, con controlador actualizado. No es un
paquete para GPU AMD/Intel, macOS, Linux ni Windows ARM. La compatibilidad GPU
se ha comprobado con una RTX 5070 Ti de 16 GB; otras tarjetas requieren validación.
Se necesitan varios GB libres para la instalación y los archivos temporales.

El modelo ASR es **Nemotron 3.5 ASR Streaming 0.6B Q8**, sin adaptaciones experimentales,
con NeMo-Speech.cpp 0.2.0 CUDA. El traductor opcional es **Hy-MT2 1.8B Q4**.
El objetivo de consumo medio del 20 % de GPU no es un límite impuesto ni una garantía;
hay picos superiores y el uso depende del audio y de las demás aplicaciones.

No se guardan grabaciones ni transcripciones. Solo se usan conexiones de loopback.
No se cambian las cuentas, escenas, perfiles ni credenciales de OBS/Twitch.
El código publicado no incluye datos de las pruebas locales ni su historial de desarrollo.

## Desarrollo

[Compilación e instalador reproducible](docs/BUILD.md) ·
[Arquitectura y privacidad](docs/ARCHITECTURE.md) ·
[Ingeniería y decisiones de diseño](docs/ENGINEERING.md) ·
[Code signing policy](docs/SIGNING.md) ·
[Licencias de terceros](THIRD_PARTY_NOTICES.md)

El código del proyecto se distribuye bajo **GPL-2.0-or-later**. Los modelos,
Python, CUDA y las demás dependencias conservan sus propias licencias.
Este proyecto no está afiliado a OBS Project, NVIDIA ni Tencent.
