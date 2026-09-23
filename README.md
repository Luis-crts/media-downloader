# Media Downloader

Aplicación de escritorio (Python + CustomTkinter) para descargar música y videos de YouTube
con **yt-dlp** y **FFmpeg**. Se distribuye como ejecutable para Windows y Linux, con acceso
directo en el Escritorio y en el menú de aplicaciones. Está pensada para crecer con nuevas
fuentes (p. ej. películas).

- [Estructura](#estructura)
- [Opción 1: usar el ejecutable (usuarios)](#opción-1-usar-el-ejecutable-usuarios)
- [Opción 2: ejecutar desde el código (desarrollo)](#opción-2-ejecutar-desde-el-código-desarrollo)
- [Compilar el ejecutable](#compilar-el-ejecutable)
- [Accesos directos](#accesos-directos)
- [FFmpeg](#ffmpeg)
- [Uso](#uso)
- [Solución de problemas](#solución-de-problemas)
- [Añadir una nueva fuente](#añadir-una-nueva-fuente-p-ej-películas)

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
    └── core/
        ├── base.py                # Contratos: BaseDownloader, modelos, errores, registro
        ├── downloader.py          # Proveedor de YouTube (yt-dlp)
        └── dependencies.py        # Detección de FFmpeg, runtime JS y conexión
```

- **`core` no importa nada de la GUI.** Puede usarse desde una CLI, una API web o tests.
- La descarga corre en un **hilo secundario**; el progreso llega a la GUI mediante una
  `queue.Queue` que se consulta con `after()` (Tkinter no es thread-safe).
- Los errores se traducen a excepciones propias (`InvalidURLError`, `NetworkError`,
  `FFmpegNotFoundError`, `ContentUnavailableError`, `DownloadCancelledError`) con mensajes
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
El informe se guarda en `self-check.txt` dentro de la carpeta de datos (ver
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
3. Elige la carpeta de destino y pulsa **Descargar**.

Las listas se guardan en una subcarpeta con su nombre y numeradas (`001 - Título.mp3`).
Si un elemento de la lista no está disponible, se omite y se informa al final.
Al cancelar quedan archivos `.part` que se reanudan si repites la descarga.
La última carpeta, formato y tema se recuerdan en `~/.media_downloader.json`.

## Solución de problemas

- **Registros:** `app.log` y `self-check.txt` están en
  `%LOCALAPPDATA%\MediaDownloader\` (Windows) o `~/.local/share/media-downloader/` (Linux).
- **Diagnóstico rápido:** `MediaDownloader.exe --self-check` (o `python main.py --self-check`).
- **Windows SmartScreen / antivirus:** los ejecutables de PyInstaller sin firmar pueden
  mostrar advertencias, sobre todo en `--onefile`. Usa `--onedir` o firma el ejecutable.
- **Linux, "no se puede abrir el lanzador":** haz clic derecho sobre el icono del Escritorio →
  *Permitir ejecutar* (algunos entornos lo exigen además del `chmod +x`).
- **Las descargas de YouTube empiezan a fallar:** actualiza yt-dlp y vuelve a compilar:

```bash
pip install -U "yt-dlp[default]"
```

## Añadir una nueva fuente (p. ej. películas)
1. Crea un módulo junto a `app/core/downloader.py` (o en `app/core/providers/`).
2. Hereda de `BaseDownloader` e implementa `can_handle(url)` y
   `download(request, on_progress, cancel_event)`.
3. Decora la clase con `@register_downloader` e impórtala en `app/core/__init__.py`.

La GUI llama a `get_downloader(url)`, que elige el proveedor adecuado; no hace falta tocarla
salvo para añadir opciones nuevas.

> Descarga solo contenido del que tengas derechos o que su licencia permita descargar.
