#!/usr/bin/env python
import multiprocessing
import os
import re
import subprocess as sp
import urllib
import requests
from argparse import ArgumentTypeError
from difflib import get_close_matches
from multiprocessing.pool import Pool
from pathlib import Path
from utils import sp_args, print_quit, read_json, store_json, sanitize_filepath

try:
    from gooey import Gooey, GooeyParser
except ImportError:  # Gooey not installed
    from utils import Gooey, GooeyParser  # dummy objects
else:
    from utils import print  # override print with flush=True for Gooey support

SCRIPT_DIR = Path(__file__).parent.absolute()
CONFIG_FILE = SCRIPT_DIR / "imp_config.json"
DATA_FILE = SCRIPT_DIR / "imp_data.json"
IMP_BASE_URL = "http://172.16.3.20/"
IMP_LOGIN_URL = IMP_BASE_URL + "api/auth/signin"
IMP_STREAM_URL = IMP_BASE_URL + "api/fetchvideo?ttid={}&token={}&type=index.m3u8"
IMP_LECTURES_URL = IMP_BASE_URL + "api/subjects/{}/lectures/{}"

CATALOG_PAT = re.compile(
    r"(https?://)?(172\.16\.3\.20/ilc/#/course/)(?P<subject>\d+)/(?P<lec>\d+)/?"
)
RANGE_PAT = re.compile(r"\s*(?P<l>\d*)(\s*:\s*(?P<r>\d*))?\s*")  # ignore spaces


@Gooey(
    program_name="Impartus Scraper",
    default_size=(1280, 720),
    richtext_controls=True,
    disable_progress_bar_animation=True,
)
def parse_args(config, data):
    def closest(choice):
        match = get_close_matches(choice.upper(), data["urls"], 1, 0.2)
        if not match:
            raise ArgumentTypeError(
                "Could not find course in local database. "
                "Ensure that it has been downloaded at least once using URL."
            )
        return match[0]

    def validate_url(url):
        match = CATALOG_PAT.match(url)
        if not match:
            err_msg = "URL doesn't match required pattern."
            if "a.impartus" in url:
                err_msg += " Should be intranet link (172.16.3.20)."
            raise ArgumentTypeError(err_msg)
        return IMP_LECTURES_URL.format(match["subject"], match["lec"])

    creds = config.get("creds", {})
    parser = GooeyParser(
        description="A scraper for Impartus Lecture Capture videos for BITS Hyderabad"
    )
    creds_group = parser.add_argument_group(
        "Credentials",
        (
            "Your impartus creds. "
            "(Only needed for login, "
            "you will be able download courses you aren't subscribed to.)"
        ),
        gooey_options={"columns": 3},
    )
    creds_group.add_argument("-u", "--username", default=creds.get("username"))
    creds_group.add_argument(
        "-p", "--password", default=creds.get("password"), widget="PasswordField"
    )
    creds_group.add_argument(
        "-s",
        "--save-creds",
        action="store_true",
        help="Save credentials so that they can be automatically loaded in the future",
    )
    main_args = parser.add_argument_group(
        "Download options", gooey_options={"columns": 2 if data["urls"] else 1}
    )
    if data["urls"]:
        course_group = main_args.add_mutually_exclusive_group(required=True)
        course_group.add_argument(
            "-n",
            "--name",
            choices=data["urls"],
            type=closest,
            help="Name of previously downloaded course.",
        )
    else:
        course_group = main_args
    course_group.add_argument(
        "-c",
        "--course_url",
        type=validate_url,
        help=(
            "Full impartus URL of course\n"
            "(Eg: http://172.16.3.20/ilc/#/course/12345/789)"
        ),
        required=not data["urls"],
    )
    range_group = main_args.add_mutually_exclusive_group()
    range_group.add_argument(
        "-r",
        "--range",
        default="",
        help="\n".join(
            (
                "Range of lectures to be downloaded. Hint-",
                " 12 (Only 12 will be downloaded),",
                " 1:4 (1 included, 4 excluded),",
                " :10 (Download lecture numbers 1 to 9),",
                " 3: (Download all lectures from number 3 onwards).",
                "You can also specify multiple ranges using commas.",
                "Eg- 12, 4:6, 15:, :2 will download 1, 4, 5, 12, 15, 16, 17, ..."
                "Leave blank to download all.",
            )
        ),
    )
    range_group.add_argument(
        "-o",
        "--only-new",
        action="store_true",
        help="Get all lectures after the last downloaded one.",
    )
    main_args.add_argument(
        "-d",
        "--dest",
        default=config.get("save_fold", SCRIPT_DIR / "Impartus Lectures"),
        type=Path,
        help=f"Download folder",
        widget="DirChooser",
    )
    others = parser.add_argument_group("Other options", gooey_options={"columns": 4})
    others.add_argument(
        "-w",
        "--worker_processes",
        default=1,
        type=int,
        choices=range(1, (os.cpu_count() or 1) + 1),
        help="Number of CPU cores to utilize.",
    )
    others.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force overwrite downloaded lectures.",
    )
    others.add_argument(
        "-k",
        "--keep-no-class",
        action="store_true",
        help="Download lectures which have 'No class' in title.",
    )
    others.add_argument(
        "-R",
        "--rename",
        action="store_true",
        help="Update downloaded lecture names with the current values from impartus",
    )
    return parser.parse_args()


