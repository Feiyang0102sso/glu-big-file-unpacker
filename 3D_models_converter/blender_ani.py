import bpy
import json

"""
!! Apply for Blender 5.0 !!
use in blender script area, copy and run it (Alt+P)
Ctrl + T = switch between animation timeline in seconds / frames ()
Home = Extended animation timeline length
Space = play/stop animation 
"""

# === config area ===
json_path = r"D:\python coding\big_asserts\DATAS\model360\pack1\pack1_xga_0273_0x7923b9.json"
target_fps = 60 # adjust frame speed
time_scale = 2.5  # adjust speed : 2.0 means slowing down by half, 0.5 means speeding up by half.


def import_v_anim():
    obj = bpy.context.active_object
    if not obj or obj.type != 'MESH':
        print("Error: Please select the model first! ")
        return

    # Set scene frame rate
    bpy.context.scene.render.fps = target_fps

    with open(json_path, 'r') as f:
        data = json.load(f)
    frames = data.get('frames', [])

    # Initialize the form key
    if not obj.data.shape_keys:
        obj.shape_key_add(name="Basis")

    # Clear old animation data
    if obj.data.shape_keys.animation_data:
        obj.data.shape_keys.animation_data_clear()

    # Core logic: Frame-by-frame import
    for i, frame_data in enumerate(frames):
        time_ms = frame_data['time']
        vertices = frame_data['vertices']

        # Calculate the target frame (apply time scaling).
        target_frame = (time_ms / 1000.0) * target_fps * time_scale

        # Get or create shape keys
        sk_name = f"Anim_Key_{i:03d}"
        sk = obj.data.shape_keys.key_blocks.get(sk_name) or obj.shape_key_add(name=sk_name)

        # Update vertex position
        # If the model orientation is incorrect,
        # modify the coordinates here, for example (v[0], v[2], -v[1]).
        for v_idx, v_coords in enumerate(vertices):
            if v_idx < len(sk.data):
                sk.data[v_idx].co = (v_coords[0], v_coords[1], v_coords[2])

        # --- Keyframe setting logic: Resolving flickering ---

        # 1. At the current time point, the weight is set to 1.0.
        sk.value = 1.0
        kf_current = sk.keyframe_insert(data_path='value', frame=target_frame)

        # 2. At the time point of the previous frame,
        # the weight is set to 0.0 (to prevent animation overlap).
        if i > 0:
            prev_frame = (frames[i - 1]['time'] / 1000.0) * target_fps * time_scale
            sk.value = 0.0
            sk.keyframe_insert(data_path='value', frame=prev_frame)

        # 3. At the next frame's time point, the weight is set to 0.0.
        if i < len(frames) - 1:
            next_frame = (frames[i + 1]['time'] / 1000.0) * target_fps * time_scale
            sk.value = 0.0
            sk.keyframe_insert(data_path='value', frame=next_frame)

    # Automatically set playback range
    bpy.context.scene.frame_start = 0
    bpy.context.scene.frame_end = int((frames[-1]['time'] / 1000.0) * target_fps * time_scale)

    print(f"Import complete! Total {len(frames)} frames")


# 执行
import_v_anim()