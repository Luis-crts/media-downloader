; Instalador de Media Downloader para Windows (Inno Setup 6).
;
; No se compila a mano: lo hace «python build.py --installer», que pasa estas constantes:
;   AppVersion  versión de la app (app/__init__.py)
;   DistDir     carpeta generada por PyInstaller (dist\MediaDownloader)
;   FFmpegDir   carpeta con ffmpeg.exe, ffprobe.exe y sus DLL (build LGPL)
;   OutputDir   dónde dejar MediaDownloader_Setup.exe

#ifndef AppVersion
  #error Compila con: python build.py --installer
#endif

#define AppName "Media Downloader"
#define AppExe "MediaDownloader.exe"
#define RootDir SourcePath + "..\.."

[Setup]
; AppId identifica la app para actualizaciones y desinstalación: no cambiarlo nunca.
AppId={{CA87270E-858E-4E19-B071-7170AAEF2B9F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Luis-crts
AppPublisherURL=https://github.com/Luis-crts/media-downloader
; Por defecto, instalación por usuario en %LOCALAPPDATA%\Programs\MediaDownloader (sin
; permisos de administrador). El asistente permite elegir «para todos los usuarios»
; (Program Files), que sí pide elevación.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\MediaDownloader
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile={#RootDir}\assets\icon.ico
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=MediaDownloader_Setup
; Cierra la app si está abierta durante una actualización o desinstalación.
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; La aplicación (PyInstaller --onedir).
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; FFmpeg junto al ejecutable, en bin\: la app lo busca ahí antes que en el PATH, así que
; el usuario no tiene que instalar nada más.
Source: "{#FFmpegDir}\bin\ffmpeg.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "{#FFmpegDir}\bin\ffprobe.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "{#FFmpegDir}\bin\*.dll"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "{#FFmpegDir}\LICENSE.txt"; DestDir: "{app}\bin"; DestName: "FFmpeg-LICENSE.txt"; Flags: ignoreversion
Source: "{#RootDir}\packaging\windows\FFmpeg-README.txt"; DestDir: "{app}\bin"; Flags: ignoreversion

[Icons]
; El icono (espada y engranajes) está embebido en el .exe. AppUserModelID debe coincidir
; con el de la app (MediaDownloader.App) para que Windows agrupe la ventana y atribuya las
; notificaciones a «Media Downloader».
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Comment: "Descarga música, videos y torrents"; AppUserModelID: "MediaDownloader.App"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon; AppUserModelID: "MediaDownloader.App"

[Registry]
; Registro de la app para las notificaciones de Windows (se elimina al desinstalar).
Root: HKA; Subkey: "Software\Classes\AppUserModelId\MediaDownloader.App"; ValueType: string; ValueName: "DisplayName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\AppUserModelId\MediaDownloader.App"; ValueType: string; ValueName: "IconUri"; ValueData: "{app}\_internal\assets\icon.png"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Archivos que la app crea junto al ejecutable mientras funciona.
Type: files; Name: "{app}\media_downloader.log*"
Type: dirifempty; Name: "{app}\bin"
Type: dirifempty; Name: "{app}"

[Code]
{ Al desinstalar, pregunta si borrar también los datos del usuario: configuración,
  cola guardada y registros. Con /SILENT o /VERYSILENT se conservan. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep <> usPostUninstall then
    exit;
  DataDir := ExpandConstant('{localappdata}\MediaDownloader');
  if UninstallSilent then
    exit;
  if MsgBox('¿Eliminar también la configuración, la cola de descargas guardada y los registros?' + #13#10 +
            '(Los archivos descargados no se tocan.)', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
  begin
    DelTree(DataDir, True, True, True);
    DeleteFile(ExpandConstant('{%USERPROFILE}\.media_downloader.json'));
  end;
end;
