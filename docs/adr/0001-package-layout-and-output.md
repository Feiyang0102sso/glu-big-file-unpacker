# ADR 0001: Use a src Package Layout and Put Output Next to the Input

## Status

Accepted

## Background

The old project had several top-level scripts that depended on the current working directory. They were hard to install and reuse. During unpacking, we also need to keep the input directory unchanged and prevent output from different BIG files from overwriting each other.

## Decision

- Put the Python package in `src/big_tool/`.
- Use `big-tool` as the distribution name and command name. Use `big_tool` as the import name.
- Unpack all `.big` files in the input directory.
- The default output directory is `<input directory name>_out`, next to the input directory.
- Put each `.big` file's output in `<output root directory>/<big file name>/`.
- Clearing an existing output directory remains the default behavior, but the user must confirm first. CLI automation can use `--yes`.
- Keep the Blender script out of the core package for now. Do not install `bpy`.

## Consequences

The tool can be used as a library or a CLI. Input resources are not deleted. In the future, we can add an external Blender runner without adding Blender dependencies to the core package.
