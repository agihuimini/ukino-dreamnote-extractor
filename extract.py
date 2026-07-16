#!/usr/bin/env python3
"""
ukino-dreamnote-extractor
Extract all notes from Ukino DreamNote's DATA.mdb into Markdown files,
preserving the original folder tree structure.

Usage:
    python3 extract.py DATA.mdb [output_dir]
"""

import csv
import io
import re
import subprocess
import sys
from pathlib import Path

SEPARATOR = "(☆-U-D-N-♬)"


# ─────────────────────────────────────────────
# Database helpers
# ─────────────────────────────────────────────

def export_table(mdb_path: str, table_name: str) -> list[dict]:
    """Export a table from an MDB file and return rows as dicts."""
    r = subprocess.run(
        ["mdb-export", mdb_path, table_name],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return []
    return list(csv.DictReader(io.StringIO(r.stdout)))


def build_lookup(rows: list[dict]) -> dict:
    """Build a MAINKEY → row dict for fast lookup."""
    return {row["MAINKEY"]: row for row in rows}


# ─────────────────────────────────────────────
# RTF → plain text (Korean cp949 aware)
# ─────────────────────────────────────────────

def rtf_to_text(rtf: str) -> str:
    """Convert an RTF string to plain text.

    mdb-export replaces the apostrophe in RTF hex sequences (\'XX) with ♪.
    This function restores that and then decodes cp949-encoded bytes.
    """
    if not rtf:
        return ""

    # Restore the mdb-export artefact: \♪XX → \'XX  (backslash + apostrophe)
    rtf = rtf.replace("\♪", "\\'")

    result: list[str] = []
    buf = bytearray()      # accumulates cp949 bytes before flushing as text
    i = 0
    # skip_depth: depth at which a skip-destination was encountered.
    # Skip is active when depth >= skip_depth (current group and its children).
    # Reset when depth drops below skip_depth (the enclosing group closes).
    skip_depth = -1
    depth = 0

    def flush():
        if buf:
            result.append(buf.decode("cp949", errors="replace"))
            buf.clear()

    while i < len(rtf):
        c = rtf[i]
        skipping = (skip_depth >= 0 and depth >= skip_depth)

        if c == "{":
            flush()
            depth += 1
            i += 1

        elif c == "}":
            flush()
            depth -= 1
            if skip_depth >= 0 and depth < skip_depth:
                skip_depth = -1
            i += 1

        elif c == "\\":
            if i + 1 >= len(rtf):
                break
            nc = rtf[i + 1]

            if nc == "'":
                # RTF hex-encoded byte: \'XX
                hex_str = rtf[i + 2 : i + 4]
                if not skipping and len(hex_str) == 2:
                    try:
                        buf.append(int(hex_str, 16))
                    except ValueError:
                        pass
                i += 4

            elif nc in ("\\", "{", "}"):
                flush()
                if not skipping:
                    result.append(nc)
                i += 2

            elif nc in ("\n", "\r"):
                i += 2

            elif nc == "*":
                # \* marks an ignorable destination group
                skip_depth = depth
                i += 2

            elif nc == "~":
                if not skipping:
                    flush()
                    result.append(" ")  # non-breaking space
                i += 2

            elif nc == "-":
                if not skipping:
                    flush()
                    result.append("­")  # optional hyphen
                i += 2

            else:
                # Control word: \wordN (N is optional numeric param)
                flush()
                j = i + 1
                while j < len(rtf) and rtf[j].isalpha():
                    j += 1
                ctrl = rtf[i + 1 : j]

                # Optional signed numeric parameter
                k = j
                if k < len(rtf) and rtf[k] in ("-", "+"):
                    k += 1
                while k < len(rtf) and rtf[k].isdigit():
                    k += 1
                # Consume the one space that delimits the control word (if present)
                if k < len(rtf) and rtf[k] == " ":
                    k += 1

                # Known ignorable RTF destinations (header groups to skip entirely)
                _SKIP_DESTS = {
                    "fonttbl", "colortbl", "stylesheet", "info",
                    "pict", "objdata", "themedata", "colorschememapping",
                    "datastore", "header", "footer", "footnote",
                }
                if ctrl in _SKIP_DESTS:
                    skip_depth = depth

                if not skipping:
                    if ctrl == "par":
                        result.append("\n")
                    elif ctrl == "line":
                        result.append("\n")
                    elif ctrl == "tab":
                        result.append("\t")
                    elif ctrl == "page":
                        result.append("\n\n---\n\n")
                    elif ctrl == "u":
                        # \uN  – Unicode char; the next N bytes (per \ucN) are the ANSI fallback.
                        # We just emit the Unicode character and skip 1 fallback byte.
                        num_str = rtf[j:k].strip()
                        if num_str.lstrip("-+").isdigit():
                            code = int(num_str)
                            if code < 0:
                                code += 65536
                            result.append(chr(code))
                        # skip 1 ANSI fallback byte
                        if k < len(rtf) and rtf[k] == "\\":
                            if k + 1 < len(rtf) and rtf[k + 1] == "'":
                                k += 4  # skip \'XX

                i = k

        else:
            if c not in ("\r", "\n") and not skipping:
                flush()
                result.append(c)
            i += 1

    flush()

    text = "".join(result)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ─────────────────────────────────────────────
# DreamNote list format helpers
# ─────────────────────────────────────────────

def split_dn_list(s: str) -> list[str]:
    """Split a DreamNote list field by its custom separator."""
    if not s:
        return []
    return [item.strip() for item in s.split(SEPARATOR) if item.strip()]


# ─────────────────────────────────────────────
# Filename sanitisation
# ─────────────────────────────────────────────

def safe_name(s: str) -> str:
    """Return a filesystem-safe version of s."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = s.strip(". ")
    return s[:200] or "unnamed"


# ─────────────────────────────────────────────
# Treeview parser
# ─────────────────────────────────────────────

def parse_treeview(tv: str) -> list[dict]:
    """Parse the DreamNote custom treeview format.

    Returns a list of root-level node dicts:
        {Key, Text, Image, children: [...]}
    """
    stack: list[dict] = []
    roots: list[dict] = []

    for raw_line in tv.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        if line == ">":
            if not stack:
                continue
            done = stack.pop()
            t = done.pop("_type", "")
            if stack:
                parent = stack[-1]
                if t == "BasicInfo":
                    # Merge fields up into the parent node
                    for k, v in done.items():
                        if k not in ("children",):
                            parent[k] = v
                elif t in ("Root", "Child"):
                    parent.setdefault("children", []).append(done)
            else:
                if t in ("Root", "Child"):
                    roots.append(done)
                elif t == "TreeView":
                    # Outermost wrapper — its children are the real roots
                    roots.extend(done.get("children", []))
            continue

        lt = line.find("<")
        if lt == -1:
            continue

        tag = line[:lt]
        rest = line[lt + 1 :]

        if rest.endswith(">") and "<" not in rest[:-1]:
            # Leaf field: Tag<value>
            if stack:
                stack[-1][tag] = rest[:-1]
        else:
            # Container open: Tag<
            stack.append({"_type": tag, "children": []})

    return roots


# ─────────────────────────────────────────────
# Content extractors
# ─────────────────────────────────────────────

def get_memo_md(key: str, memo_lut: dict) -> tuple[str, str]:
    row = memo_lut.get(key)
    if not row:
        return "", ""
    title = row["CAPTION"]
    text = rtf_to_text(row.get("RTF_DATA", ""))
    return title, text


def get_story_pages(key: str, story_lut: dict, srtf_lut: dict) -> tuple[str, list[tuple[str, str]]]:
    """Return (title, [(page_name, page_text), ...]).

    Single-page stories return a one-element list.
    """
    row = story_lut.get(key)
    if not row:
        return "", []
    title = row["CAPTION"]
    page_keys = split_dn_list(row.get("RTF_LIST", ""))
    page_names = split_dn_list(row.get("RTF_NAME_LIST", ""))

    if not page_keys:
        text = rtf_to_text(row.get("MEMO_RTF", ""))
        return title, [(title, text)]

    pages = []
    for idx, pk in enumerate(page_keys):
        pname = page_names[idx] if idx < len(page_names) else f"Page {idx + 1}"
        rtf_row = srtf_lut.get(pk)
        ptext = rtf_to_text(rtf_row["RTF_DATA"]) if rtf_row else ""
        pages.append((pname, ptext))

    return title, pages


def get_dic_md(key: str, dic_lut: dict, drtf_lut: dict) -> tuple[str, str]:
    row = dic_lut.get(key)
    if not row:
        return "", ""
    title = row["CAPTION"]
    entry_keys = split_dn_list(row.get("RTF_LIST", ""))
    entry_names = split_dn_list(row.get("RTF_NAME_LIST", ""))

    parts = []
    for idx, ek in enumerate(entry_keys):
        ename = entry_names[idx] if idx < len(entry_names) else f"Entry {idx + 1}"
        rtf_row = drtf_lut.get(ek)
        etext = rtf_to_text(rtf_row["RTF_DATA"]) if rtf_row else ""
        parts.append(f"## {ename}\n\n{etext}")

    return title, "\n\n".join(parts)


# ─────────────────────────────────────────────
# Tree walker
# ─────────────────────────────────────────────

def write_node(node: dict, parent_dir: Path, data: dict, counters: dict, merge_pages: bool = False):
    """Recursively write a treeview node to disk.

    merge_pages: if True, multi-page stories are written as one combined .md file.
                 If False (default), each page becomes a separate file inside a subfolder.
    """
    key = node.get("Key", "")
    label = node.get("Text", "") or key[:30]
    children = node.get("children", [])

    # Determine content type
    title = ""
    memo_content: str | None = None          # single-file content (memo / dic)
    story_pages: list[tuple[str, str]] = []  # multi-page story pages

    if key in data["memo_keys"]:
        title, memo_content = get_memo_md(key, data["memo_lut"])
    elif key in data["story_keys"]:
        title, story_pages = get_story_pages(key, data["story_lut"], data["srtf_lut"])
    elif key in data["dic_keys"]:
        title, memo_content = get_dic_md(key, data["dic_lut"], data["drtf_lut"])

    display = title or label
    folder_name = safe_name(display)

    if children:
        # ── Structural directory node (folder in the tree) ──
        node_dir = parent_dir / folder_name
        node_dir.mkdir(parents=True, exist_ok=True)

        if memo_content is not None:
            _write_md(node_dir / "_index.md", display, memo_content, counters)
        elif story_pages:
            _write_story(node_dir, display, story_pages, counters, merge_pages)

        for child in children:
            write_node(child, node_dir, data, counters, merge_pages)

    elif story_pages and len(story_pages) > 1 and not merge_pages:
        # ── Split mode: multi-page story → subfolder, one file per page ──
        story_dir = parent_dir / folder_name
        story_dir.mkdir(parents=True, exist_ok=True)
        _write_story(story_dir, display, story_pages, counters, merge_pages=False)

    else:
        # ── Single file: memo, single-page story, dic, or merge mode ──
        parent_dir.mkdir(parents=True, exist_ok=True)
        if story_pages:
            content = "\n\n".join(
                f"## {pname}\n\n{ptext}" for pname, ptext in story_pages
            )
        else:
            content = memo_content or ""
        file_name = safe_name(display) + ".md"
        _write_md(parent_dir / file_name, display, content, counters)


def _write_story(story_dir: Path, title: str, pages: list[tuple[str, str]],
                 counters: dict, merge_pages: bool = False):
    """Write story pages: one file per page (split) or a single combined file (merge)."""
    if merge_pages:
        content = "\n\n".join(f"## {pname}\n\n{ptext}" for pname, ptext in pages)
        _write_md(story_dir / (safe_name(title) + ".md"), title, content, counters)
    else:
        for pname, ptext in pages:
            _write_md(story_dir / (safe_name(pname) + ".md"), pname, ptext, counters)


def _write_md(path: Path, title: str, content: str, counters: dict):
    """Write a single Markdown file, appending a counter to avoid collisions."""
    # Resolve duplicate filenames
    if path.exists():
        stem, suffix = path.stem, path.suffix
        n = counters.get(str(path.parent / stem), 1)
        counters[str(path.parent / stem)] = n + 1
        path = path.parent / f"{stem}_{n}{suffix}"

    md = f"# {title}\n\n{content}\n" if content else f"# {title}\n"
    path.write_text(md, encoding="utf-8")
    print(f"  {path}")


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract Ukino DreamNote DATA.mdb to Markdown files."
    )
    parser.add_argument("mdb", help="Path to DATA.mdb")
    parser.add_argument("output", nargs="?", default="output", help="Output directory (default: output)")
    parser.add_argument(
        "--merge-pages",
        action="store_true",
        help="Combine all pages of a story into one .md file instead of splitting into separate files per page.",
    )
    args = parser.parse_args()

    mdb_path = args.mdb
    output_dir = Path(args.output)
    merge_pages = args.merge_pages

    if not Path(mdb_path).exists():
        print(f"Error: '{mdb_path}' not found", file=sys.stderr)
        sys.exit(1)

    if merge_pages:
        print("Mode: merge pages into single file per story")

    output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading tables …")
    memo_rows  = export_table(mdb_path, "FRM_MEMO")
    story_rows = export_table(mdb_path, "FRM_STORY")
    srtf_rows  = export_table(mdb_path, "FRM_STORY_RTF")
    dic_rows   = export_table(mdb_path, "FRM_DIC")
    drtf_rows  = export_table(mdb_path, "FRM_DIC_RTF")

    data = {
        "memo_keys":  {r["MAINKEY"] for r in memo_rows},
        "story_keys": {r["MAINKEY"] for r in story_rows},
        "dic_keys":   {r["MAINKEY"] for r in dic_rows},
        "memo_lut":   build_lookup(memo_rows),
        "story_lut":  build_lookup(story_rows),
        "srtf_lut":   build_lookup(srtf_rows),
        "dic_lut":    build_lookup(dic_rows),
        "drtf_lut":   build_lookup(drtf_rows),
    }
    print(
        f"  {len(memo_rows)} memos · "
        f"{len(story_rows)} stories ({len(srtf_rows)} pages) · "
        f"{len(dic_rows)} dictionaries"
    )

    project_rows = export_table(mdb_path, "PROJECT")
    counters: dict = {}

    for project in project_rows:
        pname = project["PROJECT_NAME"]
        print(f"\nProject: {pname}")
        nodes = parse_treeview(project["PROJECT_TREEVIEW"])
        print(f"  {len(nodes)} top-level folders")

        project_dir = output_dir / safe_name(pname)
        project_dir.mkdir(parents=True, exist_ok=True)

        for node in nodes:
            write_node(node, project_dir, data, counters, merge_pages)

    print(f"\nDone → {output_dir.resolve()}")


if __name__ == "__main__":
    main()
