import bpy
import json
import os

# --- 配置路径 ---
# 请修改为你的文件所在的实际文件夹路径
FILE_PATH = r"D:\python coding\big_asserts\3D_reproduct"
OBJ_NAME = "output_pustank_gun_base.obj"
JSON_NAME = "output_pustank_gun_anim.json"


def import_glu_animation():
    # 1. 导入基础模型
    full_obj_path = os.path.join(FILE_PATH, OBJ_NAME)
    bpy.ops.wm.obj_import(filepath=full_obj_path)
    obj = bpy.context.selected_objects[0]
    mesh = obj.data

    # 2. 加载动画 JSON
    with open(os.path.join(FILE_PATH, JSON_NAME), 'r') as f:
        data = json.load(f)

    frames = data["frames"]
    fps = 30  # 假设为 30fps，可根据 time_ms 调整

    # 3. 创建形态键 (Shape Keys)
    # 首先创建 Basis 键
    if not mesh.shape_keys:
        obj.shape_key_add(name="Basis")

    # 4. 遍历每一帧，创建形态键并打关键帧
    print(f"开始处理 {len(frames)} 帧动画...")

    for i, frame in enumerate(frames):
        # 这里的 time_ms 转换为 Blender 帧数 (假设 1000ms = 30帧)
        current_blender_frame = int(frame["time"] * fps / 1000)

        # 创建该帧的形态键
        sk_name = f"Frame_{i:03d}"
        sk = obj.shape_key_add(name=sk_name)

        # 更新该形态键的顶点位置
        # 注意：Blender 顶点顺序必须与导出时一致
        for j, pos in enumerate(frame["vertices"]):
            sk.data[j].co = pos

        # 在时间轴上驱动这个形态键
        # 在当前帧，该键的权重为 1.0，前一帧和后一帧为 0.0
        sk.value = 1.0
        sk.keyframe_insert(data_path="value", frame=current_blender_frame)

        sk.value = 0.0
        sk.keyframe_insert(data_path="value", frame=current_blender_frame - 1)
        sk.keyframe_insert(data_path="value", frame=current_blender_frame + 1)

    # 5. 处理 UA 节点 (骨架展示)
    # 创建骨架对象来显示节点轨迹
    arm_data = bpy.data.armatures.new("Skeleton")
    arm_obj = bpy.data.objects.new("Skeleton_Object", arm_data)
    bpy.context.collection.objects.link(arm_obj)

    # 这一步仅作为可视化节点使用
    for node_info in data["metadata"]["nodes"]:
        bpy.context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='EDIT')
        bone = arm_data.edit_bones.new(node_info)
        bone.head = (0, 0, 0)
        bone.tail = (0, 0, 0.1)  # 默认长度
        bpy.ops.object.mode_set(mode='OBJECT')

    print("动画导入完成！按下 Space 键播放。")


import_glu_animation()