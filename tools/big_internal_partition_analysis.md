# BIG 包内部逻辑划分与引用链分析

本文基于项目内的反编译文件 `IDA_Disassemble_code/gunbros.c`、解包资源表和已有笔记整理。结论分为：

- **代码确认**：可以直接从反编译控制流或数据结构读出。
- **样本确认**：可以从本项目的解包资源或资源目录中复核。
- **推断**：由代码和样本共同推导，但仍缺少原始符号或完整运行时验证。

## 1. 结论先行

BIG 内部不是单纯的“Group Hash 文件夹”，而是至少存在以下三层寻址：

```text
.big 文件
└── BIG TOC
    └── Group Hash                  [物理资源类别]
        └── Pack 的资源目录映射       [名称哈希 -> 资源句柄]
            └── CGameObjectPack       [Type ID -> 对象区起始句柄]
                └── Type 内局部索引    [第 N 个对象]
```

对于游戏对象，运行时的核心定位逻辑可以概括为：

```text
PackHash
  -> CResTOCManager::GetPackIndexFromHash()
  -> 目标 Pack 的 CGameObjectPack
  -> Type ID
  -> Type 的局部索引
  -> type_base_handle[Type ID] + local_index
  -> CSimpleStream::Open()
  -> 对应对象模板的 Init()
```

这里的 `Type ID` 和对象局部索引是两个不同维度，不能把它们合并成一个全局文件编号。

## 2. 每个 Pack 都可以拥有自己的 CGameObjectPack

`CGameApp` 初始化时先按资源包数量分配 `Vector<CGameObjectPack>`，随后逐个 Pack 检查 `___GAME_TOC_KEYSET` 是否存在；存在时才调用 `CGameObjectPack::Initialize()`。

证据：`gunbros.c:80347-80366`。

因此，`CGameObjectPack` 是**按 Pack 建立的运行时对象索引**，不是整个游戏只有一张表。

## 3. Type ID 的完整映射

反编译文件中的 `GameObjectTypeStrings[30]` 给出了 0–27 的有效对象类型名称，28 和 29 是哨兵值：

| Type ID | 引擎名称 | `AllocateGameObject()` 中的实现/对象 |
|---:|---|---|
| 0 | ACHIEVEMENT | 没有在该分配函数中实现 |
| 1 | ACHIEVEMENTLIST | 没有在该分配函数中实现 |
| 2 | ARMOR | `CArmor::Template` |
| 3 | BULLET | `CBullet::Template` |
| 4 | DAILYBONUS | `CDailyBonusTracking::Template` |
| 5 | ENEMY | `CEnemy::Template` 的反编译初始化分支 |
| 6 | GUN | `CGun::Template` |
| 7 | LEVEL | `CLevel::Template` 的反编译初始化分支 |
| 8 | LEVELPROGRESSION | `Progression` |
| 9 | MISSION | `Mission` |
| 10 | MISSIONOBJECTIVE | `MissionObjective` |
| 11 | PARTICLEEFFECT | 粒子效果模板分支 |
| 12 | PICKUP | Pickup 模板分支 |
| 13 | PLANET | `Planet` |
| 14 | PLATFORM | Platform 模板分支 |
| 15 | PLAYER | Player/Brother 模板分支 |
| 16 | PLAYERPROGRESSION | PlayerProgression 模板分支 |
| 17 | POWERUP | Powerup 模板分支 |
| 18 | PRIZE | `CPrize` |
| 19 | PROP | `CProp::Template` |
| 20 | REFINEMENT | Refinement 模板分支 |
| 21 | SOUNDEFFECT | SoundEffect 模板分支 |
| 22 | STORE | `CStoreItem` |
| 23 | TILELAYER | `CMap` |
| 24 | TILESET | TileSet 模板分支 |
| 25 | TUTORIAL | Tutorial 模板分支 |
| 26 | CHALLENGE | `CChallengeManager::Template` |
| 27 | MP_MATCH | `CMPMatch::Template` |

证据：

- 名称表：`gunbros.c:29077-29109`。
- 类型分配：`gunbros.c:129081-129323`。
- 字符串反序列化循环明确遍历 `i < 28`：`gunbros.c:192045-192067`。

因此，已有 `tools/sub_section.md` 中的 Type 映射需要修正。例如：Type 8 是 `LEVELPROGRESSION`，Type 13 是 `PLANET`，Type 23 是 `TILELAYER`；“Progression / Planet / CMap”本身的概念大致对，但编号和引擎名称不能混用。

