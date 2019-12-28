import subprocess as sp
import tempfile
from itertools import chain
from multiprocessing import Process
from pathlib import Path
from urllib.parse import quote

import requests
from utils import find_startswith, sp_args

PORT = 2369  # Just some random port
temp_dir = Path(tempfile.gettempdir())


def serve_dir(path):
    """Serve the given directory using a simple HTTP server on localhost."""
    Process(
        target=sp.run,
        args=[["python", "-m", "http.server", str(PORT), "-d", str(path)]],
        kwargs=sp_args
    ).start()


def get_variants(stream_url):
    resp = requests.get(stream_url)
    master_pls = resp.text
    variant_urls = [line for line in master_pls.splitlines() if line.startswith("http")]
    return {
        ("450p", "720p")["720" in url]: requests.get(url).text for url in variant_urls
    }


def get_variant_playlist(stream_url, quality):
    assert quality in ("720p", "450p"), "Incorrect quality given"
    variants = get_variants(stream_url)
    if not variants:
        return None
    variant = variants.get(quality)
    if not variant:
        variant = variants[max(variants)]
    return variant


def get_angle_playlists(variant_pls):
    """Split the playlist into two at #EXT-X-DISCONTINUITY, one for each angle"""
    pls = variant_pls.splitlines()
    headers_end = find_startswith(pls, "#EXT-X-KEY")
    headers = pls[:headers_end]
    angle1_end = find_startswith(pls, "#EXT-X-DISCONTINUITY")
    angle1 = pls[:angle1_end] + ["#EXT-X-ENDLIST", ""]

    angle2 = pls[angle1_end + 1 :]
    if not angle2[0].startswith("#EXT-X-KEY"):  # get key from previous section
        last_key = find_startswith(angle1, "#EXT-X-KEY", rev=True)
        angle2.insert(0, angle1[last_key])
    angle2 = headers + angle2
    return {1: "\n".join(angle1), 2: "\n".join(angle2)}


def download_stream(token, stream_url, output_file: Path, quality="720p", angle=0):
    cmd = [
        "ffmpeg",
        "-loglevel",
        "fatal",
        "-protocol_whitelist",
        "file,http,tcp,tls,crypto",
    ]
    cookies_arg = ("-cookies", f"Bearer={token}; path=/")  # needed to get auth to work
    variant_pls = get_variant_playlist(stream_url, quality)
    if not variant_pls:
        print("Some error while getting", stream_url)
        return
    angle_playlists = get_angle_playlists(variant_pls)
    for angle_num, angle_pls in angle_playlists.items():
        if angle and angle_num != angle:
            continue
        file_name = f"{output_file.stem}_{quality}_{angle_num}.m3u8"
        with open(temp_dir / file_name, "w") as f:
            f.write(angle_pls)
        # the -cookies flag is only recognized by ffmpeg when the input is via http
        # so we serve the hls playlist via an http server, and send that as input
        cmd += cookies_arg + ("-i", f"http://localhost:{PORT}/{quote(file_name)}")

    if not angle:
        # map all the input audio and video streams into separate tracks in output
        cmd += chain.from_iterable(
            ("-map", f"{i}:0", "-map", f"{i}:2") for i in range(len(angle_playlists))
        )

    cmd += ["-c", "copy", str(output_file)]
    print("Downloading", output_file.name)
    sp.call(cmd, **sp_args)
    print("Downloaded", output_file.name)


serve_dir(temp_dir)  # serve the dir which stores the angle playlists
