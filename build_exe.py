"""Baut Jarvis.exe aus dem Quellcode. Aufruf: python build_exe.py"""
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent

if __name__ == "__main__":
    subprocess.check_call([sys.executable, "-m", "PyInstaller", "jarvis.spec", "--noconfirm"], cwd=str(BASE))
    print("\nFertig. Jarvis.exe liegt in dist/Jarvis/Jarvis.exe")
