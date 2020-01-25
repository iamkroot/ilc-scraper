import subprocess as sp
import tempfile
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from itertools import chain
from multiprocessing.dummy import Process
from pathlib import Path
from urllib.parse import quote

import requests
from utils import find_startswith, sp_args


class DirServer(Process):
    """Serve the given directory using a simple HTTP server on localhost."""

    PORT = 2369  # Just some random port
    _dir_server = None  # Singleton instance

    def __new__(cls, *args, **kwargs):
        if not cls._dir_server:
            cls._dir_server = super().__new__(cls, *args, **kwargs)
        return cls._dir_server

    def __init__(self, dir_=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.daemon = True
        self.temp = dir_ is None
        if self.temp:  # Create a temp directory
            self.temp_dir = tempfile.TemporaryDirectory(prefix="ilc-scraper")
            self.dir = Path(self.temp_dir.name)
        else:  # Use given directory
            self.dir = Path(dir_)
            assert self.dir.exists()

        SimpleHTTPRequestHandler.log_message = lambda *a, **kw: None
        handler_class = partial(SimpleHTTPRequestHandler, directory=self.dir)
        self.server = HTTPServer(("localhost", self.PORT), handler_class)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc_info):
        if self.temp:
            self.temp_dir.cleanup()

        if exc_info and exc_info[0] and exc_info[0] != SystemExit:
            print(*exc_info)

    def run(self):
        self.server.serve_forever()

    @classmethod
    def get_url(cls, file_content):
        """Create a temp file with given contents and return its URL"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".m3u8", dir=cls._dir_server.dir, delete=False
        ) as f:
            f.write(file_content)
            name = Path(f.name).name
        return f"http://localhost:{cls.PORT}/{quote(name)}"


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
    if angle1_end is None:  # only one angle is present
        return {1: variant_pls}

    angle1 = pls[:angle1_end] + ["#EXT-X-ENDLIST", ""]

    angle2 = pls[angle1_end + 1 :]
    if not angle2[0].startswith("#EXT-X-KEY"):  # get key from previous section
        last_key = find_startswith(angle1, "#EXT-X-KEY", rev=True)
        angle2.insert(0, angle1[last_key])
    angle2 = headers + angle2
    return {1: "\n".join(angle1), 2: "\n".join(angle2)}


def add_inputs(token, cmd, angle_playlists, angle):
    cookies_arg = ("-cookies", f"Bearer={token}; path=/")  # needed to get auth to work

    if angle > len(angle_playlists):
        print(
            f"Invalid angle {angle} selected.",
            f"Downloading available angles: {', '.join(angle_playlists)}.",
        )
        angle = 0

    for angle_num, angle_pls in angle_playlists.items():
        if angle and angle_num != angle:
            continue
        # the -cookies flag is only recognized by ffmpeg when the input is via http
        # so we serve the hls playlist via an http server, and send that as input
        cmd += cookies_arg + ("-i", DirServer.get_url(angle_pls))

    if not angle:
        # map all the input audio and video streams into separate tracks in output
        cmd += chain.from_iterable(
            ("-map", f"{i}:v:0") for i in range(len(angle_playlists))
        )
    else:
        cmd.extend(("-map", "0:v:0"))
    cmd.extend(("-map", "0:a:0"))  # get first audio stream (assuming all are in sync)


def download_stream(token, stream_url, output_file: Path, quality="720p", angle=0):
    cmd = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-protocol_whitelist",
        "file,http,tcp,tls,crypto",
    ]
    variant_pls = get_variant_playlist(stream_url, quality)
    if not variant_pls:
        print("Some error while getting", stream_url)
        return
    angle_playlists = get_angle_playlists(variant_pls)
    add_inputs(token, cmd, angle_playlists, angle)

    cmd += ["-c", "copy", str(output_file)]

    print("Downloading", output_file.name)
    # TODO: Display ffmpeg download progress by parsing output
    proc = sp.run(cmd, text=True, **sp_args)
    if proc.returncode:
        print("ffmpeg error:", proc.stderr, "for", output_file.name)
    else:
        print("Downloaded", output_file.name)
