# Code signing policy

## Estado actual

La versión pública 0.4.1 sigue siendo **NotSigned**. Todavía no hay cuenta,
certificado ni aprobación de SignPath Foundation para este proyecto. Preparar el
proceso de firma no convierte un instalador existente en un archivo firmado.
No se reemplaza una descarga publicada para aparentar que ya está firmada.

La vía prevista es [SignPath Foundation](https://signpath.org/), que ofrece firma
gratuita a proyectos OSS aceptados bajo la identidad de la fundación. La
elegibilidad de OBS Bilingüe está pendiente de su revisión. No se afirma que la
fundación patrocine o firme actualmente el proyecto.

## Identidad de publicación

La identidad prevista del editor es **SignPath Foundation**, sujeta a aprobación.
Antes de la primera publicación firmada se revisan el Subject del certificado,
sus extensiones y los nombres alternativos. Los informes automáticos muestran
únicamente archivo, estado, editor esperado y presencia de timestamp.

La solicitud y el alta se tramitan por el mantenedor en el
[formulario oficial](https://signpath.org/apply). La preparación del repositorio
no crea una cuenta, acepta condiciones ni envía una solicitud automáticamente.

## Procedencia y responsabilidades

Los [mantenedores del repositorio](https://github.com/Kitsunp/obs-bilingue/graphs/contributors)
revisan el código y autorizan cada solicitud de firma. Solo se firman binarios de
este proyecto construidos desde su revisión pública; no se firman DLL de terceros
con la identidad del proyecto. Las claves permanecen en el servicio de firma.

El alta requiere revisión del proyecto por SignPath y configuración de su
integración GitHub con acceso limitado a este repositorio. No se instala esa app,
concede acceso ni envía una solicitud automáticamente al ejecutar los tests.
Los requisitos de la fundación se describen en sus [condiciones](https://signpath.org/terms).

## Instalador Inno Setup

El build ya admite `-SigningCommand`, que configura el callback `captionpublisher`
de Inno para **instalador y desinstalador**. El servicio debe devolver cada archivo
firmado antes de que el compilador siga. La integración real depende de la cuenta
y política aprobadas; no se ha validado una solicitud a SignPath con este proyecto.

La [integración GitHub de SignPath](https://docs.signpath.io/trusted-build-systems/github)
verifica el origen de artefactos de Actions. Hay que acordar el flujo del callback
de Inno con esa validación. Subir el EXE final a un firmador de PE **no demuestra**
que el desinstalador que lleva dentro también esté firmado. No se presenta esa
alternativa como una integración completa.

Con un firmador aprobado, el orden de publicación es:

1. Revisar commit, dependencias fijadas y licencias; compilar binarios propios.
2. Firmar el instalador y el desinstalador durante la construcción, con SHA256 y
   timestamp RFC3161. Firmar antes de calcular los hashes definitivos.
3. Ejecutar `tools/verify_signature.ps1`: debe obtener Authenticode **Valid**, firma
   embebida, editor esperado, uso de firma de código y timestamp.
4. Probar la instalación aislada y verificar también el desinstalador instalado.
5. Revisar metadatos, generar SHA256SUMS de los archivos finales y publicar una
   nueva versión, conservando el mismo editor aprobado en versiones posteriores.

```powershell
tools/verify_signature.ps1 -Path '.\dist\OBS-Bilingue-0.4.1-Windows-x64-Setup.exe'
```

Actualmente ese comando debe **fallar**: el instalador publicado no está firmado.
El verificador no busca claves/certificados de usuario ni instala confianza nueva.
Para una comprobación adicional con el Windows SDK, la [documentación de SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool)
describe `signtool verify /pa /all /tw archivo.exe`; cualquier advertencia de
timestamp o fallo impide declarar la versión lista para firma/publicación.

## SmartScreen

La firma confiable identifica al editor y protege la integridad; la reputación de
SmartScreen es otra comprobación. Microsoft advierte que un binario nuevo firmado
puede seguir mostrando el aviso. EV y autofirma no proporcionan una excepción
instantánea. No se garantiza eliminar el aviso en todos los equipos.
Véase [SmartScreen para desarrolladores](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation).

No se modifica Defender, SmartScreen, Smart App Control, los almacenes de confianza,
CUDA, Python ni los controladores del usuario para lograr que ejecute el instalador.

## Datos de red del producto

El procesamiento de voz y texto es local, con conexiones de loopback. La instalación
solicita a GitHub y Hugging Face los archivos que falten, con HTTPS y hashes fijados.
Esos servicios reciben las solicitudes normales de descarga; no se envía audio,
transcripciones ni telemetría del mantenedor/usuario al servicio de firma.
