# Alcance de la validación 0.4.1

El EXE pasa de **810536823 a 3990701 bytes** (aproximadamente **4 MB**, un 99,5 %
menor). El tamaño corresponde al bootstrap, no al conjunto de modelos y bibliotecas.
Sin reutilización local, los componentes compactos comprimidos suman 327395886 bytes
y el modelo ASR 742090464 bytes. La traducción opcional añade 577376558 bytes de
dependencias y 1133080448 bytes de pesos. Las cifras pueden cambiar en otra versión.

Comprobaciones adicionales en Windows x64:

- 110 tests Python, análisis estático y compilación nativa con advertencias como errores.
- Instalación compacta limpia desde un servidor HTTP local de pruebas para los
  componentes y desde Hugging Face para el modelo ASR; ampliación a traducción
  con descarga del modelo original. Se usó una carpeta aislada con espacios.
- Reinstalación con servidor de dependencias inaccesible: éxito, 2880 archivos
  conservados sin reescritura, configuración preservada, controlador y ocho
  variables globales de entorno sin cambios.
- Descarga alterada de un componente: rechazada por hash en `PrepareToInstall`,
  salida 7 y sin instalar el archivo de prueba ausente.
- Reparación del paquete NumPy con un archivo ausente: una sola petición de archivo
  comprimido al servidor; no volvió a descargar todos los runtimes ni los modelos.
- Carga ASR CUDA y generación funcional del traductor usando el Python instalado y
  PATH reducido a System32, sin el entorno de desarrollo en la búsqueda de DLL.
- El estado Authenticode del instalador publicado es `NotSigned`. Se documenta
  SmartScreen; no se ha probado la integración con un certificado de editor confiable.

El servidor local solo sustituye el origen de los componentes durante la prueba;
el EXE publicado fija URLs HTTPS de GitHub y de las revisiones de Hugging Face.
Los hashes de ZIP y archivos siguen siendo obligatorios en ambas construcciones.

## Validación previa 0.4.0

Esta versión cambia el empaquetado y la instalación. Conserva los pesos originales
de Nemotron; no se presenta como una mejora del reconocimiento de canciones.

Comprobaciones realizadas en Windows x64:

- 108 pruebas Python y comprobación estática de engine, tests, tools e installer.
- Compilación nativa con advertencias tratadas como errores, usando cabeceras de
  OBS 32.2.2 y rutas de compilación remapeadas.
- Instalación real en una carpeta aislada con espacios, generación de las rutas
  locales y desinstalación. No se usó una carpeta del desarrollador como runtime.
- Arranque de ASR CUDA con el Python y los runtimes del paquete y un PATH reducido
  al sistema, sin depender de un CUDA Toolkit o del entorno Python de desarrollo.
- Prueba funcional de 25 segundos con libobs, fuente nativa y navegador. La fuente
  arrancó su propio Python instalado, recibió 15.6 segundos de audio del archivo,
  produjo filas, no perdió audio y apagó el motor tras quedar inactiva. No se
  almacenaron transcripciones en el informe.
- El traductor instalado cargó y produjo texto con los archivos del paquete.
- La instalación compacta descargó y verificó el modelo ASR automáticamente; no
  instaló el traductor ni sus bibliotecas.
- La actualización añadió la traducción mediante descarga verificada, conservó
  los valores del motor y no volvió a descargar o reemplazar el ASR ya válido.
- Una reinstalación con un archivo de prueba dañado conservó 2911 archivos que
  coincidían con sus hashes y reparó el archivo modificado. No reescribió la
  configuración ni los metadatos locales correctos.
- La comprobación del controlador pasó en el equipo de prueba. El archivo del
  controlador y ocho variables globales de entorno de usuario/sistema (PATH,
  CUDA_PATH, PYTHONHOME, PYTHONPATH) permanecieron sin cambios.
- Con configuración inválida, la instalación devolvió 90, conservó ese archivo y
  no activó metadatos nuevos. No se interpretó un mensaje de éxito como evidencia
  suficiente para aceptar una instalación.
- El instalador final ocupa 810536823 bytes, por debajo del límite por archivo
  de GitHub Releases. Su SHA256 acompaña la descarga.

La revisión del código y del contenido publicado excluye rutas personales,
configuraciones locales, perfiles de prueba, grabaciones, logs y credenciales.
Los componentes de terceros mantienen sus licencias y sus metadatos originales;
algunos incluyen rutas de compilación o ejemplos genéricos de sus proveedores.
No son rutas de la máquina desde la que se publica este proyecto.

Estas comprobaciones no establecen precisión general, latencia acústica inferior
a un segundo, compatibilidad de cualquier GPU ni estabilidad durante horas. La
interfaz del instalador se verificó mediante instalaciones automatizadas; no se
afirma una inspección visual manual de cada pantalla. OBS 33 y modo portátil no
tienen una validación completa de integración en esta versión.
