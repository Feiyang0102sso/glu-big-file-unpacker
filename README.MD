# Big Tool

## How to use the window

1. Drag a folder onto any part of the window, or click **Browse ...** to select
   one. Choose the folder that contains the `.big` archives.
2. Select the tasks to run:
   - **Unpack .big archives** extracts all archives in the selected folder.
   - **by section** sorts the extracted resources into their sections. Leave it
     enabled when you want to convert models or render maps.
   - **Convert models** converts models from an unpacked, section-classified
     folder.
   - **Render maps** renders maps from an unpacked, section-classified folder.
3. Click **Run**. If existing unpacked output is found, confirm the prompt to
   replace it. Progress and errors appear in the log pane.

Model conversion and map rendering need section-classified data. When unpacking
and post-processing in one run, keep both **Unpack .big archives** and **by section**
selected. To process data that has already been unpacked, select its folder as
the input and choose the post-processing task.

Map rendering exports animated backgrounds as video and GIF loops. Video export
requires `ffmpeg` to be installed and available on the system `PATH`; otherwise
only the GIF loop is written.

## Changelog

<!-- Add release notes here. -->
