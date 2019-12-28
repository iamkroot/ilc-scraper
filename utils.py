import json
import os
import string
import subprocess
import sys
import unicodedata
from argparse import ArgumentParser
from functools import wraps
from sys import exit


def remove_gooey_kwargs(func_or_cls):
    """Decorator to remove gooey keyword arguments from functions."""
    functions = ("add_argument_group", "add_mutually_exclusive_group", "add_argument")

    @wraps(func_or_cls)
    def wrapper(*args, **kwargs):
        for kwd in ("gooey_options", "widget"):
            try:
                del kwargs[kwd]
            except KeyError:
                pass  # EAFP

        obj = func_or_cls(*args, **kwargs)
        for name in functions:
            orig_func = getattr(obj, name, None)
            if orig_func:
                setattr(obj, name, remove_gooey_kwargs(orig_func))

        return obj

    return wrapper


def Gooey(*args, **kwargs):
    """Decorator called when Gooey not installed. Simply returns original function."""

    try:
        sys.argv.remove("--ignore-gooey")  # remove flag from CLI as gooey not installed
    except ValueError:
        pass

    return lambda func: func


@remove_gooey_kwargs
class GooeyParser(ArgumentParser):
    """Modified parser that ignores gooey arguments in function calls."""


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


def find_startswith(lines, s, rev=False):
    """Find the first/last string a list which starts with 's'"""
    lines = enumerate(lines)
    if rev:
        lines = reversed(tuple(lines))
    for i, line in lines:
        if line.startswith(s):
            return i
