#!/usr/bin/env python
import json
import os
import re
import string
import subprocess
import unicodedata
import urllib
import requests
from difflib import get_close_matches
from getpass import getpass
from multiprocessing.pool import Pool
from pathlib import Path
from gooey import Gooey, GooeyParser


SCRIPT_DIR = Path(__file__).parent.absolute()
CONFIG_FILE = "imp_config.json"
DATA_FILE = "imp_data.json"
IMP_BASE_URL = "http://172.16.3.20/"
IMP_LOGIN_URL = IMP_BASE_URL + "api/auth/signin"
IMP_STREAM_URL = IMP_BASE_URL + "api/fetchvideo?ttid={}&token={}&type=index.m3u8"
IMP_LECTURES_URL = IMP_BASE_URL + "api/subjects/{}/lectures/{}"

VALID_CHARS = "-_.() " + string.ascii_letters + string.digits
CATALOG_PAT = re.compile(
    r"(https?://)?(172\.16\.3\.20/ilc/#/course/)(?P<subject>\d+)/(?P<lec>\d+)/?"
)
RANGE_PAT = re.compile(r"\s*(?P<l>\d*)(\s*:\s*(?P<r>\d*))?\s*")  # ignore spaces


def print_quit(msg, status=1):
    print(msg)
    exit(status)


def read_json(file, verbose=False):
    try:
        with open(SCRIPT_DIR / file) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print("Error while reading", file)
        print(e.msg)
    except FileNotFoundError:
        if verbose:
            print(f"Couldn't find {SCRIPT_DIR / file}. Will skip for now.")
    return {}  # use default values


def store_json(data, file):
    with open(SCRIPT_DIR / file, "w") as f:
        json.dump(data, f, indent=4)


@Gooey(program_name="Impartus Scraper", default_size=(1280, 720), header_height=50)
def parse_args(config, data):
    def closest(choice):
        match = get_close_matches(choice.upper(), data["urls"], 1, 0.2)
        return match and match[0] or choice

    creds = config.get("creds", {})
    parser = GooeyParser(
        description="A scraper for Impartus Lecture Capture videos for BITS Hyderabad"
    )
    creds_group = parser.add_argument_group(title="Credentials")
    creds_group.add_argument("-u", "--username", default=creds.get("username"))
    creds_group.add_argument(
        "-p", "--password", default=creds.get("password"), widget="PasswordField"
    )
    if data["urls"]:
        course_group = parser.add_mutually_exclusive_group()
        course_group.add_argument(
            "-n",
            "--name",
            choices=data["urls"],
            type=closest,
            help="Name of previously downloaded course.",
        )
    else:
        course_group = parser
    course_group.add_argument("-c", "--course_url", help="Full impartus URL of course")
    range_group = parser.add_mutually_exclusive_group()
    range_group.add_argument(
        "-r",
        "--range",
        default="",
        help=(
            "Range of lectures to be downloaded. Hint-"
            " 12 (Only 12 will be downloaded),"
            " 1:4 (1 included, 4 excluded),"
            " :10 (Download lecture numbers 1 to 9),"
            " 3: (Download all lectures from number 3 onwards). "
            "You can also specify multiple ranges using commas. "
            "Eg- '12, 4:6, 15:, :2' will download lectures 1, 4, 5, 12, 15, 16, 17, ..."
        ),
    )
    range_group.add_argument(
        "-o",
        "--only-new",
        action="store_true",
        help="Get all lectures after the last downloaded one.",
    )
    parser.add_argument(
        "-d",
        "--dest",
        default=config.get("save_fold", SCRIPT_DIR / "Impartus Lectures"),
        type=Path,
        help=f"Download folder (Default: {SCRIPT_DIR / 'Impartus Lectures'})",
        widget="DirChooser",
    )
    parser.add_argument(
        "-w",
        "--worker_processes",
        default=1,
        type=int,
        choices=range(1, (os.cpu_count() or 1) + 1),
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Force overwrite downloaded lectures.",
    )
    parser.add_argument(
        "-k",
        "--keep-no-class",
        action="store_true",
        default=False,
        help="Download lectures which have 'No class' in title.",
    )
    parser.add_argument(
        "-R",
        "--rename",
        action="store_true",
        default=False,
        help="Update the lecture names with the current values from impartus",
    )
    return parser.parse_args()


