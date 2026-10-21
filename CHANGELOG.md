# 0.4.1

- Small online bootstrap: Python packages and native libraries are separate,
  checksummed downloads. Original model weights remain unchanged.
- Read-only discovery of compatible local dependency files through PEP 514,
  PATH, CUDA_PATH and System32; copies are private to this plugin.
- Reinstallation preserves correct files and fetches only incomplete components.
- Subtitles-only installation is the default; translation remains optional.
- Documented unsigned publisher status and SmartScreen behavior. Added an optional
  publisher-signing build hook without changing Windows security settings.

# 0.4.0

- Instalador Windows con Python y runtimes propios, independiente de la carpeta
  de desarrollo. Descarga automática de los modelos originales con SHA256.
- Componente opcional de traducción al español y desinstalador de Windows.
- Reutilización por SHA256 de archivos y modelos correctos; reparación de archivos
  diferentes sin cambiar configuración válida, controladores, CUDA o Python global.
- Comprobación previa del controlador compatible con CUDA 13 o superior y bloqueo
  de actualización mientras OBS o el motor instalado esté en uso.
- Rutas de instalación generadas en el destino; disposiciones de plugin para
  OBS 32 y 33. Integración probada con OBS 32.2.2.
- Repositorio inicial con código, pruebas, licencias y documentación públicos.
  Sin grabaciones, transcripciones, configuraciones privadas o historial local.
- Documentación de ingeniería: procesos, transporte, estado, límites, instalación,
  contratos de compatibilidad y verificación.

El reconocimiento conserva los pesos originales de Nemotron. Esta versión no
declara resueltos el canto, los cambios rápidos de idioma o las vocales exageradas.
No se certifica un retraso universal inferior a un segundo ni estabilidad de horas.
