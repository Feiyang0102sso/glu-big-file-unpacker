# 地图拼装：TILELAYER / TILESET / PNG

本文记录 Gun Bros 的关卡地图是怎么从 `24_TILELAYER`、`25_TILESET`、`29_PNG` 三份资源拼回一张完整大图的。
证据来自 `IDA_Disassemble_code/gunbros_3.6.0_IOS.c`，样本为 `DATAS/asserts_360_out/pack2_xga`（Cerberus Prime，熔岩星球）。

相关笔记：[sections.md](sections.md)、[refs.md](refs.md)、[big_internal_partition_analysis.md](big_internal_partition_analysis.md)。
实现在 `src/big_tool/maps/`，命令行是 `big-tool map-render`。

> 所有整数都是 **小端序**（数据取自 iOS/Android 构建，`asserts_360` 指版本 3.6.0，不是 Xbox 360）。

---

## 1. 引用链

一张完整地图是**两条独立的链**叠出来的：地面靠图块，装饰物靠精灵。

```text
08_LEVEL (CLevel::Template)
  └─ GameObjectRef ──► 24_TILELAYER[n]  (CMap)
        │
        ├─ 【地面】GameObjectRef ──► 25_TILESET[m] ──► 29_PNG[k]
        │
        └─ 【装饰物】Object 图层 (type 2) ──► 20_PROP[i] (CProp::Template)
                                              └─ CGameSpriteGluRef
                                                   └─ SpriteGlu 归档 ──► 29_PNG 图集页
```

三层引用都以 `PackHash` 开头，pack2 的哈希是 `0x00267582`（`82 75 26 00`）。

---

## 2. 25_TILESET —— 图块表

`TileSet::Init`（`gunbros_3.6.0_IOS.c:130310`）：

```c
u8              imageCount;
CGameAssetRef   images[imageCount];   // 每项 8 字节：u32 packHash + i32 assetId
u8              tileCount;
struct {                              // 每项 9 字节
    u8   imageIndex;                  // 落在哪张图集上
    u16  x, y, w, h;                  // 图集内的矩形
} tiles[tileCount];
```

pack2 的 `pack2_xga_0118_0xcebf.bin` 恰好 180 字节 = `1 + 2*8 + 1 + 18*9`，无残留：

| 图集 | 资源 | 尺寸 | 提供的图块 |
|---|---|---|---|
| image 0 | `29_PNG[0]` = `pack2_xga_0163` | 1024×1024 | tile 0–15（4×4 地形块） |
| image 1 | `29_PNG[1]` = `pack2_xga_0164` | 512×256 | tile 16 = 深坑、tile 17 = 纯岩浆 |

**图块尺寸恒为 256×256**。引擎里的绘制边长直接取 `tiles[0].w`
（`CLayerTile::GetWidth` = `layerWidth * tiles[0].w`），不是每块单独算。

---

## 3. 24_TILELAYER —— 地图本体（CMap）

`CMap::Init`（`gunbros_3.6.0_IOS.c:92498`）：

```c
GameObjectRef   tileSetRef;    // u32 packHash + u8 localIndex(hash 非 0 时才读)
RequirementList requirements;  // 本图需要预加载的对象（Prop / Enemy / Player ...）
u8              layerCount;
struct {
    u8 layerType;              // 见下表
    ...                        // 各自的 Init 负责解析
} layers[layerCount];
```

`tileSetRef` 就是图块集入口：`CMap::Bind` 用它调
`GetGameObject(pack, 0x18 /* Type 24 = TILESET */, packIndex, localIndex)`。

### 3.1 图层类型

| type | 类 | 载荷 |
|---:|---|---|
| 0 | `CLayerTile` | 图块层，见 3.2 |
| 1 | `CLayerCollision` | `u16 vertCount` + `(i32 x, i32 y)[]`，`u16 edgeCount` + `(u8, u16, u16)[]` |
| 2 | `CLayerObject` | 刷怪 / 道具摆放，见 `CLayerObject::InitializeObjects` |
| 3 | `CLayerMovie` | `CGameAssetRef` + `i16 x` + `i16 y` |
| 4 | `CLayerCamera` | 8 个 `i16`（两组相机矩形） |
| 5 | `CLayerPathLink` | 寻路连接 |
| 6 | `CLayerPathMesh` | 寻路网格 |

