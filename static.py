"""A simple static site generator"""

import argparse
import hashlib
from http.server import HTTPServer
import json
import mistletoe
import os
import sys

from shutil import copy
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import Callable, Dict, Optional, Set, Tuple
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

"""
n commands:
    static create
    static generate
    static diff
    static run
"""

COLORS = {
    "cyan": '\033[96m',
    "green": '\033[92m',
    "red": '\033[91m',
    "endc": '\033[0m',
}

BASE_DIR = os.getcwd()
FOLDERS = {
    "templates": os.path.join(BASE_DIR, "templates"),
    "posts": os.path.join(BASE_DIR, "posts"),
    "assets": os.path.join(BASE_DIR, "assets"),
    "site": os.path.join(BASE_DIR, "site"),
}


def get_args() -> Tuple:
    """
    Returns what the user wants to do.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('command',
            choices=['create', 'generate', 'run', 'diff'])

    arg = parser.parse_args()
    return arg.command


def create() -> None:
    """
    Create folders to house the site.
    """

    print(f"Creating folders for site.")
    for folder in FOLDERS.values():
        try:
            os.mkdir(folder)
        except FileExistsError as err:
            print(err)
            print("Undoing changes...")
            for f in FOLDERS.values():
                if folder == f:
                    break
                os.rmdir(f)
            sys.exit(1)

    base_templates = {
                    "templates": "",
                    "posts": "",
                }
    no_output = {
                "templates": [],
                "posts": [],
                "assets": [],
    }
    meta = {"base": base_templates, "no_output": no_output,
            "templates": {}, "posts": {}, "assets": {}}
    with open('meta.json', 'w') as f:
        json.dump(meta, f, indent=4)
    print("Done!")


def get_changes(meta: Dict, force_recompile: bool = False) -> Dict:
    def file_changed(path: str, file_past: Dict) -> bool | Dict:
        if not os.path.isfile(path):
            return False

        if not file_past:
            return True

        curr_mod_date = os.path.getmtime(path)
        if file_past["mod_date"] < curr_mod_date:
            curr_hash = hashlib.md5(open(path, 'rb').read()).hexdigest()
            if file_past["hash"] != curr_hash:
                return True

        return False

    def folder_changes(name: str, ext: str="", _force_recompile: bool=False) -> Tuple[Dict, Set]:
        def populate_changes(path_: str=FOLDERS[name], dir_chain: str="") -> None:
            for file in os.scandir(path_):
                if file.is_dir():
                    populate_changes(file.path, file.name)

                elif file.name.endswith(ext):
                    name = os.path.join(dir_chain, file.name)

                    new_file = name not in past_set

                    curr_mod_date = file.stat().st_mtime
                    if new_file or past[name]["mod_date"] < curr_mod_date:
                        curr_hash = hashlib.md5(open(file.path, 'rb').read()).hexdigest()
                        if new_file or past[name]["hash"] != curr_hash:
                            changes[name] = {
                                        "mod_date": curr_mod_date,
                                        "hash": curr_hash,
                                    }
                    if not new_file:
                        past_set.remove(name)

        if _force_recompile:
            past_set = set()
        else:
            past = meta[name]
            past_set = set(past.keys())
        changes = {}

        populate_changes()

        return (changes, past_set)

    all_changes = {}

    base_template = meta["base"]["templates"]
    templates_force_recompile = force_recompile or file_changed(os.path.join(FOLDERS["templates"], base_template),
                                meta["templates"][base_template] if base_template in meta["templates"] else {})
    all_changes["templates"] = folder_changes("templates", ".html", templates_force_recompile)

    posts_template = meta["base"]["posts"]
    posts_force_recompile = templates_force_recompile or posts_template in all_changes["templates"][0]
    all_changes["posts"] = folder_changes("posts", ".md", posts_force_recompile)

    all_changes["assets"] = folder_changes("assets")

    return all_changes


def process_folder_changes(past: Dict, changes: Tuple,
        mod_handler: Callable[[str], None], del_handler: Callable[[str], None],
        save_changes: Optional[bool]=None,) -> None:
    for changed_file in changes[0].items():
        (name, metadata) = changed_file
        if save_changes:
            past[name] = metadata
        mod_handler(name)
    for deleted_file in changes[1]:
        if save_changes:
            past.pop(deleted_file)
        del_handler(deleted_file)


def assets_templates(path: str) -> str:
    return path


def assets_posts(path: str) -> str:
    return os.path.join('..', path).replace('\\', '/')

def generate(incremental: bool=True) -> None:
    """
    Genereate files for the site.
    """
    def copy_with_dirs(src: str, name: str) -> None:
        dest = os.path.join(FOLDERS["site"], os.path.split(name)[0])

        os.makedirs(os.path.split(src)[0], exist_ok=True)
        os.makedirs(dest, exist_ok=True)

        copy(src, dest)

    def templates_mod_handler(name: str) -> None:
        if name in meta["no_output"]["templates"]:
            return

        print(f"Rendering 'site\\{name}'...")
        template = env.get_template(name.replace("\\", "/"))
        template.globals.update(assets=assets_templates)
        output = template.render()

        src = os.path.join(FOLDERS["templates"], name)
        copy_with_dirs(src, name)

        with open(os.path.join(FOLDERS["site"], name), 'w') as f:
            f.write(output)

    def del_handler(name: str) -> None:
        file_path = os.path.join(FOLDERS["site"], name)
        if os.path.isfile(file_path):
            print(f"Deleting 'site\\{name}'...")
            os.remove(file_path)

        dir_path = os.path.split(file_path)[0]
        dir = os.path.split(name)[0]
        if os.path.isdir(dir_path):
            if len(os.listdir(dir_path)) == 0:
                print(f"Deleting empty directory 'site\\{dir}'...")
                os.rmdir(dir_path)

    def static_mod_handler(name: str) -> None:
        if name in meta["no_output"]["assets"]:
            return

        print(f"Copying '{name}' from 'assets\\' to 'site\\'")
        src = os.path.join(FOLDERS["assets"], name)
        copy_with_dirs(src, name)


    with open(os.path.join(BASE_DIR, 'meta.json')) as f:
        meta = json.load(f)

    print("Detecting changed files...")

    changes = get_changes(meta, not incremental)
    if incremental and len(changes["assets"][0]) == 0 and len(changes["assets"][1]) == 0 \
        and len(changes["templates"][0]) == 0 and len(changes["templates"][1]) == 0 \
        and len(changes["posts"][0]) == 0 and len(changes["posts"][1]) == 0:
        print("No changes!")
        return

    env = Environment(
            loader=FileSystemLoader(searchpath=["templates"]),
            autoescape=select_autoescape()
        )
    process_folder_changes(meta["templates"], changes["templates"], templates_mod_handler,
                           del_handler, incremental)

    process_folder_changes(meta["assets"], changes["assets"], static_mod_handler,
                           del_handler, incremental)

    with open('meta.json', 'w') as f:
        json.dump(meta, f, indent=4)

    print("Done!")


def diff() -> None:
    """
    Displays what has changed since last generation of site.
    """
    def mod_handler(name: str) -> None:
        modifications.append(f"{folder}\\{name}")

    def del_handler(name: str) -> None:
        deletions.append(f"{folder}\\{name}")

    with open(os.path.join(BASE_DIR, 'meta.json')) as f:
        meta = json.load(f)

    changes = get_changes(meta)
    modifications = []
    deletions = []

    for (folder, files) in changes.items():
        process_folder_changes(meta, files, mod_handler, del_handler)

    print("Changes:", end="")
    if len(modifications) == 0:
        print(f"{COLORS['cyan']} None!{COLORS['endc']}")
    else:
        print(COLORS['green'] + '\n\t' + '\n\t'.join(modifications) + COLORS['endc'])

    print("\nDeletions:", end="")
    if len(deletions) == 0:
        print(f"{COLORS['cyan']} None!{COLORS['endc']}")
    else:
        print(COLORS['red'] + '\n\t' + '\n\t'.join(deletions) + COLORS['endc'])


def run() -> None:
    """
    Run a simple development server.
    """

    from http.server import BaseHTTPRequestHandler

    host_name = "192.168.1.68"
    server_port = 8080
    script_location = os.path.dirname(os.path.realpath(__file__))

    env = Environment(
            loader=FileSystemLoader(searchpath=["templates"]),
            autoescape=select_autoescape()
        )

    with open(os.path.join(BASE_DIR, 'meta.json')) as f:
        meta = json.load(f)

    with open(os.path.join(script_location, "injection.html")) as inj:
        injection = inj.read()

    class DevServer(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requested = self.path[1:]

            requested_no_ext, ext = os.path.splitext(requested)

            if requested == "" and os.path.isfile(os.path.join(FOLDERS["templates"], "index.html")):
                self.send_response(301)
                self.send_header('Location','/index.html')
                self.end_headers()

            elif os.path.isfile(os.path.join(FOLDERS["assets"], requested)):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(open(os.path.join(FOLDERS["assets"], requested),'rb').read())

            elif ext in ['', '.html'] and requested_no_ext != '':
                if os.path.isfile(requested_no_ext + ".md"):
                    requested = requested_no_ext + ".md"
                    self.send_response(200)
                    self.end_headers()
                    with open(requested) as post:
                        rendered_md = mistletoe.markdown(post)
                        template = env.get_template(meta["base"]["posts"].replace('\\', '/'))
                        template.globals.update(assets=assets_posts)
                        self.wfile.write(bytes(template.render(rendered_md=rendered_md) + injection, "utf-8"))

                elif os.path.isfile(os.path.join(FOLDERS["templates"], requested_no_ext + ".html")):
                    requested = requested_no_ext + ".html"
                    self.send_response(200)
                    self.end_headers()
                    template = env.get_template((requested).replace('\\', '/'))
                    template.globals.update(assets=assets_posts)
                    self.wfile.write(bytes(template.render() + injection, "utf-8"))

                else:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(bytes("<h1>404</h1>", "utf-8"))

            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(bytes("<h1>404</h1>", "utf-8"))

        def do_POST(self):
            if self.path == "/refresh":
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({ 'refresh': event_handler.modified }).encode(encoding='utf_8'))
                if event_handler.modified:
                    event_handler.modified = ""

    class DevServerEventHandler(FileSystemEventHandler):
        def __init__(self, tolerance: int) -> None:
            super().__init__()
            self.modified = ""

        def on_modified(self, event):
            if FOLDERS["templates"] in event.src_path:
                start_path = FOLDERS["templates"]
            elif FOLDERS["assets"] in event.src_path:
                start_path = FOLDERS["assets"]
            else:
                start_path = BASE_DIR

            self.modified = os.path.relpath(event.src_path, start_path).replace('\\', '/')
            modified_no_ext, ext = os.path.splitext(self.modified)
            if ext in [".html", ".md"]:
                self.modified = modified_no_ext
            print(self.modified)

    event_handler = DevServerEventHandler()
    observer = Observer()
    observer.schedule(event_handler, BASE_DIR, recursive=True)
    observer.start()

    server = HTTPServer((host_name, server_port), DevServer)
    print("Server started http://%s:%s" % (host_name, server_port))

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        observer.stop()
        print("Server closed!")
    observer.join()



def main() -> None:
    cmd = get_args()

    print()

    if cmd == "create":
       create()

    elif cmd == "generate":
        generate()

    elif cmd == "run":
        run()

    elif cmd == "diff":
        diff()


if __name__ == "__main__":
    main()
