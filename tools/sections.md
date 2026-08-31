# BIG 容器结构与 Section 表

本文记录 `.big` 容器的完整结构，以及包内 33 个 Section 的来源与命名。

**数据来源**：`DATAS/asserts_100`（10 个包）、`asserts_240`（13 个包）、`asserts_360`（13 个包），共 36 个 `.big`。
除特别标注为「推测」的条目外，所有结论均在全部样本上逐项验证通过，验证数量写在各节末尾。

相关笔记：[tocs.md](tocs.md)、[sub_section.md](sub_section.md)、[big_internal_partition_analysis.md](big_internal_partition_analysis.md)、[refs.md](refs.md)。
010 模板：`binary template/big_assets/big_archive.bt`、`big_TOC.bt`、`string_pack.bt`。

---

## 1. 整体布局

```text
0x00  BigFileHeader     固定 0x20 字节
0x20  Table1[]          每项 8 字节，逻辑 ID -> table2 下标
....  Table2[]          每项 8 字节，group hash + 资源偏移
....  TableFooter       固定 8 字节，收尾 table2
....  数据区             全部资源，首尾相接
```

## 2. 文件头

| 偏移 | 大小 | 字段 | 恒定值 |
|---|---|---|---|
| 0x00 | 4 | `magic` | `FGIB` |
| 0x04 | 2 | `version` | 1（GB 系）/ 2（CK 系） |
| 0x06 | 2 | `flags` | `0x0080` |
| 0x08 | 4 | `table1Offset` | `0x20` |
| 0x0C | 4 | `table1EntryCount` | 2 ~ 4 |
| 0x10 | 4 | `table2Offset` | — |
| 0x14 | 4 | `table2EntryCount` | 资源总数 |
| 0x18 | 4 | `dataBlockOffset` | — |
| 0x1C | 4 | `dataBlockSize` | — |

后两个字段完全冗余，可由前四个推出。以下恒等式 **36/36** 成立：

```text
table2Offset    == table1Offset + table1EntryCount * 8
dataBlockOffset == table2Offset + table2EntryCount * 8 + 8
dataBlockSize   == FileSize() - dataBlockOffset
footer          == { uint32 0, uint32 总文件大小 }
```

`flags` 的 `0x80` 与资源块的压缩标志同值，怀疑含义相同（本包可能含压缩资源），但**无代码证据，属推测**。

## 3. Table1：稀疏 ID 区间映射

```c
struct Table1Range {
    uint32 baseResourceId;   // 区间第一个逻辑 ID
    uint16 rangeLength;      // 区间覆盖多少个连续 ID
    uint16 table2StartIndex; // baseResourceId 对应的 table2 下标
};
```

逻辑 ID 在包内不连续，故按**游程压缩**存储：`base .. base+len-1` 一一映射到 `index .. index+len-1`。
一个 753 资源的包只需 3 项。所有区间首尾相接，`rangeLength` 之和恒等于 `table2EntryCount`（36/36）。

### 3.1 ID 空洞的构成

```text
sum(table1 所有空洞宽度) == 254 + 字符串包条目数        36/36
```

拆开是两部分：

- `0x02 .. 0xFF`（254 个）**永远保留不用**；
- 其余空洞**精确等于字符串包内部条目占用的 ID**，起点与宽度都逐项吻合。

字符串包每一条都占一个逻辑 ID，由字符串包自己的索引解析，故 table1 在此留白。

### 3.2 table1 区间数的决定因素

`table1EntryCount = 1 + 资源 ID 被字符串 ID 段切开后的连续段数`。取决于字符串包格式：

| 字符串包格式 | 含义 | ID 段数 | 使用者 |
|---|---|---:|---|
| `00 A0` / `00 E0` | 只存首 ID，之后连续 | 1 | 其余 33 个包 |
| `00 20` | **每条自带 ID**，允许不连续 | 2 | **仅 pack0** |

**这就是 pack0 永远比同版本其他包多一组的原因**（33 个非 pack0 的包无一例外）。
另外 1.0.0 里字符串块排在所有资源之前，不切割任何东西，故其他包只有 2 组；2.4.0 起挪到中间，变成 3 组。