图层按文件顺序绘制，`CMap::DrawBackground` 从前往后叠，所以**索引小的在下面**。

### 3.2 CLayerTile

`CLayerTile::Init`（`gunbros_3.6.0_IOS.c:126884`）：

```c
u8   unused;          // 反编译里读出来就丢弃, 样本恒为 1
u16  width;           // 单位是图块, 不是像素
u16  height;
struct {
    u8 tileId;        // 255 = 空
    u8 flags;         // bit0 水平翻转, bit1 垂直翻转
} cells[width * height];
```

`CLayerTile::DrawBackground`（`:126932`）里两个关键点：

- `tileId == 255` 直接跳过，什么都不画；
- 行列都取模（`col % width`、`row % height`），**图层比画布小时会自动环绕平铺**。

这解释了 `pack2_xga_0112` 的岩浆层 12×5 铺在 13×5 的地形层下面：画布取各层的最大值，小的那层自己绕回来。

---

## 4. 流动的背景层

岩浆、星空、海面都不是逐帧动画，是**整层做 UV 滚动**：

- 关卡脚本调 `func.level.setTileLayerSpeed(layerIndex, speedX, speedY)`
  （见 `flow scripts/level/lava-long.flow` 等，pack2 里只有 3 个关卡用到）；
- `CLayerTile::SetSpeed`（`:126803`）把 speed 乘以 **−0.05**，单位是 **图块/秒**；
- `CLayerTile::Update`（`:126770`）每帧累加 `speed * dt`，只保留小数部分；
- 绘制时这个小数偏移配合 3.2 的取模环绕，得到无缝滚动。

所以 `setTileLayerSpeed(0, 0.5, 0)` 实际是 **0.025 图块/秒 = 6.4 像素/秒** 的水平漂移，
一个图块要走 40 秒 —— 是很缓的岩浆蠕动，不是明显的水流。

pack2 三处用法：

| 脚本 | 调用 | 实际速度 |
|---|---|---|
| `lava-long.flow` | `(0, 0.5, 0.0)` | 水平 6.4 px/s |
| `lava-long-boss.flow` | `(0, 1.0, 0.0)` | 水平 12.8 px/s |
| `lava-endless-2.flow` | `(0, 0, 1.0)` | 垂直 12.8 px/s |

`layerIndex` **只数图块层**，不数碰撞层、相机层这些
（`gunbros_3.6.0_IOS.c:117851` 的循环里，凡是虚表 +40 返回非 0 的层都直接跳过、不占序号）。

### 4.1 哪些层会滚

脚本资源没解出来，所以"这一层会不会滚"只能从图块排布反推。判据是
**整层只用了一种非空 tile id**：滚动层的本质是一张无缝纹理平铺满整层，
而地面层必然混用多种图块。`find_scrolling_layers` 就是这么判的。

3.6.0 的 22 张图里有 10 张命中，覆盖三种题材：

| 包 | 地图 | 层 | tile | 内容 |
|---|---|---|---|---|
| pack2 | 0108 / 0109 / 0110 | L0 | #6 | 暗岩浆裂纹 |
| pack2 | 0112 / 0113 / 0115 / 0116 | L0 | #17 | 亮岩浆 |
| pack9 | 0090 | L0 | #6 | 星云星辰 |
| pack12 | 0060 | L0 + L1 | #8 / #11 | 海面，两层 |

pack7 的地面层（`#0–3`、`#8`：沙土、金属格栅）和 pack11 的单层地面都混用多种图块，
正确地被排除在外。

