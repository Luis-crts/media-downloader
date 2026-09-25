## Descargas

| Sistema | Archivo | Instalación |
|---|---|---|
| **Windows 10/11 (64 bits)** | `MediaDownloader_Setup.exe` | Ejecútalo y sigue el asistente. Incluye FFmpeg; no hace falta instalar nada más. |
| **Linux (x86_64)** | `MediaDownloader-linux.tar.gz` | `tar -xzf MediaDownloader-linux.tar.gz && ./MediaDownloader-linux/install.sh` |

### Windows
- Se instala por usuario en `%LOCALAPPDATA%\Programs\MediaDownloader` (sin permisos de
  administrador); el asistente permite instalarlo para todos los usuarios en *Archivos de programa*.
- Crea los accesos directos del Menú Inicio y, opcionalmente, del Escritorio.
- Se desinstala desde *Configuración → Aplicaciones* o con el acceso del Menú Inicio.
- Windows SmartScreen puede avisar la primera vez porque el instalador no está firmado:
  *Más información → Ejecutar de todas formas*.

### Linux
- `install.sh` instala FFmpeg con el gestor de paquetes (apt, dnf, pacman o zypper), copia la
  app a `~/.local/share/media-downloader/app`, crea el comando `~/.local/bin/MediaDownloader` y
  el acceso directo en el menú y en el Escritorio.
- Desinstalar: `./MediaDownloader-linux/install.sh --uninstall` (añade `--purge` para borrar
  también la configuración y la cola).
- Requiere glibc 2.35 o posterior (Ubuntu 22.04+, Debian 12+, Fedora 36+…).

## Media Downloader 1.0.0 — versión estable

Descarga música y video de YouTube (MP3, M4A, MP4), video web y streams HLS/M3U8, torrents y
enlaces magnet, y busca películas libres en Internet Archive, Wikimedia Commons y Blender
Studio. Todo en una cola con prioridades, pausa, reintentos y verificación del archivo final.

### Novedades de la 1.0.0
- **▶ Reproducir** en cada descarga completada: abre el video o audio con el reproductor
  predeterminado del sistema.
- **Notificaciones del sistema** (Windows y Linux) al terminar una descarga o una cola completa
  mientras la app está en segundo plano; se pueden desactivar.
- **Subtítulos en español** comprobados de extremo a extremo en YouTube: se incrustan en el MP4
  como pista `spa` y se guarda el `.srt`.
- El instalador de Windows registra la app para las notificaciones y lo elimina al desinstalar.

### Novedades de la 0.10.0
- Dos fuentes nuevas en **Buscar películas**: **Wikimedia Commons** (películas, documentales y
  material histórico con licencia libre) y **Blender Studio** (sus películas abiertas: Sintel,
  Big Buck Bunny, Tears of Steel, Spring, Sprite Fright, Charge…).
- Selector de **fuente** («Todas» consulta las tres en paralelo) y **varias calidades por
  película** (original, 1080p, 480p) para elegir entre calidad y peso.
- El filtro de idioma usa los subtítulos disponibles cuando la fuente no indica el del audio.

### Novedades de la 0.9.0
- Pestaña **Buscar películas**: búsqueda en Internet Archive (dominio público y licencias
  libres) con título, año, formato/calidad, idioma, tamaño y popularidad; orden por peso o
  popularidad, filtro de idioma y botón **Añadir a la cola** en cada película.
- El motor P2P descarga solo los archivos elegidos de un torrent (la mejor versión de la
  película y sus subtítulos) y admite servidores HTTP adicionales (*web seeds*).
- Arquitectura de búsqueda extensible: `BaseSearchProvider` + `@register_search_provider`.

### Novedades de la 0.8.0
- Descargas **P2P**: enlaces magnet y archivos `.torrent` (libtorrent), en la misma cola.
- **Verificación del archivo final** con ffprobe: una descarga incompleta o dañada ya no se
  marca como completada; botón **Reintentar** que reanuda desde lo descargado.
- Cola con **prioridades** (▲▼), **persistencia** entre sesiones, pausa/reanudación, subtítulos,
  hilos HLS configurables y registro en `media_downloader.log`.

FFmpeg se distribuye bajo licencia LGPL (compilación de
[BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds)); su licencia y el enlace al código
fuente van en la carpeta `bin` de la instalación.