def login(username, password):
    payload = {"username": username, "password": password}
    try:
        response = requests.post(IMP_LOGIN_URL, data=payload, timeout=3)
    except requests.ConnectionError:
        print_quit("Connection Error")
    if response.status_code != 200:
        print_quit("Invalid username/password. Try again.")
    return response.json()["token"]


def parse_lec_ranges(ranges: str, total_lecs: int) -> set:
    if not ranges:
        return set(range(1, total_lecs + 1))
    lecture_ids = set()
    ranges = ranges.split(",") if ranges.find(",") else (ranges,)
    for r in ranges:
        m = RANGE_PAT.match(r)
        if not m:
            print_quit(f'Invalid range "{r}"')
        start = int(m["l"] or 0)
        end = start + 1 if m["r"] is None else int(m["r"] or total_lecs + 1)
        if start >= end:
            print_quit(f'Invalid range "{r}"')
        lecture_ids.update(range(start, min(end, total_lecs + 1)))
    return lecture_ids


def make_filename(lecture):
    lec_no = int(lecture["seqNo"])
    title = lecture["topic"]
    date = lecture["startTime"][:10]
    return sanitize_filepath(f"{lec_no:02}. {title} {date}.mkv")


def rename_old(downloaded, lectures):
    for lec_no, path in downloaded.items():
        for lecture in lectures:
            if lec_no == lecture["seqNo"]:
                new_name = make_filename(lecture)
                if path.name != new_name:
                    print(f"Renaming '{path.name}' to '{new_name}'")
                    path.rename(path.with_name(new_name))
                break


def main():
    try:
        sp.check_call(["ffmpeg", "-version"], **dict(sp_args, stdout=sp.DEVNULL))
    except FileNotFoundError:
        print_quit("ffmpeg not found. Ensure it is present in PATH.")
    config = read_json(CONFIG_FILE, verbose=True)
    data = read_json(DATA_FILE) or {"urls": {}}
    args = parse_args(config, data)
    if not args.username or not args.password:
        print_quit("Email and password not provided.")
    if args.save_creds:
        config["creds"] = {"username": args.username, "password": args.password}
        store_json(config, CONFIG_FILE)
    token = login(args.username, args.password)

    course_lectures_url = "name" in args and data["urls"][args.name] or args.course_url

    headers = {"Authorization": "Bearer " + token}
    response = requests.get(course_lectures_url, headers=headers)
    if not response.ok:
        print_quit("Error fetching course info. Is the url proper?")

    lectures = response.json()
    total_lecs = len(lectures)
    subject_name = "{subjectName} {sessionName}".format(**lectures[0])
    working_dir: Path = args.dest / subject_name
    working_dir.mkdir(exist_ok=True, parents=True)
    print(f'Saving to "{working_dir}"')
    data["urls"].setdefault(subject_name.upper(), course_lectures_url)
    store_json(data, DATA_FILE)

    lecture_ids = parse_lec_ranges(args.range, total_lecs)
    if not args.force or args.only_new:
        downloaded: dict = {
            int(file.stem[:2]): file
            for file in working_dir.glob("[0-9][0-9].*.mkv")
            if int(file.stem[: file.stem.find(".")]) in lecture_ids
        }
        if downloaded:
            if args.rename:
                rename_old(downloaded, lectures)
            if args.only_new:
                lecture_ids.difference_update(range(max(downloaded) + 1))
            else:
                print("Skipping already downloaded lectures:", *sorted(downloaded))
                lecture_ids.difference_update(downloaded)
    if not lecture_ids:
        print_quit("No lectures to download. Exiting.", 0)

    print("Downloading the following lecture numbers:", *sorted(lecture_ids))
    with Pool(args.worker_processes) as pool:
        for lecture in reversed(lectures):  # Download lecture #1 first
            lec_no = lecture["seqNo"]
            if lec_no not in lecture_ids:
                continue
            file_name = make_filename(lecture)
            if not args.keep_no_class and "no class" in file_name.lower():
                print(f"Skipping lecture {lec_no} as it has 'no class' in title.")
                continue
            ttid = lecture["ttid"]
            stream_url = IMP_STREAM_URL.format(ttid, token)
            lec_duration = lecture.get("actualDuration")
            pool.apply_async(
                download_stream, (stream_url, working_dir / file_name, lec_duration)
            )
        pool.close()
        pool.join()
    print("Finished!")


def get_stream_duration(stream_url):
    """Calculate total length of the stream from the m3u8 playlist file"""
    master_resp = requests.get(stream_url).text  # master playlist
    actual_url = urllib.parse.unquote(master_resp.strip().split()[-1])
    stream_pl = requests.get(actual_url).text  # playlist for single stream
    top = stream_pl.find("#EXT-X-KEY")
    end = stream_pl.find("#EXT-X-DISCONTINUITY")
    stream_1 = stream_pl[top:end]
    m = re.findall(r"#EXTINF:(?P<dur>\d+\.\d+)", stream_1)
    return int(sum(map(float, m)))


def download_stream(stream_url: str, output_file: Path, duration=None):
    cmd = [
        "ffmpeg",
        "-y",
        "-xerror",
        "-loglevel",
        "fatal",
        "-i",
        stream_url,
        "-c",
        "copy",
    ]

    try:
        duration = duration or get_stream_duration(stream_url)
    except Exception as e:
        print(f"Error while trying to get duration for {output_file.name}.", e)
    else:
        cmd += ("-t", str(duration))
    cmd.append(str(output_file))
    print("Downloading", output_file.name)
    sp.call(cmd, **sp_args)
    print("Downloaded", output_file.name)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
