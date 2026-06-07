"""
SoundCloud Downloader — sans scdl
Tous les appels API passent par curl_cffi (impersonation Chrome120).
ffmpeg gere le telechargement + conversion audio.

Usage:
    python downloader.py --token TOKEN --client-id CLIENT_ID [--format wav|flac|mp3-320|mp3]
"""

import argparse
import io
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from curl_cffi import requests as curl_requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)


# ── API helpers ────────────────────────────────────────────────────────────────

def api_get(url: str, token: str | None, **kwargs):
    headers = {}
    if token:
        headers["Authorization"] = f"OAuth {token}"
    for attempt in range(5):
        r = curl_requests.get(url, headers=headers, impersonate="chrome120",
                              timeout=30, **kwargs)
        if r.status_code == 429:
            wait = 15 * (attempt + 1)
            print(f"  429 rate-limit, attente {wait}s...")
            time.sleep(wait)
            continue
        if r.status_code == 403:
            return None  # signale 403 sans exception
        r.raise_for_status()
        return r
    return None


def get_fresh_client_id() -> str | None:
    patterns = [
        r'[,{]client_id:"([a-zA-Z0-9]{20,40})"',
        r'"client_id"\s*:\s*"([a-zA-Z0-9]{20,40})"',
        r'client_id:"([a-zA-Z0-9]{20,40})"',
        r'clientId:"([a-zA-Z0-9]{20,40})"',
        r'[?&]client_id=([a-zA-Z0-9]{20,40})',
    ]
    try:
        resp = curl_requests.get("https://soundcloud.com", impersonate="chrome120", timeout=15)
        js_urls = re.findall(r'<script[^>]+src="(https://[^"]+\.js)"', resp.text)
        for js_url in reversed(js_urls):
            try:
                js = curl_requests.get(js_url, impersonate="chrome120", timeout=10).text
                for pat in patterns:
                    m = re.search(pat, js)
                    if m:
                        return m.group(1)
            except Exception:
                continue
    except Exception:
        pass
    return None


def resolve_url(url: str, client_id: str, token: str | None) -> dict:
    r = api_get(
        f"https://api-v2.soundcloud.com/resolve?url={url}&client_id={client_id}",
        token,
    )
    if r is None:
        raise RuntimeError("403 sur resolve_url")
    return r.json()


def fetch_playlist_tracks(playlist: dict, client_id: str, token: str | None) -> list[str]:
    """Retourne les permalink_url de toutes les tracks d'une playlist."""
    tracks = playlist.get("tracks", [])
    urls: list[str] = []
    ids_a_charger: list[str] = []

    for t in tracks:
        pu = t.get("permalink_url")
        if pu:
            urls.append(pu)
        elif t.get("id"):
            ids_a_charger.append(str(t["id"]))

    # Certaines tracks n'ont que l'id — on les recupere par batch de 50
    for i in range(0, len(ids_a_charger), 50):
        batch = ids_a_charger[i:i + 50]
        r = api_get(
            f"https://api-v2.soundcloud.com/tracks?ids={','.join(batch)}&client_id={client_id}",
            token,
        )
        if r:
            for t in r.json():
                pu = t.get("permalink_url")
                if pu:
                    urls.append(pu)
        time.sleep(0.5)

    return urls


def fetch_all_tracks(user_id: int, client_id: str, token: str | None) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    next_href: str | None = (
        f"https://api-v2.soundcloud.com/stream/users/{user_id}"
        f"?client_id={client_id}&limit=200&linked_partitioning=1"
    )
    page = 0
    while next_href:
        page += 1
        print(f"  API page {page}...", end="\r")
        r = api_get(next_href, token)
        if r is None:
            raise RuntimeError("403 sur fetch_all_tracks")
        data = r.json()
        for item in data.get("collection", []):
            track = item.get("track") or (item if item.get("kind") == "track" else None)
            if track:
                pu = track.get("permalink_url")
                if pu and pu not in seen:
                    seen.add(pu)
                    urls.append(pu)
        next_href = data.get("next_href")
        if next_href and "client_id" not in next_href:
            next_href += f"&client_id={client_id}"
    print()
    return urls


# ── Download direct (curl_cffi + ffmpeg, sans scdl) ───────────────────────────

def resolve_track(track_url: str, client_id: str, token: str | None) -> dict | None:
    r = api_get(
        f"https://api-v2.soundcloud.com/resolve?url={track_url}&client_id={client_id}",
        token,
    )
    return r.json() if r else None


