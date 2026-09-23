# Media Downloader

Aplicación de escritorio (Python + CustomTkinter) para descargar música y videos de YouTube,
y películas/videos de la web (streams **HLS/M3U8**, DASH, enlaces directos y los más de 1800
sitios que reconoce yt-dlp), con **yt-dlp** y **FFmpeg**. Se distribuye como ejecutable para
Windows y Linux, con acceso directo en el Escritorio y en el menú de aplicaciones.

- [Estructura](#estructura)
- [Opción 1: usar el ejecutable (usuarios)](#opción-1-usar-el-ejecutable-usuarios)
- [Opción 2: ejecutar desde el código (desarrollo)](#opción-2-ejecutar-desde-el-código-desarrollo)
- [Compilar el ejecutable](#compilar-el-ejecutable)
- [Accesos directos](#accesos-directos)
- [FFmpeg](#ffmpeg)
- [Uso](#uso)
- [Películas / Video web (M3U8)](#películas--video-web-m3u8)
- [Solución de problemas](#solución-de-problemas)
- [Añadir una nueva fuente](#añadir-una-nueva-fuente)

## Estructura

```
App musica/
├── main.py                        # Punto de entrada (+ --self-check)
├── build.py                       # Compilación con PyInstaller (Windows/Linux)
├── requirements.txt               # Dependencias de ejecución
├── requirements-dev.txt           # + PyInstaller y Pillow
├── assets/                        # icon.ico (Windows) e icon.png (Linux)
├── bin/                           # (opcional) ffmpeg + ffprobe portables
├── packaging/make_icon.py         # Regenera los iconos
├── scripts/
│   ├── install_shortcuts_windows.ps1   # Crea los .lnk (Escritorio + Menú Inicio)
│   ├── install_shortcuts_windows.bat   # Lo mismo, con doble clic
│   └── install_shortcuts_linux.sh      # Crea los .desktop (menú + Escritorio)
├── .github/workflows/build.yml    # CI: compila y verifica en Windows y Linux
└── app/
    ├── paths.py                   # Rutas compatibles con PyInstaller (sys._MEIPASS)
    ├── gui.py                     # Interfaz CustomTkinter (solo presentación)
    ├── widgets.py                 # Sección plegable y lista de la cola
    ├── download_queue.py          # Modelo de la cola (sin interfaz, con pruebas)
    └── core/
        ├── base.py                # Contratos: BaseDownloader, modelos, errores, registro
        ├── ytdlp_backend.py       # Flujo común yt-dlp: analizar, descargar, progreso, errores
        ├── downloader.py          # Proveedor YouTube
        ├── generic.py             # Proveedor Web / M3U8 (respaldo para cualquier URL)
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

## Opción 1: usar el ejecutable (usuarios)

1. Descarga la compilación de tu sistema desde la pestaña **Actions** del repositorio
   (artefactos `MediaDownloader-windows` o `MediaDownloader-linux`) o compílala tú
   ([ver más abajo](#compilar-el-ejecutable)).
2. Instala [FFmpeg](#ffmpeg) (salvo que la compilación lo lleve embebido).
3. Crea los [accesos directos](#accesos-directos).
4. Abre **Media Downloader** desde el Escritorio o el menú. No se abre ninguna terminal.

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
pyinstaller main.py --name MediaDownloader --onedir --windowed --noconfirm --clean --add-data "assets;assets" --collect-data customtkinter --collect-data yt_dlp_ejs --icon assets/icon.ico
```

- `--windowed` (equivale a `--noconsole` / `-w`): no aparece la consola de fondo. En este modo
  `sys.stdout`/`sys.stderr` son `None`, así que la app registra en un archivo y muestra los
  errores fatales en un diálogo.
- `--add-data assets`: iconos accesibles en tiempo de ejecución.
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
- *Quitar* elimina un pendiente; *Abrir* abre la carpeta de una completada; *Vaciar
  pendientes* y *Limpiar terminadas* actúan sobre toda la lista.
- Un enlace que ya está pendiente o en curso (mismo enlace y formato) no se añade dos veces.
- Los errores quedan en la fila y en *Actividad*; el diálogo de error solo aparece cuando la
  cola se detiene, para no bloquear las descargas siguientes.
- *Analizar* (calidades) funciona también mientras hay una descarga en curso.
- La cola vive en memoria: al cerrar la aplicación con elementos pendientes se pide
  confirmación y no se conservan para la próxima sesión.

Las listas se guardan en una subcarpeta con su nombre y numeradas (`001 - Título.mp3`).
Si un elemento de la lista no está disponible, se omite y se informa al final.
La última carpeta, formato, subtítulos y tema se recuerdan en `~/.media_downloader.json`.

### Pausar, reanudar y cancelar

- **Pausar** detiene la recepción de datos al instante: el hilo de descarga (y, en HLS, cada
  hilo de segmentos) queda en espera y no se piden más segmentos. Lo descargado se conserva.
- **Reanudar** continúa desde el mismo byte o segmento. Si durante una pausa larga el
  servidor cerró la conexión, yt-dlp la reabre automáticamente y sigue donde iba.
- Si pausas mientras FFmpeg une o convierte el archivo, la pausa se aplica al terminar ese paso.
- **Cancelar** (también en pausa) deja los archivos `.part`; si repites la misma descarga se
  reanuda desde ellos.

### Subtítulos

Solo para *Video MP4* y *Películas / Video web*. Se descargan los subtítulos manuales y, si no
hay, los automáticos; se convierten a **SRT**, se **incrustan** en el MP4 como pista de texto y
se conserva también el `.srt` junto al video.

- **Idiomas:** códigos separados por comas (`es, en`). Cada código incluye sus variantes
  regionales (`es` → `es`, `es-ES`, `es-419`). `all` descarga todos.
- Se excluyen a propósito las **traducciones automáticas** de YouTube (`es-de`, `en-fr`…:
  decenas por video, que provocan bloqueos HTTP 429). Para pedir una concreta, escribe su
  código completo: `es-en` = español traducido del inglés.
- En streams HLS se usan las pistas de subtítulos del propio `.m3u8` si las hay.
- Si un subtítulo falla, el video se descarga igualmente y el aviso queda en el log.

### Cortes de red

Cada petición y cada segmento HLS/DASH se reintentan hasta **20 veces**, con espera creciente
entre intentos (1, 2, 4, 8 y luego 10 s) y un tiempo de espera de conexión de **30 s**. Los
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

## Solución de problemas

- **Registro (`media_downloader.log`):** botón **Abrir archivo de logs** en la ventana. Se
  guarda en la carpeta del proyecto (o junto al ejecutable) con todos los eventos, avisos y
  errores de la app y de yt-dlp (inicio, enlace resuelto, pausas, reintentos, fin). Rota a los
  5 MB y conserva 3 copias. Si esa carpeta no admite escritura (p. ej. en «Archivos de
  programa»), se usa `%LOCALAPPDATA%\MediaDownloader\` o `~/.local/share/media-downloader/`,
  donde también está `self-check.txt`.
- **Diagnóstico rápido:** `MediaDownloader.exe --self-check` (o `python main.py --self-check`).
- **Windows SmartScreen / antivirus:** los ejecutables de PyInstaller sin firmar pueden
  mostrar advertencias, sobre todo en `--onefile`. Usa `--onedir` o firma el ejecutable.
- **Linux, "no se puede abrir el lanzador":** haz clic derecho sobre el icono del Escritorio →
  *Permitir ejecutar* (algunos entornos lo exigen además del `chmod +x`).
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
