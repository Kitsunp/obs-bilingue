# Arquitectura y privacidad

La fuente nativa captura la mezcla de programa de OBS o una entrada individual y
la entrega por loopback al motor local. La mezcla permite recibir audio interno de
escenas, vídeos y fuentes Navegador aunque no pase por los altavoces. Utiliza el
callback público de audio mezclado y conserva los volúmenes y silencios de OBS;
incluye las fuentes globales de la pista elegida. Véase [la actualización de audio](AUDIO_UPDATE.md).
El motor remuestrea a 16 kHz, ejecuta Nemotron mediante su ABI C CUDA,
combina las etiquetas acústicas con detección textual de idioma y entrega filas
al navegador interno de OBS. La traducción opcional utiliza un proceso nativo
separado y solo se carga cuando se solicita.

El estado y las colas son acotados: audio pendiente, hipótesis, filas visibles y
trabajos de traducción tienen límites. Cada fila tiene identidad y generación;
una traducción tardía no debe recrear una fila vencida. Mostrar y ocultar la fuente
controla la conexión de audio y la vida del motor. Los procesos administrados no
se añaden al inicio de Windows.

El motor solo escucha en `127.0.0.1`. No envía audio a servicios externos, no usa
cuentas y no guarda transcripciones ni grabaciones. Los puertos se leen de la
configuración local. Los modelos se instalan como recursos originales verificados
con SHA256. `runtime.json` se crea en el destino; no contiene rutas del desarrollador.

El instalador es independiente del árbol de desarrollo. Contiene una distribución
local de Python y sus paquetes, sin entornos virtuales que dependan de otra carpeta.
No modifica perfiles, escenas, claves de emisión o archivos de autenticación de OBS.

La recuperación de un proceso ASR bloqueado se limita a su proceso hijo. Esto no
resuelve errores de reconocimiento: una hipótesis incorrecta, un idioma equivocado
o una omisión siguen siendo limitaciones del modelo y deben evaluarse con referencias.
Ni el tiempo de una llamada de inferencia ni contar filas demuestra latencia hasta
pantalla o precisión de una transmisión completa.