def best_transcoding(track: dict) -> dict | None:
    """Priorite : AAC HLS (Go+) > progressive MP3 > HLS MP3."""
    tcs = track.get("media", {}).get("transcodings", [])
    if not tcs:
        return None

    def score(tc):
        mime = tc.get("format", {}).get("mime_type", "")
        proto = tc.get("format", {}).get("protocol", "")
        if "mp4" in mime or "aac" in mime:  # AAC = Go+ 256kbps
            return 3
        if proto == "progressive":           # MP3 direct
            return 2
        if "mpeg" in mime:                   # HLS MP3
            return 1
        return 0

    return max(tcs, key=score)


def get_stream_url(tc: dict, client_id: str, token: str | None) -> str | None:
    r = api_get(f"{tc['url']}?client_id={client_id}", token)
    return r.json().get("url") if r else None


def safe_name(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).strip()[:180]


def ffmpeg_download(stream_url: str, dest: Path, fmt: str) -> bool:
    if fmt == "wav":
        acodec = ["-vn", "-acodec", "pcm_s16le", "-ar", "44100"]
    elif fmt == "flac":
        acodec = ["-vn", "-acodec", "flac"]
    elif fmt == "mp3-320":
        acodec = ["-vn", "-acodec", "libmp3lame", "-b:a", "320k"]
    else:  # mp3 natif (copy si possible)
        acodec = ["-vn", "-acodec", "libmp3lame", "-b:a", "128k"]

    cmd = ["ffmpeg", "-y", "-i", stream_url] + acodec + [str(dest)]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=600)
    if result.returncode != 0:
        err = (result.stderr or "")[-300:]
        print(f"    ffmpeg ERREUR: {err}")
    return result.returncode == 0


def load_archive(archive: Path) -> set[str]:
    if not archive.exists():
        return set()
    return set(archive.read_text(encoding="utf-8", errors="replace").splitlines())


def add_to_archive(archive: Path, entry: str) -> None:
    with open(archive, "a", encoding="utf-8") as f:
        f.write(entry + "\n")


def download_track(
    track_url: str,
    output: Path,
    archive_set: set[str],
    archive: Path,
    token: str | None,
    client_id: str,
    fmt: str,
) -> str:
    """Retourne 'ok', 'skip', '403', ou 'error'."""

    # 1. Resolve metadata
    track = resolve_track(track_url, client_id, token)
    if track is None:
        return "403"

    track_id = str(track.get("id", ""))
    archive_key = f"soundcloud {track_id}"

    # 2. Archive check
    if archive_key in archive_set:
        print("    [deja telecharge]")
        return "skip"

    # 3. Best transcoding
    tc = best_transcoding(track)
    if not tc:
        print("    [skip] aucun flux disponible")
        return "error"

    mime = tc.get("format", {}).get("mime_type", "?")
    proto = tc.get("format", {}).get("protocol", "?")

    # 4. Stream URL
    stream_url = get_stream_url(tc, client_id, token)
    if not stream_url:
        return "403"

    # 5. Filename
    artist = track.get("user", {}).get("username", "Unknown")
    title = track.get("title", "Unknown")
    ext_map = {"wav": "wav", "flac": "flac", "mp3-320": "mp3", "mp3": "mp3"}
    ext = ext_map.get(fmt, "mp3")
    dest = output / f"{safe_name(artist)} - {safe_name(title)}.{ext}"

    if dest.exists():
        add_to_archive(archive, archive_key)
        archive_set.add(archive_key)
        print(f"    [deja present] {dest.name}")
        return "skip"

    print(f"    {mime} / {proto} -> {ext.upper()}")

    # 6. Download + convert
    ok = ffmpeg_download(stream_url, dest, fmt)
    if ok:
        add_to_archive(archive, archive_key)
        archive_set.add(archive_key)
        print(f"    OK: {dest.name}")
    return "ok" if ok else "error"


# ── Main flow ──────────────────────────────────────────────────────────────────