### 3.3 保留 ID

逻辑 ID `1` 恒定指向本包的字符串包，且它恒为 `table2[0]`（36/36）。引擎的固定入口。

## 4. Table2 与 footer

```c
struct Table2Entry {
    uint32 groupHash;       // 资源类别
    uint32 resourceOffset;  // 绝对文件偏移
};
```

**没有 size 字段**：资源长度 = 下一项 offset 减本项 offset，最后一项延伸到文件末尾。
36 个包的 table2 原始顺序本来就按 offset 递增，但这是隐式契约，解析时不可重排。

| groupHash | 名称 | 内容 |
|---|---|---|
| `0x69E4C505` | string_pack | 本地化字符串包 |
| `0x69E5D35C` | keyset | uint32 句柄数组 |
| `0xB7178678` | png | PNG 贴图 |
| `0xF4E02223` | bin | 游戏对象模板 |
| `0xF686AADC` | manifest | UTF-8 文本 |
| `0xFD8A7754` | wav | RIFF/WAVE 音频 |

## 5. 资源块

```text
ubyte magic;            恒 0x04
ubyte reserved;         恒 0x00
ubyte compressionFlag;  0x00 未压缩 / 0x80 zlib
ubyte padding;          恒 0x00

压缩:   uint32 originalSize; uint32 compressedSize; ubyte zlib[compressedSize];
未压缩: 原始数据直接跟在 4 字节头后
```

13275 个资源块验证结果：

- `magic` / `reserved` / `padding` 三个字节从不变化；
- `compressionFlag` 只有 `0x80`（9237 个）和 `0x00`（4038 个）两种取值；
- 压缩块恒满足 `blockSize == 12 + compressedSize`，**无任何对齐填充**；
- 未压缩块的魔数：PNG 3536 个、RIFF 232 个，其余是无魔数的对象/元数据。

**`originalSize == 0` 的 823 个块不是坏数据**：负载是合法 zlib 流 `78 DA 03 00 00 00 00 01`，解出来是 0 字节，即**空资源**。它们全部落在 `0xF4E02223`，是 Section 表里数量为 0 的类型的占位符（见 6.3）。

> `src/big_tool/big_archive/big_extractor.py` 当前把这种块特判成 `ref` 类型并写出 8 字节 zlib 头，是错的，应正常解压得到空文件。

RIFF 即 WAV：232 个 RIFF 资源在数据偏移 `+8` 处全部是 `WAVE`，且全在 `0xFD8A7754`。

## 6. 资源句柄

低 16 位是逻辑 ID，最高字节是**资源类型标签**。把 40120 个句柄（keyset 25464 + 名字目录 14656）经 table1 解析后与落到的 group 交叉比对，**零例外**：

| 最高字节 | 类型 | 命中 |
|---:|---|---|
| `0x02` | png | 353 / 353 |
| `0x03` | bin | 3042 / 3042 |
| `0x05` | keyset | 82 / 82 |
| `0x09` | wav | 76 / 76 |
| `0x21` | 聚合（字符串条目） | 36300 |
| `0x00` | **不是句柄**：空句柄或普通数值 | 180 |

`bit16-23` 只取 `0x00` 或 `0xFF`，且 `0xFF` 与 `0x21` 严格共现。

**`0x01` 从未单独出现。** `0x21 = 0x20`（聚合标志）`| 0x01`，且全部 `0x21` 句柄都指向字符串包，故 `0x01` 很可能是「字符串」类型——字符串永远不作为顶层资源存在，只作为字符串包内的条目，必然带聚合标志。**属推测**。

### 6.1 keyset

格式 `uint16 count + uint32 handles[count]`。group `0x69E5D35C` 里的每一个资源都是一份 keyset，
36 个包共 82 个，**82/82 全部符合该格式**。

`keyset` 是引擎自己的叫法，反编译里有两个类名：`CKeysetResource`（58 次）、`CResourceKeyset`（47 次）。
不宜叫「TOC」——`CResTOCManager`（289 次）和 `CResPackTOC`（75 次）已经占用了这个词，且六个 keyset 里
只有 `___GAME_TOC_KEYSET` 一个跟目录沾边，其余就是纯句柄清单。

