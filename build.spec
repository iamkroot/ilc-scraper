import gooey
import subprocess as sp
from pathlib import Path


def find_ffmpeg():
    ffmpeg = tuple(Path().glob("ffmpeg*"))
    if ffmpeg:
        return ffmpeg[0]
    try:
        if os.name == "nt":
            ffmpeg = Path(sp.check_output(["where", "ffmpeg"]).decode().strip())
            assert ffmpeg.suffix == ".exe"
        else:
            output = sp.check_output(["whereis", "-b", "ffmpeg"]).decode().strip()
            assert output
            ffmpeg = Path(output.split()[1])
            assert ffmpeg.is_file() and not ffmpeg.is_symlink()
    except Exception as e:
        print("Could not find ffmpeg.")
        raise e
    else:
        return ffmpeg.absolute()


gooey_root = Path(gooey.__file__).parent
gooey_languages = Tree(str(gooey_root / "languages"), prefix="gooey/languages")
gooey_images = Tree(str(gooey_root / "images"), prefix="gooey/images")
options = [("u", None, "OPTION"), ("u", None, "OPTION"), ("u", None, "OPTION")]

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
    gooey_languages,
    gooey_images,
    name="ImpartusScraper",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    windowed=True,
    icon=os.path.join(gooey_root, "images", "program_icon.ico"),
)