## 4. OBJECT_SCRIPT__COUNTS_：每类对象数量表

`CGameObjectPack::InitializeCounts()` 打开资源名 `OBJECT_SCRIPT__COUNTS_`：

```c
v31 = CGameObjectPack::GAME_OBJ_COUNTS[0];
CSimpleStream::Open(..., v31, v30);
UInt8 = CInputStream::ReadUInt8(...);
```

随后它按这个首字节分配每个 Type 的对象数组和状态数组，并连续读取 28 个单字节数量：

```c
while ( v22 < 0x1C )
{
  v24 = CInputStream::ReadUInt8(...);
  ...
  ++v22;
}
```

证据：`gunbros.c:129947-130112`。

运行时读取对象时，`CGameObjectPack::GetGameObject()` 会同时检查：

```text
Type ID < Type 数量
局部索引 < 该 Type 的对象数量
```

证据：`gunbros.c:129033-129051`。

这说明 `OBJECT_SCRIPT__COUNTS_` 的作用不是“把所有 bin 重新排序”，而是定义每个逻辑 Type 有多少个可寻址对象。

## 5. ___GAME_TOC_KEYSET：每个 Type 的起始资源句柄

`CGameObjectPack::InitizlizeIndices()` 打开 `___GAME_TOC_KEYSET`，使用 `CKeysetResource::Load()` 读取一组 32 位值，然后写入 `CGameObjectPack` 的 Type 索引表：

```c
CSimpleStream::Open(..., "___GAME_TOC_KEYSET", packIndex);
CKeysetResource::Load(...);
...
*((_DWORD *)this + v1++ + 12) = v3;
```

证据：`gunbros.c:129893-129945`。

具体对象初始化时，参数 `a3` 是 Type ID，参数 `a4` 是该 Type 内的局部索引：

```c
v7 = a1[a3 + 12];
CSimpleStream::Open(..., v7 + a4, packIndex);
```

证据：`gunbros.c:129772-129807`。

所以更准确的公式是：

```text
object_resource_handle = type_base_handle[Type ID] + local_index
```

这才是“内部区块”的实际实现方式：每个 Type 对应一个连续的资源句柄区间，区间起点来自 `___GAME_TOC_KEYSET`，区间长度来自 `OBJECT_SCRIPT__COUNTS_`。

## 6. 资源句柄不是简单的物理文件序号

Pack 内部资源目录首先把名称哈希映射到 32 位资源句柄。`CResPackTOC::Bind()` 读取一组 `[hash, value]` 对，`CResPackTOC::GetResValue()` 按哈希查找 value。

证据：

- 资源目录读取：`gunbros.c:132484-132584`。
- 哈希到资源句柄：`gunbros.c:132376-132390`。
- BIG 读取资源时会根据句柄的低 15 位查找，并检查高位标志：`gunbros.c:356299-356347`、`gunbros.c:356552-356658`。

在本项目的 `pack1_xga_0318_0xe04095.bin` 中，文件头为 `06 02 00 00`，即资源目录包含 518 个 `[hash, value]` 对。该目录中可以找到：

| 名称 | `CStringToKey` 哈希 | 资源句柄 |
|---|---:|---:|
| `___GAME_TOC_KEYSET` | `0xD8A9DAA5` | `0x0500040B` |
| `OBJECT_SCRIPT__COUNTS_` | `0x02719514` | `0x03000235` |

因此，`0x03000235`、`0x0500040B` 这类值是运行时资源句柄。它们不能直接等价为“第 565 个”或“第 1035 个物理 bin”；低位索引、高位标志以及 BIG reader 的内部映射共同决定最终数据块。

## 7. 引用结构的实际边界

### 7.1 CGameAssetRef：8 字节序列化字段

`CGameAssetRef::Init()` 的读取顺序非常明确：

```c
ReadUInt32()  -> PackHash
ReadInt32()   -> 第二个 32 位字段
```

证据：`gunbros.c:191877-191890`。

因此样本：

```text
81 75 26 00 AD 00 00 00
```

可以确认拆成：

```text
PackHash = 0x00267581
第二字段 = 0x000000AD
```

但仅凭 `CGameAssetRef::Init()` 不能证明第二字段就是“目标 Pack 中从 0 开始的全局资源序号”。更稳妥的命名是 `resource_id_or_asset_value`，需要继续追踪每个资源加载器如何使用它。

