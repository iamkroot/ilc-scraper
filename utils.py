import json
import os
import string
import subprocess
import sys
import unicodedata
from argparse import ArgumentParser
from functools import wraps
from sys import exit


def remove_gooey_kwargs(func):
    """Decorator to remove gooey keyword arguments from functions."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        for kwd in ("gooey_options", "widget"):
            try:
                del kwargs[kwd]
            except KeyError:
                pass  # EAFP
        return func(*args, **kwargs)

    return wrapper


def Gooey(*args, **kwargs):
    def wrapper(func):
        return func  # make no changes to the function

    return wrapper


class GooeyParser(ArgumentParser):
    """Modified parser that ignores gooey arguments in function calls."""

    @remove_gooey_kwargs
    def add_argument_group(self, *args, **kwargs):
        group = super().add_argument_group(*args, **kwargs)
        group.add_argument_group = remove_gooey_kwargs(group.add_argument_group)
        group.add_argument = remove_gooey_kwargs(group.add_argument)
        return group

    @remove_gooey_kwargs
    def add_argument(self, *args, **kwargs):
        return super().add_argument(*args, **kwargs)


orig_print = print


def print(*args, **kwargs):
    """Override print to send unbufferred output."""
    kwargs.setdefault("flush", True)
    orig_print(*args, **kwargs)


def print_quit(msg, status=1):
    print(msg)
    exit(status)


def make_subprocess_args():
    env = os.environ
    try:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    except AttributeError:
        si = None
    sep = ";" if os.name == "nt" else ":"
    env["PATH"] = env["PATH"] + sep + sep.join(sys.path)
    args = {
        "close_fds": True,
        "stdin": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "startupinfo": si,
        "env": env,
    }
    return args


sp_args = make_subprocess_args()


def read_json(file, verbose=False):
    try:
        with open(file) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print("Error while reading", file)
        print(e.msg)
    except FileNotFoundError:
        if verbose:
            print(f"Couldn't find {file}. Will skip for now.")
    return {}  # use default values


def store_json(data, file):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)


VALID_CHARS = "-_.() " + string.ascii_letters + string.digits


def sanitize_filepath(filename):
    cleaned = unicodedata.normalize("NFKD", filename).encode("ASCII", "ignore")
    return "".join(chr(c) for c in cleaned if chr(c) in VALID_CHARS)
