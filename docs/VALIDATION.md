# Alcance de la validación 0.4.0

Esta versión cambia el empaquetado y la instalación. Conserva los pesos originales
de Nemotron; no se presenta como una mejora del reconocimiento de canciones.

Comprobaciones realizadas en Windows x64:

- 104 pruebas Python y comprobación estática de engine, tests, tools e installer.
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
- El instalador final ocupa 811579224 bytes, por debajo del límite por archivo
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