### 7.2 GameObjectRef：5 字节序列化字段

`IGameObject::GameObjectRef::Init()` 读取：

```c
ReadUInt32()  -> PackHash
PackHash 非零时 ReadUInt8() -> Type 内或对象引用上下文中的局部编号
```

证据：`gunbros.c:191893-191911`。

内存中额外缓存了 PackIndex，所以结构体看起来是 8 字节，但序列化输入在 PackHash 非零时实际读取 5 字节。

### 7.3 GameObjectTypeRef：6 字节序列化字段

读取顺序为：

```c
ReadUInt8()  -> Type ID
ReadUInt32() -> PackHash
ReadUInt8()  -> 局部编号
```

证据：`gunbros.c:192178-192198`。

字符串解析还显示其格式按 `TYPE_PACKHASH_INDEX` 拆分：`gunbros.c:192038-192113`。所以它才是带有明确 Type ID 的对象引用，而不是普通 `CGameAssetRef`。

### 7.4 CGameSpriteGluRef：7 字节序列化字段

`CGameSpriteGluRef::Init()` 读取 4 字节 PackHash 加 3 个单字节字段：

```c
ReadUInt32();
ReadUInt8();
ReadUInt8();
ReadUInt8();
```

证据：`gunbros.c:191858-191874`。

## 8. 游戏内调用示例：枪械

`CStoreItem::Init()` 连续读取 6 个 `CGameAssetRef`：

```c
CGameAssetRef::Init(this + 36, ...);
CGameAssetRef::Init(this + 52, ...);
CGameAssetRef::Init(this + 64, ...);
CGameAssetRef::Init(this + 76, ...);
CGameAssetRef::Init(this + 88, ...);
CGameAssetRef::Init(this + 100, ...);
```

证据：`gunbros.c:159932-159937`。

商店系统取到一个枪械对象引用后，调用路径是：

```text
CStoreAggregator::GetGameObjectRef()
  -> CGunBros::GetGameObject(..., 6, packIndex, localIndex)
  -> CGameObjectPack::GetGameObject(pack, 6, localIndex)
  -> CGun::Template
```

证据：`gunbros.c:151112-151137`、`gunbros.c:78497-78505`、`gunbros.c:129033-129051`。

敌人、子弹、关卡、星球等对象也走同一套 Type + 局部索引机制，只是 Type ID 不同。

## 9. 对现有两份笔记的修正

需要修正或降级表述的地方：

1. `0xf4e02223` 是对象模板主要所在的物理 Group，但 Type 划分不是由文件夹名称直接完成，而是由 `CGameObjectPack` 的 counts/keyset 两张运行时索引表完成。
2. 有效 Type 是 0–27，共 28 个槽位；不是简单的 0–25。
3. Type 8、13、23 等编号在现有 `sub_section.md` 中有错位，应以 `GameObjectTypeStrings` 和 `AllocateGameObject` 为准。
4. `OBJECT_SCRIPT__COUNTS_` 给出每个 Type 的对象数量；`___GAME_TOC_KEYSET` 给出每个 Type 的资源区起始句柄。二者职责不同。
5. `81 75 26 00 AD 00 00 00` 可以确认是 `CGameAssetRef` 的 8 字节输入，但 `AD` 是否为简单的 0-based 全局资源序号，当前证据不足。
6. PackHash 到 PackIndex 的转换由 `CResTOCManager::GetPackIndexFromHash()` 完成，其实现是哈希表查找，不是对 PackHash 做简单数值换算：`gunbros.c:132617-132627`。

## 10. 下一步最有价值的验证

如果继续深入，优先做以下三件事：

1. 从 `OBJECT_SCRIPT__COUNTS_` 的资源句柄实际取出 29 字节，得到 pack1 各 Type 的真实数量数组。
2. 从 `___GAME_TOC_KEYSET` 的资源句柄实际取出 Type 起始句柄数组，并与 `pack1_xga_resources.csv` 的物理偏移逐项对齐。
3. 针对一个已知武器，追踪 `CStoreAggregator::GetGameObjectRef()` 返回的 PackIndex/局部编号，再验证 Type 6 的起始句柄加局部编号是否正好落到该枪械模板。

完成这三步后，就能把目前的“逻辑模型”进一步变成 pack1 具体的 Type 区间表。