用 `cstring_to_key` 反查出的名字：

| 名称 | 出现在 | 项数 | 内容 |
|---|---|---:|---|
| `___GAME_TOC_KEYSET` | 每个包 | 33 + N | Section 基址 + 全部字符串句柄 |
| *未知，hash `0x0042F53B`* | 每个包 | N | 纯字符串句柄，N = 字符串包条目数 |
| `FONT_KEYSET` | 仅 pack0 | 26 | **13 个 bin + 13 个 png**，成对 |
| `KEYSET_SPLASH_IMAGES` | 仅 pack0 | 27 | 27 张 png 闪屏图 |
| `KEYSET_SPLASH_TEXT` | 仅 pack0 | 27 | 27 条字符串（iOS 文案） |
| `KEYSET_SPLASH_TEXT_ANDROID` | 仅 pack0 | 27 | 与上一条**仅差第 12 项** |

#### 为什么每个包恒定是 2 个

第二个是第一个的**尾部副本**，逐项比对 **36/36** 成立：

```text
___GAME_TOC_KEYSET  =  [ 33 个 Section 基址 ]  +  [ 全部字符串句柄 ]
未知 0x0042F53B     =                            [ 全部字符串句柄 ]
                                                        ↑ 两者逐字节相同
```

服务两个不同的消费者：`CGameObjectPack` 只用前 33 个基址，字符串子系统只用后半段。
属冗余存储，不是两种不同的数据。

#### pack0 多出 4 个

字体与闪屏是全局资源，只放核心包。`FONT_KEYSET` 的 13 对结构应为「每套字体 = 1 份度量数据 + 1 张字形图集」，**未验证**。
`KEYSET_SPLASH_TEXT_ANDROID` 与 iOS 版只差一条文案（`0x21FF01B7` vs `0x21FF01B8`），
`DATAS` 是 iOS 资源，安卓文案被一并打入。

`0x0042F53B` 仍未解出：`gunbros.c` 的 3584 个字符串字面量全部 hash 过，又试过 `___STRING_KEYSET`
一类的组合，均未命中，名字可能是运行时拼接的。

### 6.2 Section 表的来源

**`___GAME_TOC_KEYSET` 的非聚合前缀就是 Section 表**，结构在 26 个包（2.4.0 / 3.6.0）上完全一致：

```text
[ 固定 N 个非聚合句柄 ]  +  [ 全部字符串句柄，恒在尾部 ]
        ↑                          ↑
  2.4.0 = 32 个             数量 == 字符串包条目数
  3.6.0 = 33 个
```

前缀的每一项是一个**区间基址**，寻址公式即反编译笔记里的：

```text
资源句柄 = 基址[Type ID] + 局部序号
```

**Section 编号 = Type ID + 1**，故前 28 个的名字直接取自 `gunbros.c` 的 `GameObjectTypeStrings`。

### 6.3 Section 命名表

```text
 1 ACHIEVEMENT        8 LEVEL            15 PLATFORM          22 SOUNDEFFECT
 2 ACHIEVEMENTLIST    9 LEVELPROGRESSION 16 PLAYER            23 STORE
 3 ARMOR             10 MISSION          17 PLAYERPROGRESSION 24 TILELAYER
 4 BULLET            11 MISSIONOBJECTIVE 18 POWERUP           25 TILESET
 5 DAILYBONUS        12 PARTICLEEFFECT   19 PRIZE             26 TUTORIAL
 6 ENEMY             13 PICKUP           20 PROP              27 CHALLENGE
 7 GUN               14 PLANET           21 REFINEMENT        28 MP_MATCH
```

29 与 30 之后的三个不属于对象类型，按内容判定：

