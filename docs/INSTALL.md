# Instalación en Windows

La opción recomendada es el instalador de [Releases](https://github.com/Kitsunp/obs-bilingue/releases).
El EXE contiene la fuente y el motor ligero; comprueba las dependencias existentes
y descarga los componentes incompletos, incluidos los pesos originales, comprobando
SHA256. Una primera instalación sigue necesitando descargas grandes: un EXE pequeño
no reduce el tamaño de los modelos. Requiere internet cuando falten componentes. No requiere
Python, pip, uv ni CUDA Toolkit previamente instalados. Sí requiere un controlador
NVIDIA compatible con el runtime incluido, OBS x64 y su fuente Navegador.
El instalador comprueba que el controlador soporte CUDA 13 o superior. No instala
ni reemplaza controladores o CUDA Toolkit y no modifica el Python ni el PATH global.

Cierra OBS antes de instalar o actualizar. El instalador no lo cierra ni cambia
escenas, perfiles, cuentas o servicios de emisión. Al terminar abre OBS y añade la
fuente **Bilingue - Subtitulos de voz en directo**. El audio se elige en propiedades.
No se inicia un servicio de Windows ni una tarea al encender el equipo.

## Reutilización de dependencias

Primero comprueba cada archivo de la carpeta del plugin. Los archivos correctos se
conservan sin reescribirlos. Busca también copias locales mediante registros Python
PEP 514, las ubicaciones explícitas de PATH y CUDA_PATH, y System32 para bibliotecas
nativas. No recorre discos, carpetas personales ni cachés de navegadores.

Solo acepta archivos con el mismo SHA256 de la distribución probada. Una versión
aparentemente más nueva no demuestra compatibilidad: Python 3.13 no reemplaza las
extensiones CPython 3.12 y una DLL CUDA 14 no reemplaza automáticamente CUDA 13.
Las copias externas compatibles se leen y copian a la carpeta privada del plugin;
no se ejecuta ni modifica el Python externo, sus paquetes o el Toolkit.

Las descargas se dividen por paquete Python y biblioteca nativa, no por un único
runtime gigante. Si un paquete está incompleto se descarga ese paquete; sus archivos
correctos instalados se conservan. La extracción ocurre en una carpeta temporal,
y se verifica todo antes de publicar las rutas del motor. Reinstalar con todas las
dependencias correctas no requiere volver a descargarlas.

## SmartScreen y firma digital

El aviso **«Windows protegió su PC» al ejecutar** puede aparecer porque este
instalador no tiene firma Authenticode de editor ni reputación establecida. La
captura de ese aviso por sí sola no determina si un archivo es seguro o malicioso.
Esta distribución no desactiva SmartScreen, Defender, Smart App Control ni añade
certificados de confianza al equipo.

Comprueba que el archivo provenga de este repositorio y compara su hash con
`SHA256SUMS.txt` de la misma versión. Puedes inspeccionarlo sin ejecutarlo:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath '.\OBS-Bilingue-0.4.1-Windows-x64-Setup.exe'
Get-AuthenticodeSignature -LiteralPath '.\OBS-Bilingue-0.4.1-Windows-x64-Setup.exe'
```

La firma de esta versión se informa como `NotSigned`. El checksum sirve para
comprobar el archivo frente al publicado; no sustituye una identidad de editor
verificada ni garantiza ausencia de vulnerabilidades. No se ofrece una promesa de
eliminar ese aviso: se necesita una identidad/certificado confiable y aun un archivo
firmado nuevo puede mostrarlo mientras gana reputación. Un certificado autofirmado
no resuelve este problema. Véase la [documentación oficial de Microsoft](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation).

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
Los archivos que ya pasan el SHA256 esperado no se sobrescriben. Se sustituyen
solo archivos ausentes o diferentes de esta distribución, dentro de su carpeta.
El desinstalador mantiene su propio registro de archivos. Una configuración
inválida produce un error; no se borra silenciosamente para instalar valores nuevos.

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
