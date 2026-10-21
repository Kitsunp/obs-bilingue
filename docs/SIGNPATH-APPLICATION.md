# Solicitud SignPath Foundation: borrador del proyecto

Este documento prepara los campos del formulario público. **No se ha enviado**.
Los campos de cuenta y las aceptaciones se completan por el mantenedor en
https://signpath.org/apply.

| Campo | Contenido preparado |
| --- | --- |
| Project Name | OBS Bilingüe |
| Repository URL | https://github.com/Kitsunp/obs-bilingue |
| Homepage URL | https://github.com/Kitsunp/obs-bilingue |
| Download URL | https://github.com/Kitsunp/obs-bilingue/releases |
| Privacy/code signing policy | https://github.com/Kitsunp/obs-bilingue/blob/main/docs/SIGNING.md |
| Build System | GitHub Actions |
| Maintainer Type | Proyecto de código abierto mantenido de forma independiente |
| Tagline | Local multilingual live voice captions for OBS Studio. |

## Description

OBS Bilingüe is an open-source native OBS Studio source that turns incoming voice
audio into local live captions, with automatic language identification, configurable
language colors and optional Spanish text translation. It processes audio locally
and starts or stops its managed caption engine with source visibility. Its Windows
installer checks existing dependency files and downloads missing components into
the plugin's private directory without changing system Python, CUDA or drivers.

## Reputation

This is a new project with public source and preliminary Windows releases. We do
not claim widespread adoption, media coverage or independent reputation evidence.
The repository includes tests and build instructions. The released 0.4.1 source
revision has a public verification run:
https://github.com/Kitsunp/obs-bilingue/actions/runs/39546526973

The existing release is unsigned. We request an initial eligibility review and
guidance on integrating the Inno Setup signing callback with GitHub origin
verification.

## Aspectos que requieren revisión del proveedor

El código propio usa GPL-2.0-or-later. El instalador obtiene bibliotecas oficiales
CUDA de NVIDIA y modelos con licencias distintas: Nemotron bajo OpenMDW-1.1 y
Hy-MT2 bajo Apache-2.0. Son dependencias publicadas sin cambios por sus proveedores.
La excepción de System Libraries y la elegibilidad del conjunto deben confirmarse
con SignPath; no se afirma automáticamente que todos los componentes sean OSI.

El instalador usa Inno Setup con callback de firma para instalador/desinstalador.
Se debe validar ese flujo con la verificación de origen de GitHub de SignPath.
No se solicita firmar bibliotecas de terceros con el certificado del proyecto.

## Alta y revisión

El mantenedor completa el alta y revisa las condiciones en el formulario oficial.
El borrador no concede acceso a GitHub ni envía una petición de firma.
