import gooey
import subprocess
options = [("u", None, "OPTION"), ("u", None, "OPTION"), ("u", None, "OPTION")]
from pathlib import Path

def find_ffmpeg():
    ffmpeg = tuple(Path().glob("ffmpeg*"))
    if ffmpeg:
        return ffmpeg[0]
    try:
        return Path(subprocess.check_output(["where", "ffmpeg"]).decode().strip())
    except Exception as e:
        print("Could not find ffmpeg.")
        raise e

gooey_root = os.path.dirname(gooey.__file__)
gooey_languages = Tree(os.path.join(gooey_root, "languages"), prefix="gooey/languages")
gooey_images = Tree(os.path.join(gooey_root, "images"), prefix="gooey/images")

a = Analysis(
    ["ilc_scrape.py"],
    pathex=[""],
    binaries=[],
    datas=[(str(find_ffmpeg()), ".")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    options,
    gooey_languages,  # Add them in to collected files
    gooey_images,  # Same here.
    name="ImpartusScraper",
    debug=False,
    strip=False,
    upx=True,
    console=False,
    windowed=True,
    icon=os.path.join(gooey_root, "images", "program_icon.ico"),
)