def login(username, password):
    payload = {"username": username, "password": password}

    response = requests.post(IMP_LOGIN_URL, data=payload)
    if response.status_code != 200:
        print_quit("Invalid username/password. Try again.")
    return response.json()["token"]


def sanitize_filepath(filename):
    cleaned = unicodedata.normalize("NFKD", filename).encode("ASCII", "ignore")
    return "".join(chr(c) for c in cleaned if chr(c) in VALID_CHARS)


def parse_lec_ranges(ranges: str, total_lecs: int, no_interact: bool = False) -> set:
    if not ranges:
        if not no_interact:
            ranges = input(
                "Enter ranges (Eg: '12, 4:6, 15:, :2') (Leave blank to download all): "
            )
        if not ranges:
            return set(range(1, total_lecs + 1))
    lecture_ids = set()
    ranges = ranges.split(",") if ranges.find(",") else (ranges,)
    for r in ranges:
        m = RANGE_PAT.match(r)
        if not m:
            print_quit(f'Invalid range "{r}"')
            quit(130)
        start = int(m["l"] or 0)
        end = start + 1 if m["r"] is None else int(m["r"] or total_lecs + 1)
        if start >= end:
            print_quit(f'Invalid range "{r}"')
        lecture_ids.update(range(start, min(end, total_lecs + 1)))
    return lecture_ids


def get_lecture_url(urls, name=None, course_url=None):
    if not (name or course_url):
        opt = input("Press 'c' to specify Course URL or 'n' for Course Name: ")
        if opt == "c":
            course_url = input(
                "Enter course url (Eg: http://172.16.3.20/ilc/#/course/12345/789): "
            )
        elif opt == "n":
            name = input("Enter course name (fuzzy search enabled): ")
        else:
            print_quit("Invalid option selected.")
    if name:
        crs = name in urls and [name] or get_close_matches(name.upper(), urls, 1, 0.3)
        if not crs:
            print_quit(
                "Could not find course in local database. "
                "Ensure that it has been downloaded at least once using URL. "
            )
        return urls[crs[0]]
    else:
        m = re.match(CATALOG_PAT, course_url)
        if not m:
            print_quit("URL doesn't match required pattern.")
        return IMP_LECTURES_URL.format(m["subject"], m["lec"])


def make_filename(lecture):
    lec_no = lecture["seqNo"]
    title = lecture["topic"]
    date = lecture["startTime"][:10]
    return sanitize_filepath(f"{lec_no}. {title} {date}.mkv")


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
        subprocess.check_call(["ffmpeg", "-version"], stdout=subprocess.DEVNULL)
    except FileNotFoundError:
        print_quit("ffmpeg not found. Ensure it is present in PATH.")
    config = read_json(CONFIG_FILE, verbose=True)
    data = read_json(DATA_FILE) or {"urls": {}}
    args = parse_args(config, data)

    if not args.username:
        args.username = input("Enter Impartus Email username: ")
    if not args.password:
        args.password = getpass(
            "Enter Impartus password (keep typing, no '*' will be shown): "
        )
    token = login(args.username, args.password)

    course_lectures_url = get_lecture_url(data["urls"], args.name, args.course_url)

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

    lecture_ids = parse_lec_ranges(args.range, total_lecs, args.name or args.only_new)
    if not args.force or args.only_new:
        downloaded: dict = {
            int(file.stem[: file.stem.find(".")]): file
            for file in working_dir.glob("*.mkv")
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
            pool.apply_async(download_stream, [stream_url, working_dir / file_name])

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


def download_stream(stream_url, output_file):
    cmd = [
        "ffmpeg",
        "-y",
        "-xerror",
        "-loglevel",
        "fatal",
        "-stats",
        "-i",
        stream_url,
        "-c",
        "copy",
    ]

    try:
        duration = get_stream_duration(stream_url)
    except Exception as e:
        print(f"Error while trying to get duration for {output_file.name}.", e)
    else:
        cmd += ("-t", str(duration))
    cmd.append(str(output_file))
    subprocess.call(cmd)


if __name__ == "__main__":
    main()