def run(url: str, output: Path, token: str | None, client_id: str | None, fmt: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    archive = output / ".scdl_archive"

    fmt_labels = {
        "mp3": "MP3 128kbps (natif)",
        "mp3-320": "MP3 320kbps (re-encode)",
        "flac": "FLAC",
        "wav": "WAV (256kbps AAC source avec Go+)",
    }
    print(f"URL     : {url}")
    print(f"Format  : {fmt_labels.get(fmt, fmt)}")
    print(f"Dossier : {output.resolve()}")
    print(f"Token   : {'OK' if token else 'ABSENT'}")
    print()

    # Client ID
    if not client_id:
        print("Recuperation d'un client_id frais...")
        client_id = get_fresh_client_id()
        if not client_id:
            print("Impossible d'extraire le client_id automatiquement.")
            print("Lance avec --client-id XXXXX (F12 > Network sur SoundCloud)")
            sys.exit(1)
    print(f"client_id : {client_id}")

    # Resolve URL (profil, playlist, track...)
    print("Connexion a l'API SoundCloud...")
    try:
        resolved = resolve_url(url, client_id, token)
    except Exception as e:
        print(f"Erreur ({e}), nouveau client_id...")
        client_id = get_fresh_client_id() or client_id
        resolved = resolve_url(url, client_id, token)

    kind = resolved.get("kind", "")

    if kind == "user":
        print(f"Profil trouve : {resolved.get('username')} (id={resolved['id']})")
        print("Recuperation des tracks (uploads + reposts)...")
        track_urls = fetch_all_tracks(resolved["id"], client_id, token)

    elif kind in ("playlist", "system-playlist"):
        title = resolved.get("title", "?")
        count = resolved.get("track_count", "?")
        print(f"Playlist trouvee : {title} ({count} tracks)")
        print("Recuperation des tracks...")
        track_urls = fetch_playlist_tracks(resolved, client_id, token)

    elif kind == "track":
        print(f"Track trouvee : {resolved.get('title')}")
        track_urls = [resolved.get("permalink_url")]

    else:
        print(f"ERREUR : type non reconnu ({kind!r})")
        print("Fournissez l'URL d'un profil, d'une playlist ou d'une track.")
        sys.exit(1)

    print(f"{len(track_urls)} track(s) trouvee(s)\n{'-'*50}")

    archive_set = load_archive(archive)
    ok = skipped = 0
    failed_urls: list[str] = []
    consecutive_403 = 0

    for i, track_url in enumerate(track_urls, 1):
        name = track_url.split("/")[-1][:60]
        print(f"[{i}/{len(track_urls)}] {name}")

        try:
            status = download_track(track_url, output, archive_set, archive, token, client_id, fmt)
        except Exception as e:
            print(f"    EXCEPTION : {e}")
            status = "error"

        if status in ("ok", "skip"):
            if status == "ok":
                ok += 1
            else:
                skipped += 1
            consecutive_403 = 0
        elif status == "403":
            failed_urls.append(track_url)
            consecutive_403 += 1
            if consecutive_403 >= 3:
                wait = min(30 * consecutive_403, 120)
                print(f"  {consecutive_403} x 403 — attente {wait}s (rate-limit)...")
                time.sleep(wait)
                new_id = get_fresh_client_id()
                if new_id and new_id != client_id:
                    client_id = new_id
                    print(f"  Nouveau client_id : {client_id}")
                consecutive_403 = 0
        else:
            failed_urls.append(track_url)
            consecutive_403 = 0

        time.sleep(3)

    # Retry echecs
    still_failed: list[str] = []
    if failed_urls:
        print(f"\n{'-'*50}")
        print(f"Retry de {len(failed_urls)} echec(s) dans 60s...")
        time.sleep(60)
        consecutive_403 = 0
        for i, track_url in enumerate(failed_urls, 1):
            name = track_url.split("/")[-1][:60]
            print(f"  [retry {i}/{len(failed_urls)}] {name}")
            try:
                status = download_track(track_url, output, archive_set, archive, token, client_id, fmt)
            except Exception as e:
                print(f"    EXCEPTION : {e}")
                status = "error"
            if status in ("ok", "skip"):
                if status == "ok":
                    ok += 1
            else:
                still_failed.append(track_url)
            time.sleep(5)

        if still_failed:
            retry_file = output / "failed_tracks.txt"
            retry_file.write_text("\n".join(still_failed), encoding="utf-8")
            print(f"\n  {len(still_failed)} track(s) toujours en echec -> {retry_file}")

    print(f"\n{'-'*50}")
    print(f"Termine : {ok} telecharge(s)  |  {skipped} deja presents  |  {len(still_failed)} echec(s)")
    print(f"Fichiers dans : {output.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Telecharge toutes les musiques SoundCloud via API directe + ffmpeg"
    )
    parser.add_argument("--url",       default="https://soundcloud.com/leap1")
    parser.add_argument("--output",    default=r"D:\downloads")
    parser.add_argument("--token",     default=None,
                        help="OAuth token (F12 > Network > Authorization: OAuth XXXXX)")
    parser.add_argument("--client-id", default=None, dest="client_id",
                        help="Client ID (F12 > Network > ?client_id=XXXXX)")
    parser.add_argument("--format",    default="wav",
                        choices=["mp3", "mp3-320", "flac", "wav"])
    args = parser.parse_args()

    run(
        url=args.url,
        output=Path(args.output),
        token=args.token,
        client_id=args.client_id,
        fmt=args.format,
    )


if __name__ == "__main__":
    main()
