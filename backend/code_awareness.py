"""Read-only Git inspection and selective parsing. Never imports or executes repository code."""
import re
import subprocess
from pathlib import Path
from tree_sitter import Language, Parser
import tree_sitter_python
import tree_sitter_typescript


def symbols(source: bytes, language: str):
    if len(source) > 1_000_000:
        raise ValueError("File exceeds selective parsing size limit")
    grammar = {"python": tree_sitter_python.language, "typescript": tree_sitter_typescript.language_typescript,
               "tsx": tree_sitter_typescript.language_tsx}.get(language)
    if not grammar:
        raise ValueError("Unsupported language")
    tree = Parser(Language(grammar())).parse(source)
    found, pending = [], [tree.root_node]
    kinds = {"function_definition", "class_definition", "function_declaration", "class_declaration",
             "method_definition", "interface_declaration", "type_alias_declaration"}
    while pending:
        node = pending.pop()
        if node.type in kinds:
            name = node.child_by_field_name("name")
            if name:
                found.append({"name": source[name.start_byte:name.end_byte].decode("utf-8", errors="replace"),
                              "kind": node.type, "line_start": node.start_point.row + 1,
                              "line_end": node.end_point.row + 1, "ambiguous": node.has_error})
        pending.extend(reversed(node.children))
    return found


def git_changes(checkout: Path, base_sha: str, head_sha: str):
    for sha in (base_sha, head_sha):
        if not re.fullmatch(r"[0-9a-f]{40,64}", sha):
            raise ValueError("Only exact commit SHAs are accepted")
    output = subprocess.run(["git", "-C", str(checkout.resolve()), "-c", "core.hooksPath=/dev/null",
        "diff", "--no-ext-diff", "--no-textconv", "--name-status", "-z", "-M", base_sha, head_sha, "--"],
        capture_output=True, check=True, timeout=30).stdout.decode("utf-8", errors="replace").split("\0")
    result, i = [], 0
    while i < len(output) - 1:
        status = output[i]
        i += 1
        if status.startswith(("R", "C")):
            old_path, new_path = output[i:i + 2]
            i += 2
            similarity = int(status[1:])
            result.append({"status": "renamed" if status[0] == "R" else "copied", "old_path": old_path,
                           "path": new_path, "similarity": similarity, "ambiguous": similarity < 100})
        else:
            result.append({"status": status, "path": output[i], "ambiguous": status in ("D", "A")})
            i += 1
    return result
