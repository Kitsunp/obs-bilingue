# Instalación en Windows

La opción recomendada es el instalador de [Releases](https://github.com/Kitsunp/obs-bilingue/releases).
Incluye Python y los runtimes, y descarga automáticamente los pesos originales
de Hugging Face comprobando SHA256. Requiere internet durante la instalación. No requiere
Python, pip, uv ni CUDA Toolkit previamente instalados. Sí requiere un controlador
NVIDIA compatible con el runtime incluido, OBS x64 y su fuente Navegador.

Cierra OBS antes de instalar o actualizar. El instalador no lo cierra ni cambia
escenas, perfiles, cuentas o servicios de emisión. Al terminar abre OBS y añade la
fuente **Bilingue - Subtitulos de voz en directo**. El audio se elige en propiedades.
No se inicia un servicio de Windows ni una tarea al encender el equipo.

La ruta normal se deriva de ProgramData. El instalador genera `data/runtime.json`
con la ruta del motor y de su Python local. Este archivo pertenece al equipo de
destino y nunca se incluye en el repositorio o en el instalador. No muevas después
la carpeta instalada: reinstala para regenerar las rutas.

## OBS portátil

OBS portátil no usa los plugins de ProgramData. Ejecuta el instalador con `/DIR=`
apuntando a la carpeta del plugin dentro de tu instalación portátil. OBS 33 utiliza
`plugins/obs-bilingue`; verifica la ubicación que corresponda a otras versiones.
No se certifica una instalación portátil sin probarla con esa versión de OBS.
Consulta la [guía oficial de ubicaciones](https://obsproject.com/kb/legacy-plugin-locations).

## Actualizar y desinstalar

Vuelve a ejecutar el instalador con OBS cerrado para actualizar. Los valores de
configuración del motor existentes se conservan y se añaden los nuevos valores
predeterminados cuando faltan. Las propiedades de las fuentes pertenecen a OBS.

Se puede desinstalar desde Aplicaciones de Windows o mediante el desinstalador
de la carpeta del plugin. Cierra OBS primero. La desinstalación retira los archivos
de este producto; no borra las escenas ni las fuentes guardadas en OBS.

## Si no aparece la fuente

Comprueba que OBS esté cerrado durante la instalación, que usas Windows y OBS x64,
y que el instalador terminó correctamente. Después reinicia OBS. Si el motor no
carga, revisa el controlador NVIDIA y reinstala el paquete. No compartas perfiles,
tokens de streaming ni grabaciones al informar de un problema.

Los subtítulos pueden ser incorrectos: la detección automática no garantiza el
idioma de frases muy cortas ni la transcripción completa del canto. El componente
de traducción necesita espacio adicional, pero permanece descargado de la GPU
mientras esté desactivado en las propiedades.
