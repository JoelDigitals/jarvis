import json, os, time, subprocess, tempfile, shutil, uuid
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
_OUTPUT_DIR = _BASE / "content" / "videos"
_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def _check_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return True
    except:
        return False

def _get_output_path(format: str = "mp4") -> str:
    return str(_OUTPUT_DIR / f"video_{uuid.uuid4().hex[:8]}.{format}")

def _create_from_images(image_paths: list[str], audio_path: str = "", duration: float = 3.0, fps: int = 24) -> str:
    if not _check_ffmpeg():
        return "FFmpeg nicht gefunden. Bitte installieren: https://ffmpeg.org"
    if not image_paths:
        return "Keine Bilder angegeben."

    out = _get_output_path()
    valid = [p for p in image_paths if Path(p).exists()]
    if not valid:
        return "Keine der angegebenen Bilddateien existiert."

    try:
        with tempfile.TemporaryDirectory() as td:
            list_path = Path(td) / "files.txt"
            with open(list_path, "w") as f:
                for p in valid:
                    abs_p = str(Path(p).resolve())
                    f.write(f"file '{abs_p}'\n")
                    f.write(f"duration {duration}\n")
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path)]
            if audio_path and Path(audio_path).exists():
                cmd += ["-i", audio_path, "-c:a", "aac", "-shortest"]
            cmd += ["-vf", f"fps={fps},format=yuv420p", "-c:v", "libx264", "-pix_fmt", "yuv420p", out]
            subprocess.run(cmd, capture_output=True, timeout=120)
            if Path(out).exists():
                size_mb = Path(out).stat().st_size / (1024 * 1024)
                return f"Video erstellt: {out} ({size_mb:.1f} MB)"
            return "Fehler bei der Video-Erstellung."
    except subprocess.TimeoutExpired:
        return "Timeout bei der Video-Erstellung (länger als 120s)."
    except Exception as e:
        return f"Fehler: {e}"

def _trim_video(input_path: str, start: str = "00:00:00", end: str = "") -> str:
    if not _check_ffmpeg():
        return "FFmpeg nicht gefunden."
    if not Path(input_path).exists():
        return "Eingabedatei nicht gefunden."
    out = _get_output_path()
    try:
        cmd = ["ffmpeg", "-y", "-i", input_path, "-ss", start]
        if end:
            cmd += ["-to", end]
        cmd += ["-c", "copy", out]
        subprocess.run(cmd, capture_output=True, timeout=300)
        if Path(out).exists():
            return f"Video getrimmt: {out}"
        return "Fehler beim Trimmen."
    except Exception as e:
        return f"Fehler: {e}"

def _concat_videos(input_paths: list[str]) -> str:
    if not _check_ffmpeg():
        return "FFmpeg nicht gefunden."
    valid = [p for p in input_paths if Path(p).exists()]
    if len(valid) < 2:
        return "Mindestens 2 gültige Videodateien benötigt."
    out = _get_output_path()
    try:
        with tempfile.TemporaryDirectory() as td:
            list_path = Path(td) / "videos.txt"
            with open(list_path, "w") as f:
                for p in valid:
                    f.write(f"file '{Path(p).resolve()}'\n")
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", out]
            subprocess.run(cmd, capture_output=True, timeout=300)
            if Path(out).exists():
                return f"Videos zusammengefügt: {out}"
            return "Fehler beim Zusammenfügen."
    except Exception as e:
        return f"Fehler: {e}"

def _add_text_overlay(input_path: str, text: str, position: str = "bottom") -> str:
    if not _check_ffmpeg():
        return "FFmpeg nicht gefunden."
    if not Path(input_path).exists():
        return "Eingabedatei nicht gefunden."
    out = _get_output_path()

    pos_map = {
        "top": "(w-text_w)/2:10",
        "bottom": "(w-text_w)/2:h-th-10",
        "center": "(w-text_w)/2:(h-th)/2",
    }
    pos = pos_map.get(position, pos_map["bottom"])

    try:
        escaped = text.replace("'", "'\\\\''")
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", f"drawtext=text='{escaped}':fontsize=24:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=5:x={pos}:fontfile='C\\:/Windows/Fonts/arial.ttf'",
            "-c:a", "copy", out
        ]
        subprocess.run(cmd, capture_output=True, timeout=300)
        if Path(out).exists():
            return f"Text hinzugefügt: {out}"
        return "Fehler beim Hinzufügen von Text."
    except Exception as e:
        return f"Fehler: {e}"

def video_action(parameters: dict = None, player=None) -> str:
    params = parameters or {}
    action = params.get("action", "create").lower().strip()
    images = params.get("images", [])
    audio = params.get("audio", "")
    duration = float(params.get("duration", 3.0))
    fps = int(params.get("fps", 24))
    input_path = params.get("input", "")
    start = params.get("start", "00:00:00")
    end = params.get("end", "")
    text = params.get("text", "")
    position = params.get("position", "bottom")
    paths = params.get("paths", [])

    if action == "create":
        return _create_from_images(images, audio, duration, fps)

    if action == "trim":
        return _trim_video(input_path, start, end)

    if action == "concat":
        return _concat_videos(paths)

    if action == "text":
        return _add_text_overlay(input_path, text, position)

    if action == "info":
        if not _check_ffmpeg():
            return "FFmpeg nicht gefunden."
        return f"FFmpeg verfügbar. Ausgabeverzeichnis: {_OUTPUT_DIR}"

    return f"Unbekannte Aktion: {action}. Verfügbar: create, trim, concat, text, info"
