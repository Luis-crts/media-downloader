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

## Novedades de la 0.8.0
- Descargas **P2P**: enlaces magnet y archivos `.torrent` (libtorrent), en la misma cola.
- **Verificación del archivo final** con ffprobe: una descarga incompleta o dañada ya no se
  marca como completada; botón **Reintentar** que reanuda desde lo descargado.
- Cola con **prioridades** (▲▼), **persistencia** entre sesiones, pausa/reanudación, subtítulos,
  hilos HLS configurables y registro en `media_downloader.log`.

FFmpeg se distribuye bajo licencia LGPL (compilación de
[BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds)); su licencia y el enlace al código
fuente van en la carpeta `bin` de la instalación.