**pack12 是双层视差水面**：底层 tile 8 全不透明，上层 tile 11 的 alpha 在 204–243 之间，
两层必须以不同速度漂移才有水感。速度比例存在关卡脚本里，没解出来，
所以 `SCROLL_RATES` 给的是一组**整数倍率**（底层 1×、上层 2×）——
整数才能保证"一格 = 一个循环"仍然无缝。滚动方向同理是个选择（默认竖直），
不是从数据里读出来的。

---

## 5. 装饰物：Object 图层 + SpriteGlu

石堆、管道、机械、传送门这些**不在图块层里**，它们是 Object 图层（type 2）里的 PROP 实例。

### 5.1 CLayerObject

`CLayerObject::InitializeObjects`（`gunbros_3.6.0_IOS.c:126460`）：

```c
u16  totalObjects;
u8   groupCount;
struct {
    u8   objectType;              // 19 = PROP, 15 = PLAYER 出生点, ...
    u16  count;
    u16  allocCount;
    struct {                      // 每项 11 字节 + 可选附加数据
        u32 packHash;
        u8  localIndex;           // 20_PROP 里的第几个模板
        u8  hasExtra;
        i16 x, y;                 // 地图像素坐标
        u8  flags;
        // hasExtra 时按 objectType 再读 0 / 1 / 2 / 3 字节
    } objects[max(count, 1)];
} groups[groupCount];
```

附加数据长度由 `objectType` 决定：type 15 读 `u16`，type 5 读 `u8+i16`，type 14 读 `u8`，
其余（含 PROP）什么都不读。

### 5.2 CProp::Template

`CProp::Template::Init`（`:123346`）开头就是 `CGameSpriteGluRef`：

```c
u32 packHash;
u8  archeType;         // pack2 全是 0
u8  character;         // pack2 全是 0
u8  mainAnimation;     // 主层
u8  foregroundAnim;    // 前景层
u8  backgroundAnim;    // 背景层
```

**一个 prop 有三个精灵层，不是一个。** `CProp::Bind`（`:124863`）建三个 `CSpritePlayer`，
分别由 `CProp::DrawBackground` / `Draw` / `DrawForeground` 各画一遍，255 表示该层不存在：

| 层 | 文件字节 | 模板偏移 | pack2 用到的 prop 数 |
|---|---:|---:|---:|
| 背景 | 8 | +16 | 42 |
| 主 | 6 | +12 | 40 |
| 前景 | 7 | +17 | 1 |

pack2 的 62 个模板**每个至少有一层**。只画主层会漏掉 22 个完全看不见的 prop
（血迹、焦痕、圆坑、木托板这类贴地装饰全在背景层），成图会明显偏空。

### 5.3 SpriteGlu 归档

`CSpriteGlu`（`:57762` 起）按资源**名字**去取，pack2 里对应这些资源：

| 资源名 | pack2 文件 | 内容 |
|---|---|---|
| `SPRITEGLU__BINARY_GLOBAL` | `0195`（820 B） | 槽位表 t2（107 项）、精灵表 t3（122 项，见 5.5）、6 个 archetype |
| `SPRITEGLU__BINARY_ARCHETYPE_000+i` | `0196`–`0201` | 子帧表 + 帧表 + 动画表；archetype 0 各 196 / 196 / 119 项 |
| `BASE_TEXTURE_MAP+i` | `0202`–`0207` | 矩形表 + remap；archetype 0 有 106 个矩形铺在 4 页上，remap 107 项 |
| `BASE_TEXTURE_PAGE_0+i` | `0188`–`0194` | 7 张图集页 |

`TEXTURE_MAP_GLOBAL` 给出每个 archetype 占几页，pack2 是 `4,1,1,1,0,0` —— 正好 7 页。

**BINARY_ARCHETYPE**（`CSpriteGlu::LoadArcheType`，`:57552`）：

