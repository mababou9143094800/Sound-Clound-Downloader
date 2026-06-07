"""
SoundCloud Downloader — Launcher
Verifie et installe toutes les dependances, puis lance l'interface web.
Fonctionne en tant que script Python OU en .exe compile avec PyInstaller.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ANSI colors (Windows 10+)
os.system("")
GRN = "\033[92m"
RED = "\033[91m"
YLW = "\033[93m"
CYN = "\033[96m"
BLD = "\033[1m"
DIM = "\033[2m"
RST = "\033[0m"

IS_EXE = getattr(sys, "frozen", False)
SCRIPT_DIR = Path(sys.executable).parent if IS_EXE else Path(__file__).parent

PIP_PACKAGES = ["flask", "curl_cffi"]


# ── Helpers ────────────────────────────────────────────────────────────────────

def clr(msg, color):
    print(f"  {color}{msg}{RST}", flush=True)

def ok(msg):   clr(f"✓  {msg}", GRN)
def err(msg):  clr(f"✗  {msg}", RED)
def info(msg): clr(f"→  {msg}", CYN)
def warn(msg): clr(f"⚠  {msg}", YLW)


# ── Python ─────────────────────────────────────────────────────────────────────

def find_python() -> str | None:
    """Cherche un Python 3.8+ valide sur le systeme."""
    candidates = ["python", "python3", "py"]
    lad = os.environ.get("LOCALAPPDATA", "")
    pf  = os.environ.get("ProgramFiles", "")
    pf86 = os.environ.get("ProgramFiles(x86)", "")
    for ver in ["314", "313", "312", "311", "310", "39", "38"]:
        for base in [lad, pf, pf86]:
            if base:
                candidates.append(str(Path(base) / f"Programs/Python/Python{ver}/python.exe"))
                candidates.append(str(Path(base) / f"Python{ver}/python.exe"))

    for c in candidates:
        try:
            r = subprocess.run(
                [c, "-c", "import sys; exit(0 if sys.version_info>=(3,8) else 1)"],
                capture_output=True, timeout=5,
            )
            if r.returncode == 0:
                return c
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    return None


def install_python_winget() -> bool:
    info("Installation de Python via winget (patiente 1-2 minutes)...")
    r = subprocess.run(
        ["winget", "install", "Python.Python.3.12", "-e",
         "--silent", "--accept-source-agreements", "--accept-package-agreements"],
        capture_output=True, text=True, timeout=300,
    )
    return r.returncode == 0


def install_python_direct() -> bool:
    """Telecharge et installe Python depuis python.org."""
    import urllib.request, tempfile
    url = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
    info("Telechargement de Python depuis python.org...")
    try:
        tmp = tempfile.mktemp(suffix=".exe")
        urllib.request.urlretrieve(url, tmp)
        info("Installation de Python (fenetres peuvent apparaitre)...")
        r = subprocess.run(
            [tmp, "/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_test=0"],
            timeout=300,
        )
        os.unlink(tmp)
        return r.returncode == 0
    except Exception as e:
        warn(f"Echec du telechargement : {e}")
        return False


def refresh_path():
    """Recharge le PATH depuis la base de registres Windows."""
    try:
        import winreg
        paths = []
        for hive, key in [
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            (winreg.HKEY_CURRENT_USER, r"Environment"),
        ]:
            try:
                with winreg.OpenKey(hive, key) as k:
                    paths.append(winreg.QueryValueEx(k, "PATH")[0])
            except FileNotFoundError:
                pass
        if paths:
            os.environ["PATH"] = ";".join(paths)
    except Exception:
        pass


# ── Pip packages ───────────────────────────────────────────────────────────────

def pkg_ok(python_exe: str, package: str) -> bool:
    name = package.replace("-", "_").split("[")[0]
    r = subprocess.run([python_exe, "-c", f"import {name}"],
                       capture_output=True, timeout=15)
    return r.returncode == 0


def install_pkgs(python_exe: str, packages: list[str]) -> bool:
    r = subprocess.run(
        [python_exe, "-m", "pip", "install", "--upgrade", "--quiet", *packages],
        capture_output=True, text=True, timeout=300,
    )
    return r.returncode == 0


# ── FFmpeg ─────────────────────────────────────────────────────────────────────

def ffmpeg_ok() -> bool:
    return shutil.which("ffmpeg") is not None


def install_ffmpeg_winget() -> bool:
    info("Installation de ffmpeg via winget (patiente 1-2 minutes)...")
    r = subprocess.run(
        ["winget", "install", "Gyan.FFmpeg", "-e",
         "--silent", "--accept-source-agreements", "--accept-package-agreements"],
        capture_output=True, text=True, timeout=300,
    )
    return r.returncode == 0


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    os.system("cls")
    print(f"""
{CYN}╔══════════════════════════════════════════════════════╗
║   🎵  SoundCloud Downloader  —  Demarrage           ║
╚══════════════════════════════════════════════════════╝{RST}
""")

    # ── 1. Python ──────────────────────────────────────────────────────
    print(f"{BLD}[1/3] Verification de Python{RST}")

    if IS_EXE:
        python_exe = find_python()
        if not python_exe:
            info("Python non trouve — tentative d'installation automatique...")
            if install_python_winget() or install_python_direct():
                refresh_path()
                python_exe = find_python()

        if not python_exe:
            err("Impossible d'installer Python automatiquement.")
            print()
            warn("Installe Python manuellement en 3 etapes :")
            print(f"  {DIM}1. Va sur  https://www.python.org/downloads{RST}")
            print(f"  {DIM}2. Clique 'Download Python' et lance l'installateur{RST}")
            print(f"  {DIM}3. IMPORTANT : coche la case 'Add Python to PATH'{RST}")
            print(f"  {DIM}4. Relance ce programme{RST}")
            input("\n  Appuie sur Entree pour fermer...")
            return
        ok(f"Python trouve : {python_exe}")
    else:
        python_exe = sys.executable
        ok(f"Python {sys.version.split()[0]}")

    # ── 2. Packages pip ────────────────────────────────────────────────
    print(f"\n{BLD}[2/3] Packages Python{RST}")
    missing = [p for p in PIP_PACKAGES if not pkg_ok(python_exe, p)]

    if missing:
        info(f"Installation : {', '.join(missing)}")
        if install_pkgs(python_exe, missing):
            ok("Packages installes avec succes")
        else:
            err("Erreur lors de l'installation des packages")
            warn("Essaie manuellement dans un terminal :")
            print(f"  {DIM}pip install {' '.join(missing)}{RST}")
            input("\n  Appuie sur Entree pour fermer...")
            return
    else:
        ok("Tous les packages sont deja presents")

    # ── 3. FFmpeg ──────────────────────────────────────────────────────
    print(f"\n{BLD}[3/3] FFmpeg (conversion audio){RST}")

    if not ffmpeg_ok():
        if install_ffmpeg_winget():
            refresh_path()
            if ffmpeg_ok():
                ok("FFmpeg installe avec succes")
            else:
                warn("FFmpeg installe — redemarrage necessaire pour l'activer")
        else:
            warn("FFmpeg non installe automatiquement")
            warn("Telechargez-le sur  https://ffmpeg.org/download.html")
            warn("et ajoutez-le au PATH Windows pour la conversion audio")
    else:
        ok("FFmpeg present")

    # ── Lancement ──────────────────────────────────────────────────────
    app_path = SCRIPT_DIR / "app.py"
    if not app_path.exists():
        err(f"app.py introuvable dans : {SCRIPT_DIR}")
        warn("Place ce fichier dans le meme dossier que app.py et downloader.py")
        input("\n  Appuie sur Entree pour fermer...")
        return

    print(f"\n{GRN}{'─'*54}{RST}")
    ok("Tout est pret !  Le navigateur va s'ouvrir...")
    print(f"{GRN}{'─'*54}{RST}")
    print(f"\n  {DIM}Ferme cette fenetre pour arreter le serveur.{RST}\n")
    time.sleep(1)

    subprocess.run([python_exe, str(app_path)])


if __name__ == "__main__":
    main()
