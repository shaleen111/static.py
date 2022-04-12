"""A simple static site generator"""

import argparse
import glob
import hashlib
import json
import os
import sys
import string
import yaml

from shutil import copy
from jinja2 import Environment, FileSystemLoader, Template, select_autoescape
from http.server import HTTPServer, BaseHTTPRequestHandler
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from typing import Callable, Dict, List, Optional, Set, Tuple
from watchdog.events import FileSystemEventHandler, DirModifiedEvent, \
    FileModifiedEvent
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
    "data": os.path.join(BASE_DIR, "data"),
}

FileInfo = Dict[str, str]
FolderInfo = Dict[str, FileInfo]
FolderChanges = Tuple[FolderInfo, Set[str]]

md = (
    MarkdownIt()
    .use(front_matter_plugin)
    .use(dollarmath_plugin, double_inline=True)
)

env = Environment(
    loader=FileSystemLoader(searchpath=[FOLDERS["templates"]]),
    autoescape=select_autoescape()
)


def get_args() -> str:
    """
    Parses through and validates command line arguments.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument('command',
                        choices=['create', 'generate', 'run', 'diff'])
    arg = parser.parse_args()
    return arg.command


def create() -> None:
    """
    Create directory structure for the site:
    ./
        -> assets/
        -> data/
        -> templates/
        -> posts/
        -> site/
        -> history.json
        -> meta.json
    """

    print("Creating folders for site.")
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
    meta = {"base": base_templates, "no_output": no_output}
    history = {"assets": {}, "data": {}, "templates": {}, "posts": {}}
    with open('meta.json', 'w') as f:
        json.dump(meta, f, indent=4)
    with open("history.json", 'w') as f:
        json.dump(history, f, indent=4)
    print("Done!")


def recursively_act_on_dir(pattern: str) -> Callable:
    def decorator(action: Callable) -> Callable:
        def inner() -> None:
            files = glob.iglob(pattern, recursive=True)
            returns = dict()
            for file in files:
                ret = action(file)
                if ret:
                    returns[ret[0]] = ret[1]
            return returns
        return inner
    return decorator


def path_toss(path: str) -> str:
    tossed = ""
    c = path[0]
    while c not in ['\\', '/']:
        path = path[1:]
        tossed += c
        c = path[0]
    return (tossed, path[1:])


def build_dep_tree(meta: Dict):
    def get_files(pattern: str):
        files = set(glob.iglob(pattern, recursive=True))
        return files
    prereqs = meta["deps"]
    dependent = dict()
    for (pattern, prereq) in prereqs.items():
        for p in prereq:
            p = p.replace('/', '\\')
            if p in dependent:
                dependent[p].update(get_files(pattern))
            else:
                dependent[p] = get_files(pattern)
    return dependent


def get_changes(history: Dict, meta: Dict, force_recompile: bool = False) \
        -> Dict[str, FolderChanges]:
    def _get_changes(path: str, file_past: FileInfo) -> bool:
        if not os.path.isfile(path):
            return {}

        curr_mod_date = os.path.getmtime(path)
        if not file_past or file_past["mod_date"] < curr_mod_date:
            curr_hash = hashlib.md5(open(path, 'rb').read()).hexdigest()
            if not file_past or file_past["hash"] != curr_hash:
                return {
                    "mod_date": curr_mod_date,
                    "hash": curr_hash
                }

        return {}

    def folder_changes(name: str, ext: Optional[str] = "",
                       get_deps: Optional[Callable] = None) -> FolderChanges:
        @recursively_act_on_dir(f"{name}/**/*{ext}")
        def populate_changes(file: str) -> None:
            file_name = os.path.relpath(file, name)
            new_file = file_name not in past_set
            if not new_file:
                past_set.remove(file_name)
            if file in prereqs:
                print(file, prereq_changed)
                if file in prereq_changed:
                    changes[file_name] = prereq_info[file]
                    print(changes[file_name])
                return
            if file not in recompile or new_file:
                file_past = {} if new_file or file in recompile \
                   else past[file_name]
                file_changes = _get_changes(file, file_past)
                if file_changes:
                    changes[file_name] = file_changes
            else:
                changes[file_name] = history[name][file_name]

        if force_recompile:
            past_set = set()
        else:
            past = history[name]
            past_set = set(past.keys())
        changes = {}

        populate_changes()

        return (changes, past_set)
    all_changes = {}

    dep_tree = build_dep_tree(meta)
    recompile = set()
    prereq_info = dict()
    prereq_changed = set()
    prereqs = dep_tree.keys()
    for (prereq, dependents) in dep_tree.items():
        folder, relpath = path_toss(prereq)
        prereq_history = {} if prereq in recompile \
            else history[folder][relpath]
        prereq_changes = _get_changes(prereq, prereq_history)
        if prereq_changes:
            prereq_changed.add(prereq)
            prereq_info[prereq] = prereq_changes
            recompile.update(dependents)

    all_changes["templates"] = folder_changes("templates", ".html")
    all_changes["posts"] = folder_changes("posts", ".md")
    all_changes["assets"] = folder_changes("assets")
    all_changes["data"] = folder_changes("data", ".json")
    print(all_changes)

    return all_changes


def process_folder_changes(changes: FolderChanges,
                           mod_handler: Callable[[str], None],
                           del_handler: Callable[[str], None],
                           history: Optional[Dict[str, FolderInfo]] = None) \
                           -> None:
    for changed_file in changes[0].items():
        (name, metadata) = changed_file
        if history:
            history[name] = metadata
        mod_handler(name)
    for deleted_file in changes[1]:
        if history:
            history.pop(deleted_file)
        del_handler(deleted_file)


def diff() -> None:
    """
    Displays what has changed since last generation of site.
    """
    def mod_handler(name: str) -> None:
        modifications.append(f"{folder}\\{name}")

    def del_handler(name: str) -> None:
        deletions.append(f"{folder}\\{name}")

    with open(os.path.join(BASE_DIR, 'history.json')) as f:
        history = json.load(f)

    with open(os.path.join(BASE_DIR, 'meta.json')) as f:
        meta = json.load(f)

    changes = get_changes(history, meta)
    modifications = []
    deletions = []

    for (folder, files) in changes.items():
        process_folder_changes(files, mod_handler, del_handler)

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


@recursively_act_on_dir("posts/**/*.md")
def get_all_front_matter(file: os.DirEntry[str], relpath: str) -> Dict[str, Dict]:
    if not file.name.endswith(".md"):
        return
    with open(file.path) as f:
        post = f.read()
    tokens = md.parse(post)
    return (os.path.join(relpath, file.name), get_front_matter(tokens))


def get_front_matter(tokens: List[Token]) -> Dict:
    front_matter = {}
    if tokens[0].type == "front_matter":
        front_matter = yaml.safe_load(tokens[0].content)
    return {**front_matter, **word_count(tokens)}


def word_count(tokens: List[Token]) -> Dict[str, int]:
    def count(text: str) -> int:
        return sum([el.strip(string.punctuation).isalpha() for el in text.split()])

    info: Dict = {}

    words: int = 0
    for token in tokens:
        if token.type == "text":
            words += count(token.content)
        elif token.type == "inline":
            for child in token.children or ():
                if child.type == "text":
                    words += count(child.content)

    info["words"] = words
    info["minutes"] = int(round(info["words"] / 200))
    return info


def generate(incremental: bool=True) -> None:
    """
    Genereate files for the site.
    """

    def make_dirs_for_file(dest_pathname: str) -> str:
        dest = os.path.join(FOLDERS["site"], dest_pathname)
        os.makedirs(os.path.split(dest)[0], exist_ok=True)
        return dest

    def assets_mod_handler(name: str) -> None:
        if name in meta["no_output"]["assets"]:
            return

        print(f"Copying '{name}' from 'assets\\' to 'site\\'")
        src = os.path.join(FOLDERS["assets"], name)
        dest = make_dirs_for_file(name)
        copy(src, dest)

    def posts_mod_handler(name: str) -> None:
        if name in meta["no_output"]["templates"]:
            return

        print(f"Generating post 'posts\\{name}'...")

        src = os.path.join(FOLDERS["posts"], name)
        dest_pathname = os.path.join("posts", os.path.splitext(name)[0] + ".html")

        with open(src) as f:
            post = f.read()
        tokens = md.parse(post)
        front_matter = get_front_matter(tokens)
        rendered_md = md.render(post)
        template = env.get_template(front_matter["template"].replace('\\', '/'))
        output = template.render(post=front_matter, rendered_md = rendered_md)

        dest = make_dirs_for_file(dest_pathname)
        with open(dest, 'w') as f:
            f.write(output)

    def templates_mod_handler(name: str) -> None:
        if name in meta["no_output"]["templates"]:
            return

        print(f"Rendering 'site\\{name}'...")
        template = env.get_template(name.replace("\\", "/"))
        output = template.render()

        dest = make_dirs_for_file(name)
        with open(dest, 'w') as f:
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

    def posts_del_handler(name: str) -> None:
        del_post = os.path.join("posts", name)
        del_post = os.path.splitext(del_post)[0] + ".html"
        del_handler(del_post)

    def data_handler(name: str) -> None:
        print(f"Updating metadata for 'data\\{name}'...")

    with open(os.path.join(BASE_DIR, 'history.json')) as f:
        history = json.load(f)

    with open(os.path.join(BASE_DIR, 'meta.json')) as f:
        meta = json.load(f)

    print("Detecting changed files...")

    no_changes = incremental
    changes = get_changes(history, meta, not incremental)

    if no_changes:
        for folder in ["assets", "data", "templates", "posts"]:
            if len(changes[folder][0]) + len(changes[folder][1]) > 0:
                no_changes = False
                break
    if no_changes:
        print("No changes!")
        return

    send_history = lambda x: history[x] if incremental else None
    process_folder_changes(changes["templates"], templates_mod_handler, del_handler,
                           send_history("templates"))
    process_folder_changes(changes["assets"], assets_mod_handler, del_handler,
                           send_history("assets"))
    process_folder_changes(changes["posts"], posts_mod_handler, posts_del_handler,
                           send_history("posts"))
    process_folder_changes(changes["data"], data_handler, data_handler,
                           send_history("data"))
    with open('history.json', 'w') as f:
        json.dump(history, f, indent=4)

    print("Done!")


def run() -> None:
    """
    Run a simple development server.
    """

    HOST_NAME = "192.168.1.68"
    SERVER_PORT = 8080
    SCRIPT_LOCATION = os.path.dirname(os.path.realpath(__file__))

    with open(os.path.join(BASE_DIR, 'meta.json')) as f:
        meta = json.load(f)

    with open(os.path.join(SCRIPT_LOCATION, "injection.html")) as inj:
        injection = inj.read()

    index_exists = os.path.isfile(os.path.join(FOLDERS["templates"], "index.html"))
    not_found_exists = os.path.isfile(os.path.join(FOLDERS["templates"], "404.html"))

    class DevServer(BaseHTTPRequestHandler):
        def write_template(self, template: Template) -> None:
            self.wfile.write(bytes(template.render() + injection, "utf-8"))

        def send_404(self) -> None:
            self.send_response(404)
            self.end_headers()

            if not_found_exists:
                template = env.get_template("404.html")
                template.globals.update()
                self.write_template(template)

            else:
                self.wfile.write(bytes("<h1>404</h1>", "utf-8"))

        def do_GET(self) -> None:
            requested = self.path[1:]
            requested_no_ext, ext = os.path.splitext(requested)

            if index_exists and requested == "":
                self.send_response(301)
                self.send_header('Location','/index')
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
                    with open(requested) as f:
                        post = f.read()
                    tokens = md.parse(post)
                    front_matter = get_front_matter(tokens)
                    rendered_md = md.render(post)
                    template = env.get_template(meta["base"]["posts"].replace('\\', '/'))
                    template.globals.update(post=front_matter, rendered_md=rendered_md)
                    self.write_template(template)

                elif os.path.isfile(os.path.join(FOLDERS["templates"], requested_no_ext + ".html")):
                    requested = requested_no_ext + ".html"
                    self.send_response(200)
                    self.end_headers()
                    template = env.get_template((requested).replace('\\', '/'))
                    self.write_template(template)

                else:
                    self.send_404()

            else:
                self.send_404()

        def do_POST(self):
            if self.path == "/refresh":
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({ 'refresh': event_handler.modified }).encode(encoding='utf_8'))
                if event_handler.modified:
                    event_handler.modified = ""

    class DevServerEventHandler(FileSystemEventHandler):
        def __init__(self) -> None:
            super().__init__()
            self.modified = ""

        def on_modified(self, event: DirModifiedEvent | FileModifiedEvent) -> None:
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

    print(get_all_front_matter(FOLDERS["posts"]))
    event_handler = DevServerEventHandler()
    observer = Observer()
    observer.schedule(event_handler, BASE_DIR, recursive=True)
    observer.start()

    server = HTTPServer((HOST_NAME, SERVER_PORT), DevServer)
    print("Server started http://%s:%s" % (HOST_NAME, SERVER_PORT))

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