```c
// 两张结构完全相同的表, 但语义不同
u16 subFrameCount;   // table1: 子帧, parts 里的 id 指向【精灵】
    struct { u8 partCount; struct { u16 id; i16 x, y; } parts[partCount]; } subFrames[];
u16 frameCount;      // table2: 帧, parts 里的 id 指向【子帧】
    struct { u8 partCount; struct { u16 id; i16 x, y; } parts[partCount]; } frames[];
u16 animCount;
    struct { u8 flag; u8 stepCount; struct { u16 frameId; u16 duration; } steps[]; } anims[];
u8  moduleCount;
    struct { u8 bitmask[(spriteCount + 7) / 8]; u8 value; } modules[];
```

**两张表不能混用**：动画的 `frameId` 索引的是 table2，table2 的 part 再索引 table1，
最终偏移是两级相加。搞错会让所有装饰物张冠李戴。
证据在 `CSpriteIterator::SetLayer`（`:58229`）和 `SetSprite`（`:58033`）：

```c
subFrameId = table2[ anim.steps[k].frameId ].parts[layer].id;
spriteId   = table1[ subFrameId ].parts[i].id;
x = table2[...].parts[layer].x + table1[...].parts[i].x;   // y 同理
```

**BASE_TEXTURE_MAP**（`CSpriteGlu::LoadTexturePack`，`:57348`）：

```c
u8  pageCount; u8 pageFlags[pageCount];
u16 rectCount;
    struct { u8 page; u16 x, y, w, h; } rects[rectCount];
u16 n; u16 remap[n];
```

### 5.4 拼一个装饰物

从 prop 到像素一共**五级间接**，少一级就全错：

```text
PROP.animation
  1. archetype.anims[animation].steps[0].frameId
  2. archetype.frames[frameId].parts        -> (subFrameId, dx1, dy1)      [table2]
  3. archetype.subFrames[subFrameId].parts  -> (spriteId,   dx2, dy2)      [table1]
  4. global.t3[spriteId]                    -> (slot, transform, blend)
     global.t2[slot]                        -> slot'    (pack2 里是恒等映射)
     texmap.remap[slot']                    -> rectIndex
  5. texmap.rects[rectIndex]                -> (page, x, y, w, h)
  => 在 29_PNG[pageBase + page] 上裁这块, 画到 (obj.x + dx1 + dx2, obj.y + dy1 + dy2)
```

第 4 步那两次查表很容易漏。`t3` 里的 u16 **不是矩形号**，它要先过全局 `t2`（`SPRITEGLU__BINARY_GLOBAL`
的第一张表，107 项），再过本 archetype 的 `remap`（`BASE_TEXTURE_MAP` 末尾那 107 个 u16），
才得到矩形号。原文在 `CSpritePlayer::Draw`（`:59206` 附近）：

```c
v45 = t2[ t3[spriteId].slot ];
rect = rects + 10 * remap[v45];
```

### 5.5 翻转标志与混合标志

`t3` 每项是 `(u16 槽位, u8 transform, u8 blend)`，后两个字节都不能丢。

**transform** 是 3 bit（`CSpriteGlu::FlipTransform`，`:56870`）：**bit0 垂直翻转、
bit1 水平翻转、bit2 宽高对调**。要按位判断，不要按值枚举 —— pack2 的 122 个精灵里
`0:105, 2:13, 3:3, 1:1`，只处理 3 会漏掉 14 个。

> 哪个 bit 对应哪个轴是**拿游戏截图比对定下来的，不是从代码读出来的**。
> `CSpritePlayer::Draw` 把这两个 bit 折成一个渲染层的 transform 码，那个枚举看着像
> MIDP 的 `Sprite.TRANS_*` 但并不是（`drawSurface` 在转置路径上还会再映射一次）。
> 按 MIDP 读会把两个轴弄反，表现为栅栏灯镜像到框外边去，看着像"偏移"。
> `drawSurface` 本身只做平移，transform 不改变绘制位置。

**blend** 只有 0 和 0x80 两种。`CSpritePlayer::Draw` 按它的**符号**分支：负值走辉光路径
（`PushColor` + 另一套混合模式）。pack2 有 4 个精灵带 0x80，全是**不透明黑底的辉光图**，
用普通 alpha 合成会画出一个黑方块而不是一盏灯，必须做加法混合。