| Section | 内容 | 判据 |
|---:|---|---|
| 29 | **PNG** | 标签 `0x02`，落在 png 组 |
| 30 | **WAV** | 标签 `0x09`，落在 wav 组 |
| 31 | **3D 模型** | magic `03` + 长度前缀 ASCII 名；pack1 首两项是 `gruntgun`/`grunt`、`pustank`/`gun1` |
| 32 | **每关一份的对象引用表** | 内容是 `GameObjectRef` 列表（PackHash + 1 字节）；**资源数在 13 个包里逐项等于 Section 8 (LEVEL)** |
| 33 | **`OBJECT_SCRIPT__COUNTS_` 本身** | 名字哈希 `0x02719514` 查出的句柄与 Section 33 基址相同，13/13 |

### 6.4 判断 Section 是否为空

不要靠「只有 1 个资源」来猜。`OBJECT_SCRIPT__COUNTS_`（29 字节：首字节 `1C` = 28 个类型，后跟 28 个 uint8）直接给出每个类型的真实对象数，与基址间距**逐项吻合**。以 `asserts_360/pack1_xga` 为例：

| Section | 类型 | 基址间距 | COUNTS |
|---:|---|---:|---:|
| 4 | BULLET | 17 | 17 |
| 6 | ENEMY | 29 | 29 |
| 12 | PARTICLEEFFECT | 84 | 84 |
| 14 | PLANET | 1 | 1 |
| 20 | PROP | 2 | 2 |
| 22 | SOUNDEFFECT | 30 | 30 |
| 其余 22 个 | — | 1 | **0** |

`COUNTS == 0` 的 22 个类型，数据区各放一个空资源占位，**22/22 验证通过**。
所以间距为 1 未必是空：PLANET 间距 1 但 `COUNTS == 1`，是真实对象。

### 6.5 Section 体系的覆盖范围

**Section 表不延伸到文件末尾。** 13 个包全部验证：Section 33 的基址 ID 恰好等于 table1 第二个区间的最后一个 ID。之后 ID 断档（如跳到 `0x407`），`基址 + 序号` 的算术走不过去，故 Section 33 只含 1 个资源。

| pack | Section 覆盖 | 体系外资源数 |
|---|---|---:|
| pack1 | `table2[1..310]` | **442** |
| pack5 | `table2[1..737]` | **684** |
| pack0 | `table2[1..82]` | **396** |
| pack4 | `table2[1..1144]` | 14 |

`table2[0]`（字符串包）也在 Section 体系之外，由固定 ID `1` 寻址。

---

## 7. 未解决

1. **体系外资源如何寻址。** pack1 有 442 个、pack5 有 684 个资源既不在 Section 表内，也基本不在名字目录里（pack1 名字目录 518 条中仅 12 条指向该区）。其中包括 195 张特效贴图、大部分 wav 和一批 bin。怀疑走 `CGameSpriteGluRef`（PackHash + SpriteId/ActionId/AnimId，不带资源 ID），**未验证**。

   **已知的一条线索**：pack0 那 4 个额外 keyset 指向的资源**全部落在 Section 体系之外**（区间 `0x4A7..0x56C` 与 `0x582..0x647`），无一在 Section 覆盖的 `0x100..0x151` 内。所以 keyset 确实是体系外资源的寻址手段之一。但缺口仍然很大：pack0 靠这 4 个只覆盖 107 个，而它体系外有 396 个；其余各包只有 2 个 keyset，且没有一个指向体系外，解释不了 pack1 那 442 个。
2. **png 句柄不被逐个存储。** 把 pack1 的 223 张 png 句柄全包搜索，仅 22 张命中且多为二进制巧合；换 `CGameAssetRef` 形式仅 6 张。印证了区间寻址，但也说明第二段 png（`0x40F..0x4D1`，195 张）的入口尚未找到。
3. **manifest 完全在寻址体系外。** 恒为 table2 最后一项，内容 `packN_xga-en-leads`，全库无任何句柄指向它。疑为打包工具写入的构建标记，**未验证**。
4. **一个 keyset 名字未知**（`0x0042F53B`，每个包都有的那份纯字符串句柄表）。`0x357AD3BD` 已解出为 `KEYSET_SPLASH_TEXT_ANDROID`。
5. **`flags = 0x80` 的确切含义**。
6. **`bit16-23` 为何只有 `0x00` / `0xFF`**。`big_TOC.bt` 注释里「aggregate-table selector」的说法目前只有一个取值，无证据支撑。
