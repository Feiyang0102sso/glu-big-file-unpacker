# big-tool Domain Terms

## Asset Package

A directory provided by the user. It contains one or more `.big` files and their related resources. The input for `unpack` is the asset package directory, not a single archive file.

## BIG Archive

A `.big` file. It contains a file header, a main directory, and resource data blocks. Each resource is located by its group hash and offset.

## Resource

A data block in the main directory of a BIG archive. After unpacking, it is written to a directory based on its group hash. Its file extension is guessed from its content.

## Extraction Output

The `<input directory name>_out` directory next to the input directory. Each BIG archive has a subdirectory with the same name.

## External Blender Integration

In the future, the tool may call Blender on the user's computer from the command line. Blender will then run the animation import script. This is not part of the current Python core package and does not depend on `bpy`.