part 的绘制顺序是数组**倒序**（`SetLayer` 从 `partCount-1` 往下走），所以索引 0 最后画、在最上层。
prop 之间按 `CProp::GetZOrder` 排，即按 y 从小到大。

---

## 6. pack2 的九张地图

层 0 铺满 tile 17（纯岩浆）的，就是会被 `setTileLayerSpeed` 滚动的那一层。

| # | 资源 | 图块数 | 像素 | 图层 | 岩浆层 |
|---:|---|---|---|---:|---|
| 0 | `0108_0x4902` | 9×7 | 2304×1792 | 2 | — |
| 1 | `0109_0x527a` | 7×9 | 1792×2304 | 2 | — |
| 2 | `0110_0x5f53` | 5×5 | 1280×1280 | 2 | — |
| 3 | `0111_0x61d3` | 11×17 | 2816×4352 | 1 | — |
| 4 | `0112_0x6f38` | 13×5 | 3328×1280 | 2 | 层 0 |
| 5 | `0113_0x8543` | 5×8 | 1280×2048 | 2 | 层 0 |
| 6 | `0114_0x8eb5` | 16×12 | 4096×3072 | 1 | — |
| 7 | `0115_0xab95` | 6×8 | 1536×2048 | 2 | 层 0 |
| 8 | `0116_0xbd4a` | 6×8 | 1536×2048 | 2 | 层 0 |

prop 实例数（含无贴图的逻辑 prop）依次为 76 / 65 / 58 / 111 / 86 / 26 / 111 / 87 / 87。

`08_LEVEL[0..8]` 指向的地图依次是 `[0, 1, 2, 3, 4, 5, 7, 8, 7]`，地图 6 没有关卡引用。


---

## 7. 怎么跑

解包时必须带 `--by-section`，Section 名字是定位 TILELAYER / TILESET / PROP / PNG 的唯一依据：

```bash
big-tool unpack DATAS/asserts_360 --by-section
```

```bash
big-tool map-render DATAS/asserts_360_out
```

默认每个包写到自己的 `_rendered_maps/`，`--output` 可以集中到一处。
`--no-props` 只出地形。

3.6.0 的 13 个包里有 5 个含地图，共 22 张；其余 8 个的 `24_TILELAYER` 都是 `_empty`。

### 动态背景

`--ani_bak` 给有滚动层的地图额外出一对循环动画（`<地图>_bak.mp4` + `<地图>_bak.gif`）：

```bash
big-tool map-render DATAS/asserts_360_out --ani_bak
```

一个循环是**一格图块的行程**，所以首尾帧自然接得上。渲染 60 帧：

- **MP4** 全分辨率，x264 `crf 16` / `preset slow` / `yuv420p`，30 fps，即 2 秒一圈。
  帧是一边画一边喂给 ffmpeg 的 —— 大图 60 帧全存内存要好几个 GB。需要 PATH 上有 ffmpeg，
  没有就只出 GIF。
- **GIF** 从同一批帧里每 3 帧取一张，缩到 0.25，20 帧 / 100 ms，和以前一样。

逐帧只有滚动层在变，所以不滚的图块层和裁好的 prop 图元都缓存复用
（`MapRenderCache`）。prop 本身仍要逐帧重画：辉光精灵走的是加法混合，
需要底下已经滚过的像素。

10 张有滚动层的地图，整批约 6 分钟。

### SpriteGlu 归档怎么定位

引擎按资源名去查（`SPRITEGLU__BINARY_GLOBAL` 等），而包内的**资源名称目录还没解**。
好在这块资源是自描述且连续的：global 里写着 archetype 数 N，后面紧跟 N 个 archetype、
N 个 texture map，最后一个 `TEXTURE_MAP_GLOBAL` 又要正好是 `u16 + N` 字节。
`locate_archive` 就靠这个形状去试，包里不会有第二处能凑巧对上。

图集页是紧挨在 global 之前的那 `sum(pageCounts)` 个 PNG 资源；对不上时只告警不中断，
免得一个包的异常挡住整批。
