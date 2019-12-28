#!/usr/bin/env python
import multiprocessing
import re
import subprocess as sp
from argparse import ArgumentTypeError
from difflib import get_close_matches
from multiprocessing.pool import Pool
from pathlib import Path
from urllib.parse import urlsplit

import requests
from downloader import DirServer, download_stream
from utils import print_quit, read_json, sanitize_filepath, sp_args, store_json

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
IMP_LOGIN_URL = "api/auth/signin"
IMP_STREAM_URL = "api/fetchvideo?ttid={}&token={}&type=index.m3u8"
IMP_LECTURES_URL = "api/subjects/{}/lectures/{}"

CATALOG_PAT = re.compile(
    r"(?P<base>(https?://)?((172\.16\.3\.20)|((a|bitshyd).impartus.com))/)"
    r"ilc/#/course/(?P<subject>\d+)/(?P<lec>\d+)/?"
)
RANGE_PAT = re.compile(r"\s*(?P<l>\d*)(\s*:\s*(?P<r>\d*))?\s*")  # ignore spaces

ANGLE_CHOICES = ("both", "right", "left")


@Gooey(
    program_name="Impartus Scraper",
    default_size=(1280, 720),
    richtext_controls=True,
    disable_progress_bar_animation=True,
)
def parse_args(config, course_api_urls=None):
    def closest_name(choice):
        match = get_close_matches(choice.upper(), course_api_urls, 1, 0.2)
        if not match:
            raise ArgumentTypeError(
                "Could not find course in local database. "
                "Ensure that it has been downloaded at least once using URL."
            )
        return match[0]

    def validate_url(url):
        match = CATALOG_PAT.match(url)
        if not match:
            raise ArgumentTypeError("URL doesn't match required pattern.")
        return match["base"] + IMP_LECTURES_URL.format(match["subject"], match["lec"])

    creds = config.get("creds", {})
    parser = GooeyParser(
        description="A scraper for Impartus Lecture Capture videos for BITS Hyderabad"
    )
    creds_group = parser.add_argument_group(
        "Credentials",
        (
            "Your impartus creds. (Only needed for login, "
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
        "Download options", gooey_options={"columns": 2 if course_api_urls else 1}
    )
    if course_api_urls:
        course_group = main_args.add_mutually_exclusive_group(required=True)
        course_group.add_argument(
            "-n",
            "--name",
            choices=course_api_urls,
            type=closest_name,
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
        required=not course_api_urls,
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
        "-a",
        "--angle",
        default="both",
        choices=ANGLE_CHOICES,
        help="The camera angle(s) to download",
    )
    main_args.add_argument(
        "-q",
        "--quality",
        default="720p",
        choices=["720p", "450p"],
        help="Video quality of the downloaded lectures",
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
        choices=[1, 2],  # no clear benefit of using more than 2 workers
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


def get_course_url(args, course_urls):
    course_lectures_url = course_urls.get(getattr(args, "name", None), args.course_url)
    split = urlsplit(course_lectures_url)
    global IMP_BASE_URL
    # support for different domains
    IMP_BASE_URL = split.scheme + "://" + split.hostname + "/"
    return course_lectures_url


def login(username, password):
    payload = {"username": username, "password": password}
    try:
        response = requests.post(IMP_BASE_URL + IMP_LOGIN_URL, data=payload, timeout=3)
    except (requests.ConnectionError, requests.Timeout) as e:
        print_quit("Connection Error", e)
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


def download(token, lecture_ids, lectures, work_dir, args):
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
            stream_url = IMP_BASE_URL + IMP_STREAM_URL.format(ttid, token)
            pool.apply_async(
                func=download_stream,
                kwds={
                    "token": token,
                    "stream_url": stream_url,
                    "output_file": work_dir / file_name,
                    "quality": args.quality,
                    "angle": ANGLE_CHOICES.index(args.angle),
                },
            )
        pool.close()
        pool.join()
    print("Finished!")


def main():
    try:
        sp.check_call(["ffmpeg", "-version"], **dict(sp_args, stdout=sp.DEVNULL))
    except FileNotFoundError:
        print_quit("ffmpeg not found. Ensure it is present in PATH.")
    config = read_json(CONFIG_FILE, verbose=True)
    data = read_json(DATA_FILE) or {"urls": {}}
    args = parse_args(config, data["urls"])
    if not args.username or not args.password:
        print_quit("Email and password not provided.")
    if args.save_creds:
        config["creds"] = {"username": args.username, "password": args.password}
        store_json(config, CONFIG_FILE)

    course_lectures_url = get_course_url(args, data["urls"])
    token = login(args.username, args.password)

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
            if int(file.stem[:2]) in lecture_ids
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

    dir_server = DirServer()
    dir_server.start()
    try:
        download(token, lecture_ids, lectures, working_dir, args)
    finally:
        dir_server.terminate()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
