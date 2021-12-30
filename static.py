"""A simple static site generator"""

import argparse
import hashlib
import json
import os
import sys
import threading

from shutil import copy
from itertools import zip_longest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from typing import Callable, Dict, Optional, Set, Tuple

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
    meta = {"base": base_templates, "templates": {}, "posts": {}, "assets": {}}
    with open('meta.json', 'w') as f:
        json.dump(meta, f, indent=4)
    print("Done!")


def get_changes(meta: Dict) -> Dict:
    def file_changed(path: str) -> bool:
        if not os.path.isfile(path):
            return False



        return False

    def folder_changes(name: str, ext: str="", force_recompile: bool=False) -> Tuple[Dict, Set]:
        def populate_changes(path_: str=FOLDERS[name], dir_chain: str=""): 
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
        
        if force_recompile:
            past_set = set()
        else:
            past = meta[name]
            past_set = set(past.keys())
        changes = {}

        populate_changes()

        return (changes, past_set)

    all_changes = {}
    
    base_changed = file_changed(os.path.join(BASE_DIR, meta["base"]["templates"]))
    all_changes["templates"] = folder_changes("templates", ".html", base_changed)

    all_changes["posts"] = folder_changes("posts", ".md", base_changed or 
                                file_changed(os.path.join(BASE_DIR, meta["base"]["posts"])))
    
    all_changes["assets"] = folder_changes("assets")

    return all_changes


def process_folder_changes(past: Dict, changes: Tuple, 
        mod_handler: Callable[[str], None], del_handler: Callable[[str], None], 
        save_changes: Optional[bool]=None,) -> None:
    for (changed_file, deleted_file) in zip_longest(changes[0].items(), 
                                            changes[1]):
        if changed_file:
            (name, metadata) = changed_file
            if save_changes:
                past[name] = metadata
            mod_handler(name)

        if deleted_file:
            if save_changes:
                past.pop(deleted_file)
            del_handler(deleted_file)


def generate(incremental: bool=True):
    """
    Genereate files for the site.
    """
    def copy_with_dirs(src: str, name: str):
        dest = os.path.join(FOLDERS["site"], os.path.split(name)[0])

        os.makedirs(os.path.split(src)[0], exist_ok=True)
        os.makedirs(dest, exist_ok=True)

        copy(src, dest)

    def templates_mod_handler(name: str):
        print(f"Rendering 'site\\{name}'...")
        template = env.get_template(name.replace("\\", "/"))
        template.globals.update({"static": static})
        output = template.render()
        
        src = os.path.join(FOLDERS["templates"], name)
        copy_with_dirs(src, name)

        with open(os.path.join(FOLDERS["site"], name), 'w') as f:
            f.write(output)

    def del_handler(name: str):
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

    def static_mod_handler(name: str):
        print(f"Copying '{name}' from 'assets\\' to 'site\\'")
        
        src = os.path.join(FOLDERS["assets"], name)
        copy_with_dirs(src, name)

    def static(path: str) -> str:
        return path


    env = Environment(
            loader=FileSystemLoader(searchpath=["templates"]),
            autoescape=select_autoescape()
        )

    with open(os.path.join(BASE_DIR, 'meta.json')) as f:
        meta = json.load(f)
    
    print("\nDetecting changed files...")

    if incremental:
        changes = get_changes(meta)

        if len(changes["assets"][0]) == 0 and len(changes["assets"][1]) == 0 \
           and len(changes["templates"][0]) == 0 and len(changes["templates"][1]) == 0 \
           and len(changes["posts"][0]) == 0 and len(changes["posts"][1]) == 0:
            print("No changes!")
            return
    else:
        empty = {
                    "templates": {},
                    "assets": {},
                    "posts": {},
                }
        changes = get_changes(empty)

    process_folder_changes(meta["templates"], changes["templates"], templates_mod_handler, 
                           del_handler, incremental)
    process_folder_changes(meta["assets"], changes["assets"], static_mod_handler,
                           del_handler, incremental)

    with open('meta.json', 'w') as f:
        json.dump(meta, f, indent=4)

    print("Done!")

    
def run():
    """
    Run a simple development server.
    """

    from http.server import BaseHTTPRequestHandler, HTTPServer

    def static(path: str) -> str:
        return path

    host_name = "localhost"
    server_port = 8080

    env = Environment(
            loader=FileSystemLoader(searchpath=["templates"]),
            autoescape=select_autoescape()
        )

    class DevServer(BaseHTTPRequestHandler):
        def do_GET(self):
            requested = self.path[1:]
            requested_no_ext = os.path.splitext(requested)[0]

            if os.path.isfile(os.path.join(FOLDERS["assets"], requested)):
                self.send_response(200)
                self.send_header('Cache-Control', 'public, max-age=15552000')
                self.end_headers()
                self.wfile.write(open(os.path.join(FOLDERS["assets"], requested),'rb').read())
            elif os.path.isfile(os.path.join(FOLDERS["posts"], requested_no_ext + ".md")):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(bytes("<h1> Trying to access post </h1>", "utf-8"))
            elif os.path.isfile(os.path.join(FOLDERS["templates"], requested_no_ext + ".html")):
                self.send_response(200)
                self.end_headers()
                template = env.get_template((requested_no_ext + ".html").replace('\\', '/'))
                template.globals.update({'static': static})
                self.wfile.write(bytes(template.render(), "utf-8"))
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(bytes("<h1>404</h1>", "utf-8"))

    server = HTTPServer((host_name, server_port), DevServer)
    print("Server started http://%s:%s" % (host_name, server_port))

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

    server.server_close()
    print("Server stopped.")


def diff():
    """
    Displays what has changed since last generation of site.
    """
    def mod_handler(name: str): 
        modifications.append(f"{folder}\\{name}")

    def del_handler(name: str):
        deletions.append(f"{folder}\\{name}")

    with open(os.path.join(BASE_DIR, 'meta.json')) as f:
        meta = json.load(f)
    
    changes = get_changes(meta)
    modifications = []
    deletions = []
    
    for (folder, files) in changes.items():
        process_folder_changes(meta, files, mod_handler, del_handler)

    print("\nChanges:", end="")
    if len(modifications) == 0:
        print(f"{COLORS['cyan']} None!{COLORS['endc']}")
    else:
        print(COLORS['green'] + '\n\t' + '\n\t'.join(modifications) + COLORS['endc'])

    print("\nDeletions:", end="")
    if len(deletions) == 0:
        print(f"{COLORS['cyan']} None!{COLORS['endc']}")
    else:
        print(COLORS['red'] + '\n\t' + '\n\t'.join(deletions) + COLORS['endc'])

def main():
    cmd = get_args()

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
    print()
