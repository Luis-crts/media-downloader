# Media Downloader

Aplicación de escritorio (Python + CustomTkinter) para descargar música y videos de YouTube,
y películas/videos de la web (streams **HLS/M3U8**, DASH, enlaces directos y los más de 1800
sitios que reconoce yt-dlp), con **yt-dlp** y **FFmpeg**. Se distribuye como ejecutable para
Windows y Linux, con acceso directo en el Escritorio y en el menú de aplicaciones.

- [Estructura](#estructura)
- [Opción 1: instalar (usuarios)](#opción-1-instalar-usuarios)
- [Opción 2: ejecutar desde el código (desarrollo)](#opción-2-ejecutar-desde-el-código-desarrollo)
- [Compilar el ejecutable](#compilar-el-ejecutable)
- [Accesos directos](#accesos-directos)
- [FFmpeg](#ffmpeg)
- [Uso](#uso)
- [Películas / Video web (M3U8)](#películas--video-web-m3u8)
- [Torrent (enlaces magnet)](#torrent-enlaces-magnet)
- [Buscar películas](#buscar-películas)
- [Solución de problemas](#solución-de-problemas)
- [Añadir una nueva fuente](#añadir-una-nueva-fuente)

## Estructura

```
App musica/
├── main.py                        # Punto de entrada (+ --self-check)
├── build.py                       # Compilación con PyInstaller (Windows/Linux)
├── requirements.txt               # Dependencias de ejecución
├── requirements-dev.txt           # + PyInstaller y Pillow
├── assets/                        # icon.ico (Windows), icon.png (Linux), icon_source.png (original)
├── bin/                           # (opcional) ffmpeg + ffprobe portables
├── packaging/make_icon.py         # Genera icon.ico / icon.png desde icon_source.png
├── packaging/windows/             # Instalador de Windows (Inno Setup) + aviso de FFmpeg
├── packaging/linux/install.sh     # Instalador de Linux (FFmpeg, ~/.local/bin, .desktop)
├── scripts/
│   ├── install_shortcuts_windows.ps1   # Crea los .lnk (Escritorio + Menú Inicio)
│   ├── install_shortcuts_windows.bat   # Lo mismo, con doble clic
│   └── install_shortcuts_linux.sh      # Crea los .desktop (menú + Escritorio)
├── .github/workflows/build.yml    # CI: compila y verifica en Windows y Linux
└── app/
    ├── paths.py                   # Rutas compatibles con PyInstaller (sys._MEIPASS)
    ├── gui.py                     # Interfaz CustomTkinter (solo presentación)
    ├── widgets.py                 # Sección plegable y lista de la cola
    ├── search_view.py             # Pestaña «Buscar películas»
    ├── download_queue.py          # Modelo de la cola (sin interfaz, con pruebas)
    └── core/
        ├── base.py                # Contratos: BaseDownloader, modelos, errores, registro
        ├── ytdlp_backend.py       # Flujo común yt-dlp: analizar, descargar, progreso, errores
        ├── downloader.py          # Proveedor YouTube
        ├── generic.py             # Proveedor Web / M3U8 (respaldo para cualquier URL)
        ├── torrent.py             # Proveedor P2P: magnet y .torrent (libtorrent)
        ├── search/                # Búsqueda: BaseSearchProvider + Archive, Commons, Blender
        ├── validation.py          # Verificación del archivo final (ffprobe)
        ├── extractor.py           # Resolvers por sitio + sniffer de páginas (HTML/iframes/JS)
        └── dependencies.py        # Detección de FFmpeg, runtime JS y conexión
tests/                             # Pruebas sin red (python -m unittest discover -s tests)
```

Selección de proveedor (`get_downloader(url, tipo)`): se recorre el registro en orden y se
usa el primero que acepta la URL **y** el tipo. YouTube va primero; `GenericDownloader` va
último y acepta cualquier `http(s)`, así que también sirve para MP3/MP4 de Vimeo, SoundCloud,
etc. El tipo *Películas / Video Web* siempre usa el genérico.

- **`core` no importa nada de la GUI.** Puede usarse desde una CLI, una API web o tests.
- La descarga corre en un **hilo secundario**; el progreso llega a la GUI mediante una
  `queue.Queue` que se consulta con `after()` (Tkinter no es thread-safe).
- Los errores se traducen a excepciones propias (`InvalidURLError`, `NetworkError`,
  `FFmpegNotFoundError`, `ContentUnavailableError`, `AccessDeniedError`, `DRMProtectedError`,
  `DownloadCancelledError`) con mensajes
  listos para mostrar.

---

## Opción 1: instalar (usuarios)

Descarga el instalador de tu sistema desde **Releases** del repositorio:

| Sistema | Archivo | Cómo se instala |
|---|---|---|
| Windows 10/11 (64 bits) | `MediaDownloader_Setup.exe` | Doble clic y seguir el asistente. **Incluye FFmpeg**. |
| Linux x86_64 | `MediaDownloader-linux.tar.gz` | `tar -xzf MediaDownloader-linux.tar.gz && ./MediaDownloader-linux/install.sh` |

**Windows:** se instala por usuario en `%LOCALAPPDATA%\Programs\MediaDownloader` (sin permisos de
administrador; el asistente permite elegir *Archivos de programa* para todos los usuarios), crea
los accesos directos del Menú Inicio y del Escritorio con el icono de la app y registra el
desinstalador en *Configuración → Aplicaciones*. Al desinstalar pregunta si borrar también la
configuración y la cola guardada; los archivos descargados nunca se tocan.

**Linux:** `install.sh` instala FFmpeg con el gestor de paquetes (apt, dnf, pacman o zypper),
copia la app a `~/.local/share/media-downloader/app`, crea el comando
`~/.local/bin/MediaDownloader` y los lanzadores del menú y del Escritorio. Opciones: `-y` (sin
preguntas), `--no-desktop`, `--no-ffmpeg`, `--uninstall` y `--uninstall --purge`.

## Opción 2: ejecutar desde el código (desarrollo)

Requiere Python 3.10+ (en Windows, marca **"Add python.exe to PATH"** al instalarlo).

**Windows**

```bash
python -m venv .venv
```

```bash
.venv\Scripts\pip install -r requirements.txt
```

```bash
.venv\Scripts\python main.py
```

**Linux** (en Debian/Ubuntu, Tkinter se instala aparte: `sudo apt install python3-tk python3-venv`)

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python main.py
```

---

## Compilar el ejecutable

PyInstaller **no compila de forma cruzada**: el `.exe` se genera en Windows y el binario de
Linux en Linux. El script `build.py` encapsula todas las opciones y verifica el resultado.

### Instalador de Windows

```bash
python build.py --installer
```

Genera `dist/MediaDownloader_Setup.exe` con **Inno Setup 6**
(`winget install --id JRSoftware.InnoSetup -e`) a partir de
`packaging/windows/MediaDownloader.iss`. Incluye la carpeta de PyInstaller y un FFmpeg
**LGPL** (compilación *shared* de BtbN: `ffmpeg`/`ffprobe` comparten las DLL), que se descarga
la primera vez en `build/ffmpeg/`; con `--ffmpeg-dir CARPETA` se usa otro. FFmpeg queda en
`bin\` junto al ejecutable, que es el primer sitio donde la app lo busca.

### Publicación automática

Al subir una etiqueta `vX.Y.Z`, GitHub Actions compila en Windows y Linux, **prueba los dos
instaladores** (instalación silenciosa, ejecución con el FFmpeg incluido/instalado, descarga
HLS real en Linux y desinstalación) y, solo si todo pasa, publica `MediaDownloader_Setup.exe`
y `MediaDownloader-linux.tar.gz` en el Release con las notas de `packaging/RELEASE_NOTES.md`.

```bash
git tag -a v0.9.0 -m "Media Downloader 0.9.0"
```

```bash
git push origin v0.9.0
```

### Modos

| Comando | Resultado | Cuándo usarlo |
|---|---|---|
| `python build.py` | `dist/MediaDownloader/` (carpeta, `--onedir`) | **Recomendado.** Arranque inmediato y menos falsos positivos de antivirus. |
| `python build.py --onefile` | `dist/MediaDownloader(.exe)` (un archivo) | Para compartir un único archivo. Cada arranque descomprime en una carpeta temporal (unos segundos). |
| `... --embed-ffmpeg` | Incluye `ffmpeg` y `ffprobe` dentro del paquete | Para que el usuario final no tenga que instalar FFmpeg. Toma los binarios de `./bin` o del PATH. |

Al terminar, `build.py` ejecuta `MediaDownloader --self-check`, que comprueba que el binario
contiene iconos, temas de CustomTkinter, extractores de yt-dlp y los scripts de `yt-dlp-ejs`.
El informe se guarda en `self-check.txt` dentro de la carpeta de datos del usuario (ver
[registros](#solución-de-problemas)).

### Flujo en Windows

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -r requirements-dev.txt
```

```bash
python build.py
```

```bash
scripts\install_shortcuts_windows.bat
```

Para distribuir: comprime la carpeta `dist\MediaDownloader` en un ZIP. El usuario la
descomprime donde quiera (p. ej. `%LOCALAPPDATA%\Programs\MediaDownloader`) y ejecuta el
`.bat` con `-Target` apuntando al `.exe`, o simplemente crea el acceso directo a mano.

### Flujo en Linux (Debian/Ubuntu)

```bash
sudo apt install python3-venv python3-tk
```

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements-dev.txt
```

```bash
python build.py
```

```bash
chmod +x scripts/install_shortcuts_linux.sh
```

```bash
./scripts/install_shortcuts_linux.sh
```

En Fedora: `sudo dnf install python3-tkinter`. En Arch: `sudo pacman -S tk`.

Compatibilidad: el binario de Linux solo funciona en distribuciones con una glibc **igual o
más nueva** que la de la máquina donde se compiló. Por eso la CI compila en Ubuntu 22.04.

### Comando PyInstaller equivalente

`build.py` ejecuta esto (en Linux cambia `;` por `:` en `--add-data` y se omite `--icon`,
que allí lo aporta el `.desktop`):

```bash
pyinstaller main.py --name MediaDownloader --onedir --windowed --noconfirm --clean --add-data "assets/icon.ico;assets" --add-data "assets/icon.png;assets" --collect-data customtkinter --collect-data yt_dlp_ejs --icon assets/icon.ico
```

- `--windowed` (equivale a `--noconsole` / `-w`): no aparece la consola de fondo. En este modo
  `sys.stdout`/`sys.stderr` son `None`, así que la app registra en un archivo y muestra los
  errores fatales en un diálogo.
- `--add-data assets/icon.*`: iconos de la ventana accesibles en tiempo de ejecución.
- `--collect-data customtkinter` / `yt_dlp_ejs`: archivos no-Python (temas JSON y scripts JS)
  que PyInstaller no detecta por sí solo.

### Rutas dentro del binario (`sys._MEIPASS`)

`app/paths.py` centraliza la resolución de rutas:

| Función | Desde el código | Desde el binario |
|---|---|---|
| `resource_path(...)` / `bundle_dir()` | raíz del proyecto | `sys._MEIPASS` (temporal en `--onefile`, `_internal/` en `--onedir`) |
| `app_dir()` | raíz del proyecto | carpeta del ejecutable |
| `user_data_dir()` | `%LOCALAPPDATA%\MediaDownloader` · `~/.local/share/media-downloader` | igual |

Nunca se usan rutas relativas al directorio de trabajo, porque un acceso directo puede
lanzar la app desde cualquier carpeta.

---

## Accesos directos

### Windows

Doble clic en `scripts\install_shortcuts_windows.bat`, o desde PowerShell:

```bash
powershell -ExecutionPolicy Bypass -File scripts\install_shortcuts_windows.ps1
```

Crea `Media Downloader.lnk` en el **Escritorio** y en el **Menú Inicio** con el icono de la
app. Usa el objeto COM `WScript.Shell` incluido en Windows, así que no requiere `pywin32`.
Detecta el destino automáticamente: build `--onedir`, build `--onefile` o, si no hay
compilación, `.venv\Scripts\pythonw.exe main.py` (que tampoco abre consola).

| Parámetro | Efecto |
|---|---|
| `-Target "C:\ruta\MediaDownloader.exe"` | Usa un ejecutable concreto |
| `-NoDesktop` / `-NoStartMenu` | Omite uno de los dos accesos |
| `-Uninstall` | Elimina los accesos directos |

### Linux

```bash
./scripts/install_shortcuts_linux.sh
```

Crea `media-downloader.desktop` en `~/.local/share/applications/` (menú de aplicaciones) y
en el Escritorio del usuario (según `xdg-user-dir DESKTOP`, así que funciona también con
"Escritorio" en español), ambos con `chmod +x`. Además:

- instala el icono en `~/.local/share/icons/hicolor/256x256/apps/`;
- en GNOME marca el lanzador del Escritorio como confiable (`gio set … metadata::trusted true`);
- escapa correctamente rutas con espacios u otros caracteres especiales en la clave `Exec`;
- define `StartupWMClass=MediaDownloader` para que el dock agrupe la ventana con su icono.

Opciones: `--target RUTA`, `--no-desktop`, `--uninstall`, `--help`.

> Si mueves la carpeta de la aplicación, vuelve a ejecutar el script de accesos directos.

---

## FFmpeg

Se usa para convertir a MP3, extraer M4A, unir video + audio y embeber carátulas. yt-dlp lo
invoca directamente, así que no hace falta `python-ffmpeg`.

La app lo busca en este orden:
1. `bin/` junto al ejecutable (o en la raíz del proyecto al ejecutar desde el código).
2. Dentro del paquete (`--embed-ffmpeg`).
3. El PATH del sistema.

**Windows**

```bash
winget install --id Gyan.FFmpeg -e
```

Si no tienes winget, descarga `ffmpeg-release-essentials.zip` de
<https://www.gyan.dev/ffmpeg/builds/>, descomprímelo (p. ej. en `C:\ffmpeg`) y añade
`C:\ffmpeg\bin` al PATH (*Inicio → "Editar las variables de entorno del sistema" → Path*).
O copia `ffmpeg.exe` y `ffprobe.exe` en la carpeta `bin\`.

**Linux**

```bash
sudo apt install ffmpeg
```

Comprueba la instalación con `ffmpeg -version` en una terminal **nueva**.

> **Licencia:** las compilaciones habituales de FFmpeg son GPL. Si distribuyes un ejecutable
> con `--embed-ffmpeg`, incluye el aviso de licencia de FFmpeg y un enlace a su código fuente.

### Runtime de JavaScript (recomendado)

Las versiones actuales de yt-dlp necesitan un runtime JS para resolver los formatos de
YouTube; sin él, algunos videos ofrecen menos calidades o fallan. La app detecta **Deno**,
**Node.js** o **Bun** automáticamente. Lo recomendado es Deno:

```bash
winget install --id DenoLand.Deno -e
```

En Linux: `curl -fsSL https://deno.land/install.sh | sh`.

---

## Uso
1. Pega la URL de un video o lista de reproducción (botón **Pegar** o Ctrl+V).
2. Elige el formato:
   - **Audio MP3**: mejor audio disponible convertido a MP3 VBR V0, con metadatos y carátula.
   - **Audio M4A/MP4**: pista AAC original, sin recodificar, con metadatos y carátula.
   - **Video MP4**: máxima resolución disponible + mejor audio, unidos en MP4. A igualdad de
     resolución se prefiere H.264/AAC por compatibilidad; en 1440p/4K YouTube solo ofrece
     VP9/AV1, que se guarda igualmente en contenedor MP4.
3. (Video) Opcional: marca **Subtítulos** e indica los idiomas.
4. Elige la carpeta de destino y pulsa **Descargar**.

### Cola de descargas

Pulsar **Descargar** mientras otra descarga está en curso no la interrumpe: el enlace se añade
a la **cola** (el botón pasa a llamarse *Añadir a la cola*) y se descarga de uno en uno, en
orden. Cada elemento guarda sus propias opciones (formato, calidad, subtítulos, cabeceras,
nombre, carpeta), así que puedes cambiarlas entre un enlace y otro.

- La lista *Cola de descargas* muestra cada elemento como **Pendiente**, **Descargando**,
  **En pausa**, **Completada**, **Error** o **Cancelada**, con su progreso.
- Al terminar (bien, con error o cancelada) empieza automáticamente la siguiente.
- **Pausar** pausa la descarga activa y la cola espera; **Cancelar** cancela solo la activa y
  sigue con la siguiente.
- **▲ / ▼** cambian la prioridad de un pendiente (p. ej. adelantar canciones ligeras a
  películas pesadas). Solo reordenan los pendientes entre sí: la descarga activa no se toca.
- **▶ Reproducir** (en las completadas) abre el archivo con el reproductor predeterminado del
  sistema; si la descarga trae varios archivos (subtítulos, extras de un torrent) abre el video o
  audio principal. *Abrir* abre su carpeta.
- *Quitar* elimina un pendiente; *Vaciar pendientes* y *Limpiar terminadas* actúan sobre toda
  la lista.
- Un enlace que ya está pendiente o en curso (mismo enlace y formato) no se añade dos veces.
- Los errores quedan en la fila y en *Actividad*; el diálogo de error solo aparece cuando la
  cola se detiene, para no bloquear las descargas siguientes.
- *Analizar* (calidades) funciona también mientras hay una descarga en curso.
- **La cola se conserva entre sesiones.** Se guarda automáticamente en cada cambio (también
  ante un cierre inesperado) en `queue.json`, dentro de la carpeta de datos del usuario
  (`%LOCALAPPDATA%\MediaDownloader\` en Windows, `~/.local/share/media-downloader/` en
  Linux). Al volver a abrir la aplicación, las pendientes reaparecen en el mismo orden (la que
  estaba en curso, la primera, y se reanuda desde sus `.part`). No arrancan solas: pulsa
  **▶ Iniciar cola**. Las terminadas no se guardan.

Las listas se guardan en una subcarpeta con su nombre y numeradas (`001 - Título.mp3`).
Si un elemento de la lista no está disponible, se omite y se informa al final.
La última carpeta, formato, subtítulos y tema se recuerdan en `~/.media_downloader.json`.

### Notificaciones

Con **Notificar al terminar** (junto a *Actividad*, activada por defecto) la app avisa con una
notificación del sistema cuando termina una descarga —o falla— **mientras la ventana está
minimizada o en segundo plano**, y con un resumen cuando termina una cola de varias
(«2 completadas, 1 con error»). Con la ventana delante no se notifica.

- **Windows 10/11:** notificaciones nativas del sistema. Windows solo las acepta de apps
  registradas: el instalador registra `MediaDownloader.App` (y lo elimina al desinstalar); desde
  el código fuente la app lo registra en `HKCU\Software\Classes\AppUserModelId`.
- **Linux:** `notify-send` (paquete `libnotify-bin` en Debian/Ubuntu) o `gdbus`.
- Si el sistema no puede mostrarlas, solo se anota en el log.

### Pausar, reanudar y cancelar

- **Pausar** detiene la recepción de datos al instante: el hilo de descarga (y, en HLS, cada
  hilo de segmentos) queda en espera y no se piden más segmentos. Lo descargado se conserva.
- **Reanudar** continúa desde el mismo byte o segmento. Si durante una pausa larga el
  servidor cerró la conexión, yt-dlp la reabre automáticamente y sigue donde iba.
- Si pausas mientras FFmpeg une o convierte el archivo, la pausa se aplica al terminar ese paso.
- **Cancelar** (también en pausa) deja los archivos `.part`; si repites la misma descarga se
  reanuda desde ellos.

### Subtítulos

Solo para *Video MP4* y *Películas / Video web* (YouTube y cualquier sitio que yt-dlp soporte).
Marca **Subtítulos** y deja `es` en *Idiomas* para subtítulos en español. Se descargan los
subtítulos manuales y, si no hay, los automáticos; se convierten a **SRT**, se **incrustan** en
el MP4 como pista de texto (idioma `spa`, seleccionable en el reproductor) y se conserva también
el `.srt` junto al video.

- **Idiomas:** códigos separados por comas (`es, en`). Cada código incluye sus variantes
  regionales (`es` → `es`, `es-ES`, `es-419`). `all` descarga todos.
- Se excluyen a propósito las **traducciones automáticas** de YouTube (`es-de`, `en-fr`…:
  decenas por video, que provocan bloqueos HTTP 429). Para pedir una concreta, escribe su
  código completo: `es-en` = español traducido del inglés.
- En streams HLS se usan las pistas de subtítulos del propio `.m3u8` si las hay.
- Si un subtítulo falla, el video se descarga igualmente y el aviso queda en el log.

### Verificación del archivo final

Una descarga solo se marca como **Completada** si el archivo final pasa estas comprobaciones;
si no, se **elimina** y la fila queda en **Error** con el motivo, lista para **Reintentar**:

1. **Coherencia de la descarga directa (HTTP):** si al reanudar tras un corte el servidor anuncia
   un tamaño total distinto, está sirviendo otra versión del archivo y las partes no encajan
   (causa típica del «.mp4 de 1 KB»). También falla si lo descargado es menor que lo anunciado.
2. **Tamaño mínimo** (16 KB) y **lectura con ffprobe**: debe tener pista de video (formatos de
   video) o de audio, y una duración real.
3. **Duración** frente a la anunciada por la fuente (al menos el 90 %) y **tasa de bytes**
   coherente con la duración.

No se usa un umbral fijo tipo «5 MB»: rechazaría canciones MP3 o clips cortos válidos.

- **Antes de analizar** se espera al menos 0,5 s y hasta que el tamaño del archivo deje de cambiar
  (máx. 3 s), por si el post-procesado, el antivirus o un indexador aún lo están escribiendo.
- **Red de seguridad:** si ffprobe no puede leer un archivo de **más de 1 MB**, no se borra: se
  conserva como **«Guardado (sin verificar)»** y el log registra «Archivo sin verificar» con la
  causa. Solo se eliminan los archivos ilegibles pequeños (restos típicos de una descarga rota).
- ffprobe, el reproductor de **▶ Reproducir** y las notificaciones se lanzan con el entorno
  original del sistema, no con las bibliotecas empaquetadas del ejecutable (ver *Solución de
  problemas*).

- **HLS/DASH:** si un segmento falla tras todos los reintentos, la descarga se detiene en lugar de
  omitirlo (`skip_unavailable_fragments = False`): FFmpeg solo une el video con el 100 % de los
  segmentos. Los segmentos ya descargados se conservan y un reintento continúa desde ahí.
- **Si FFmpeg falla** al unir o convertir, la descarga queda en **Error** («Error al procesar con
  FFmpeg»), la causa exacta de FFmpeg se registra en `media_downloader.log` y se elimina lo que ni
  FFmpeg puede leer (las pistas válidas se conservan para el reintento).
- **Reintentar** vuelve a poner la descarga en cola con **el mismo nombre de archivo** que el
  primer intento, para que yt-dlp reanude desde el `.part` (`continuedl`). Un `.part` solo se
  puede reanudar si el nombre coincide: si la página cambia de título entre visitas, fija el
  **Nombre** en *Opciones avanzadas*.

### Cortes de red

Cada petición y cada segmento HLS/DASH se reintentan hasta **20 veces**, con espera creciente
entre intentos (1, 2, 4, 8 y luego 10 s, mediante `retry_sleep_functions` de yt-dlp) y un tiempo
de espera de conexión de **30 s**. Los
archivos parciales y los segmentos ya descargados se reutilizan (`continuedl`), así que un corte
de red o un reinicio no obliga a empezar de cero.

## Películas / Video web (M3U8)

Elige **Formato → Películas / Video Web (M3U8 / Enlace genérico)**. Aparece la sección
plegable **▸ Opciones avanzadas de video web** (cerrada por defecto; se recuerda si la dejas
abierta). Plegada, su cabecera resume lo configurado, p. ej. *Referer: www.sitio.com*:

| Campo | Para qué sirve |
|---|---|
| **User-Agent** | Se identifica como un navegador de escritorio (valor actualizado por yt-dlp). *Restablecer* recupera el valor por defecto. |
| **Referer** | Página donde se reproduce el video. Muchos CDN devuelven **403** si falta. |
| **Hilos** | Segmentos HLS/DASH descargados en paralelo: 1, 4, **8** (por defecto) o 16. Más hilos acelera los streams (en pruebas, 8 hilos ≈ 2× más rápido que 1); si el servidor responde con 429/403, baja a 4 o 1. Se guarda con cada descarga de la cola. |
| **Nombre** | Nombre del archivo final (sin extensión). Si se deja vacío se usa el título de la página, el nombre de la URL o `video-AAAAMMDD-HHMMSS`. Se vacía al añadir a la cola, porque es propio de cada descarga. |

**Calidad:** pulsa **Analizar** para ver las resoluciones del stream (p. ej. 1080p, 720p…) y
elige una; con *Máxima disponible* se toma la mejor automáticamente. El selector también
funciona para *Video MP4* de YouTube. Si cambias el enlace, se vuelve a *automática*.

**Qué se puede pegar:**
1. Un enlace directo `.m3u8`, `.mpd`, `.mp4`, `.webm`… yt-dlp descarga los segmentos
   `.ts`/`.m4s` en paralelo (8 a la vez), con las cabeceras indicadas en **todas** las
   peticiones (manifiesto, segmentos y claves AES-128), y FFmpeg los une en un `.mp4` sin
   recodificar.
2. La página de un sitio que yt-dlp reconozca (más de 1800).
3. Cualquier otra página con un reproductor: si yt-dlp no la reconoce, el *sniffer* de
   `extractor.py` busca el video en el HTML (`<video>/<source>`, configuraciones de
   JWPlayer/Clappr/Video.js, JSON con `\/` escapados, JavaScript empaquetado con
   `eval(function(p,a,c,k,e,d)…)`) y entra en los iframes (2 niveles), enviando como Referer
   la página que contiene el reproductor, como haría un navegador.

**Si no encuentra el video:** ábrelo en el navegador, pulsa F12 → pestaña *Red*, reproduce
el video y filtra por `m3u8`. Copia esa URL en *Enlace* y la dirección de la página en
*Referer*.

**Límites:**
- **DRM:** los servicios de suscripción (Netflix, Disney+, Prime Video…) cifran con
  Widevine/PlayReady/FairPlay. La app lo detecta y muestra *Contenido protegido (DRM)*;
  no intenta eludirlo.
- Los enlaces de stream suelen llevar un token que caduca: si falla con 403/404 un rato
  después, copia de nuevo la URL.
- Algunas webs exigen cookies de sesión; hoy no están soportadas.

Descarga solo contenido que tengas derecho a guardar (dominio público, licencias libres,
tus propios videos, o cuando el sitio lo permita).

### Añadir un resolver para un servidor concreto

Si un sitio necesita lógica propia (p. ej. llamar a una API para obtener el `.m3u8`), crea un
`SiteResolver` en `app/core/extractor.py` o en su propio módulo. El docstring de
`extractor.py` trae una plantilla completa:

```python
@register_resolver
class MiServidorResolver(SiteResolver):
    name = "MiServidor"
    domains = ("miservidor.example",)

    def resolve(self, url, headers):
        page = fetch_page(url, headers)
        ...
        return ResolvedMedia(url=m3u8, headers=with_referer(headers, page.url), title=page_title(page.text))
```

Los resolvers se ejecutan antes que yt-dlp y el sniffer. Mantenlos pequeños: los sitios
cambian a menudo, así que conviene cubrir cada uno con una prueba en `tests/`.

## Torrent (enlaces magnet)

Formato **Película / Torrent (Enlace Magnet)**. Acepta:
- enlaces **magnet** (`magnet:?xt=urn:btih:…`, también BitTorrent v2 `urn:btmh:`),
- URLs a archivos **.torrent**,
- archivos **.torrent** del disco (botón **.torrent…** junto a *Pegar*).

Al pegar un enlace magnet el formato cambia solo a *Torrent*. Usa **libtorrent** y va a la misma
cola que el resto: pausa, cancelar, reintentar, prioridades y persistencia funcionan igual. El
progreso muestra porcentaje, **↓ bajada · ↑ subida**, **semillas y pares** conectados y tiempo
restante. Los archivos se guardan en la carpeta de destino, dentro de la carpeta del torrent.

Comportamiento:
- **No se comparte al terminar.** Mientras descarga, BitTorrent sube datos a otros pares (es parte
  del protocolo); al llegar al 100 % se detiene. No se abren puertos en el router (UPnP/NAT-PMP
  desactivados).
- **Reanudación:** al pausar, cancelar o cerrar la app se conservan los datos; *Reintentar* (o
  volver a añadir el mismo enlace con la misma carpeta) comprueba las piezas y continúa donde iba.
- **Integridad:** cada pieza se verifica por hash, por eso no se aplica la verificación con ffprobe.
- **Sin fuentes:** si un magnet no consigue metadatos en 5 min, o la descarga pasa 15 min sin
  avanzar, queda en *Error* (lo descargado se conserva para reintentar).
- Windows puede pedir permiso en el **firewall** la primera vez: la app escucha en el puerto 6881
  para recibir conexiones de otros pares (funciona también sin ese permiso, con menos pares).

> En BitTorrent tu dirección IP es visible para el resto de pares del enjambre. Úsalo con
> contenido que tengas derecho a descargar y compartir (software libre, dominio público,
> licencias Creative Commons…).

## Buscar películas

Pestaña **Buscar películas**. Busca contenido de dominio público o con licencia libre y muestra
una tabla con **título, año, formato/calidad, idioma, tamaño y popularidad**. La búsqueda corre
en segundo plano («Buscando opciones…»).

| Fuente | Qué aporta | Cómo se descarga |
|---|---|---|
| **Internet Archive** | Largometrajes clásicos (cine mudo, negro, serie B…) | Torrent de Archive (solo la mejor versión) |
| **Wikimedia Commons** | Películas, documentales y material histórico (≥ 3 min) | Directa, original o recodificada a 1080p/480p |
| **Blender Studio** | Las películas abiertas de Blender: Elephants Dream, Big Buck Bunny, Sintel, Tears of Steel, Cosmos Laundromat, Spring, Sprite Fright, Charge, Wing It!… | Directa desde Commons o `download.blender.org` |

- **Fuente:** «Todas» consulta las tres en paralelo e intercala sus resultados; si una falla, se
  muestran las demás. Si dos fuentes devuelven el mismo archivo, se queda la más específica.
- **Ordenar:** relevancia, menor peso, mayor peso, más populares (en local, al instante).
- **Idioma:** todos, español o inglés. En Archive es el idioma del audio; en Commons y Blender,
  el de los **subtítulos disponibles** (Commons no registra el idioma del audio).
- **Varias calidades por película:** en Commons/Blender cada película aparece en varias filas
  (original, 1080p, 480p y, si existe, la copia de blender.org). El tamaño de las versiones
  recodificadas es una estimación (bitrate × duración).
- **Pulsa el título** para abrir su página y comprobar la licencia (visible bajo cada título).
- **Añadir a la cola** envía la película a la cola principal.

**Wikimedia Commons** solo admite contenido libre (lo exige y revisa). La búsqueda usa su API
pública; las descargas se hacen con el User-Agent propio de la app, porque
`upload.wikimedia.org` responde 403 a clientes que se presentan como un navegador genérico.
Los videos de menos de 3 minutos se omiten para centrarse en películas y documentales.

**Blender Studio** no publica una API de catálogo: el listado sale de la categoría
«Blender movies» de Commons (las películas nuevas aparecen solas), sin duplicados y con el
año de estreno, más las copias que siguen en `download.blender.org` (Sintel 1080p MKV,
Tears of Steel 720p). *Agent 327: Operation Barbershop* no está: en Commons solo hay el teaser.

### Internet Archive

Solo aparecen películas **de dominio público o con licencia libre**: las de la colección
`feature_films` que declaran una licencia Creative Commons o de dominio público, y las de las
colecciones que mantiene Archive (cine mudo, cine negro, ciencia ficción y terror, comedia,
dibujos clásicos, Prelinger). La licencia la declara quien sube el contenido y puede ser
incorrecta: por eso cada fila la muestra.

Qué se descarga: cada película de Archive guarda varias copias (MP4, MP4 de 512 kb, OGV, a veces
el MPEG2 original de varios GB) y su torrent las incluye todas. Se elige **una sola versión**
—primero formatos que se reproducen en cualquier sitio (MP4/MKV), después la mayor resolución—
más sus subtítulos `.srt`, y el motor P2P descarga **solo esos archivos**. Si la película está
dividida en partes (`1of5`, `parte2`, `reel3`…) se descargan todas. El tamaño de la tabla es el
de esos archivos, no el del ítem completo.

Detalle técnico: los *web seeds* de los torrents de Archive (`archive.org/download/`) redirigen
al servidor que guarda el ítem, y tras una redirección libtorrent no puede completar las piezas
que el archivo elegido comparte con los vecinos (la descarga se quedaba en ~94 %). Por eso se
añaden las URL directas de esos servidores (`web_seeds` en `DownloadRequest`).

### Añadir otro buscador

1. Crea un módulo en `app/core/search/`.
2. Hereda de `BaseSearchProvider` e implementa `search(query) -> list[SearchResult]`. Cada
   resultado indica `download_url` y `download_type` (y, si es un torrent, `files`/`web_seeds`).
3. Decora la clase con `@register_search_provider` e impórtala en `app/core/search/__init__.py`.

Las pruebas de `tests/test_search.py` muestran cómo probar un proveedor sin red.

## Solución de problemas

- **Registro (`media_downloader.log`):** botón **Abrir archivo de logs** en la ventana. Se
  guarda en la carpeta del proyecto (o junto al ejecutable) con todos los eventos, avisos y
  errores de la app y de yt-dlp (inicio, enlace resuelto, pausas, reintentos, fin). Rota a los
  5 MB y conserva 3 copias. Si esa carpeta no admite escritura (p. ej. en «Archivos de
  programa»), se usa `%LOCALAPPDATA%\MediaDownloader\` o `~/.local/share/media-downloader/`,
  donde también está `self-check.txt`.
- **Diagnóstico rápido:** `MediaDownloader.exe --self-check` (o `python main.py --self-check`).
- **Prueba de descarga real sin interfaz:** `MediaDownloader.exe --test-download URL` descarga el
  enlace (calidad baja) en la carpeta de datos del usuario (`test-download/`) y deja el resultado en
  `self-check.txt` y en el log. Código de salida 0 = correcto.
- **Windows SmartScreen / antivirus:** los ejecutables de PyInstaller sin firmar pueden
  mostrar advertencias, sobre todo en `--onefile`. Usa `--onedir` o firma el ejecutable.
- **Linux, "no se puede abrir el lanzador":** haz clic derecho sobre el icono del Escritorio →
  *Permitir ejecutar* (algunos entornos lo exigen además del `chmod +x`).
- **Linux: la descarga llega al 100 % y el archivo desaparece** (1.0.0 en distribuciones más
  nuevas que Ubuntu 22.04, p. ej. 24.04): corregido en la 1.0.1. El ejecutable apunta
  `LD_LIBRARY_PATH` a sus bibliotecas y el `ffprobe` del sistema las heredaba y no arrancaba
  (`GLIBCXX_3.4.32 not found`); el validador lo tomaba por un archivo dañado. La CI prueba ahora
  el binario de Linux también en Ubuntu 24.04 con una descarga real.
- **«Acceso denegado» (403) en video web:** revisa el *Referer* (debe ser la página del
  reproductor, a veces la del iframe) y que el enlace no haya caducado.
- **Las descargas de YouTube empiezan a fallar:** actualiza yt-dlp y vuelve a compilar:

```bash
pip install -U "yt-dlp[default]"
```

## Añadir una nueva fuente
1. Crea un módulo junto a `app/core/downloader.py`.
2. Si usa yt-dlp, hereda de `YtDlpDownloader` y sobrescribe solo `can_handle`,
   `supported_types` y, si hace falta, `_resolve`/`_analyze` (como `generic.py`). Si no,
   hereda de `BaseDownloader` e implementa `download(...)` y opcionalmente `list_qualities(...)`.
3. Decora la clase con `@register_downloader` e impórtala en `app/core/__init__.py`
   **antes** de `generic` (el genérico debe quedar el último).

La GUI llama a `get_downloader(url)`, que elige el proveedor adecuado; no hace falta tocarla
salvo para añadir opciones nuevas.

> Descarga solo contenido del que tengas derechos o que su licencia permita descargar.
