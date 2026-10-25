# OLIVIA

OLIVIA 是一个在你自己电脑上运行的中文陪伴程序，在终端里用文字聊天。现在是内部测试版，还在打磨，会出错，也欢迎你告诉我们哪里不对。

## 它是什么，不是什么

- 它是一个可以说说话的地方：听你说，回应你，在合适的时候给一些小方法，以及当地的求助电话。
- 它不是心理咨询，不做诊断，也不提供治疗，不能代替医生、心理咨询师或你身边的人。
- 它只为 18 岁及以上的成年人设计，第一次使用时会请你确认年龄。
- 它运行时不联网。聊天内容不会上传，也不会写进任何文件。

## 如果你现在有危险

请马上联系当地的紧急服务，或者你信任的人，不要等这个程序。

- 中国大陆：110（报警）、120（急救）；心理援助热线 12356（各地接听时段不同，部分省份夜间不接听）
- 香港：999；18111 精神健康支援热线（24 小时）
- 其他地区：设置好地区后运行 `olivia resources` 查看当地电话，或访问 <https://findahelpline.com/>

## 安装

需要先装好 Python 3.11 或更新版本、git 和 [pipx](https://pipx.pypa.io/)。

安装 pipx（装完后重新打开终端）：

- macOS：`brew install pipx`，然后 `pipx ensurepath`
- Windows：`py -m pip install --user pipx`，然后 `py -m pipx ensurepath`
- Linux：用系统的包管理器安装（例如 `sudo apt install pipx`），然后 `pipx ensurepath`

然后安装 OLIVIA：

```bash
pipx install git+https://github.com/Olivia295/OLIVIA.git
olivia --version
```

如果电脑上默认的 Python 版本低于 3.11，可以指定版本：`pipx install --python python3.11 git+https://github.com/Olivia295/OLIVIA.git`。

## 更新与卸载

```bash
pipx reinstall olivia    # 从 GitHub 重新安装最新版本
pipx uninstall olivia    # 卸载程序
```

卸载不会删除你的本地设置，需要的话按下面「数据存在哪里」手动删除。

## 开始使用

| 命令 | 作用 |
| --- | --- |
| `olivia chat` | 开始聊天。第一次会先完成几步设置：确认你已满 18 岁、怎么称呼你、所在地区等。输入 `/exit` 结束。危机筛查除了规则，还会参考一个装在本机的小模型（不联网）。这个模型更敏感：只会让判断更谨慎，不会放松规则已经做出的判断，所以偶尔也会在普通的话上弹出求助卡片。模型文件缺失或校验不通过时自动只用规则 |
| `olivia region` | 查看保存的国家/地区；`olivia region HK` 修改（也认得 `china`、`中国`、`大陆`、`香港`、`台湾`、`澳门`、`美国`、`uk` 这类叫法），`olivia region --clear` 清除。支持的地区：CN、HK、MO、TW、US、CA、GB、AU；其他地方用 `olivia region ZZ`，时区默认取这台电脑的设置，也可以加 `--timezone Asia/Tokyo` 指定。有多个时区的地区（US、CA、AU）在电脑时区不属于该地区时需要加上时区，例如 `olivia region US --timezone America/New_York`。认不出的地区不会被保存 |
| `olivia persona` | 查看四种陪伴方式（温和包裹、沉静哲思、平视战友、静默树洞）和现在用的是哪一种；`olivia persona 2`、`olivia persona 沉静哲思`，或者用简称 `树洞`、`静默`、`哲思`、`禅`、`战友`、`理性`、`温和` 更换，下次聊天生效 |
| `olivia profile` | 查看或修改双方的称呼（你的称呼、OLIVIA 的称呼）和不想谈的话题。输入序号选一项再修改；新写的话题会替换原来的，输入 `0` 清空，直接回车不改。下次聊天生效 |
| `olivia health` | 查看或修改你愿意告诉 OLIVIA 的健康情况（以往被专业人士评估过的情况，以及心脏或呼吸方面的情况、家里是否安全），用来避开不适合你的练习。列表只显示中文名称。只在这台电脑上加密保存；电脑没有系统钥匙串时不会保存 |
| `olivia safety-plan` | 在平静的时候写一份自己的安全计划：预警信号、能让自己好受一点的方法、能让自己分心的人或地方、可以求助的人和电话、让环境更安全。每一部分都可以跳过，之后可以查看、修改或清空。只在这台电脑上加密保存；电脑没有系统钥匙串时不会保存。聊天中特别难熬的时候，OLIVIA 会把其中的安抚方法、分心去处和求助的人拿出来给你看 |
| `olivia journal` | 看看最近七天的小结：聊了几次、聊天前后的心情分、试过的小练习。只根据本机的聊天小结生成，不含聊天原文。看完会问一句有没有帮助，可以直接回车跳过 |
| `olivia stats` | 看看使用数字：一共聊了几次、最近 7 天和 30 天各几次、深夜（00:00–05:00）聊天的占比、回复里聊到身边可以联系的人的占比、心情自评结束时比开始时平均变化多少。只有次数、比例和分数，不含任何聊天内容；只根据本机加密的聊天小结计算，不另存任何东西。较早版本留下的小结没有深夜与轮数记录，只计入聊天次数和自评 |
| `olivia memory` | 查看 OLIVIA 在这台电脑上记得什么：每次聊天的小结、周记记录和你让它记住的话（按时间编号），以及还存着哪些别的东西（只列名字，不显示健康信息和安全计划的内容）。只显示在屏幕上，不会另存成文件 |
| `olivia forget` | 让 OLIVIA 忘掉：一条记录、全部聊天记录、锦囊与方法偏好、安全计划，或者全部数据（之后从第一次设置重新开始）。也可以直接用 `--entry 2`（序号见 `olivia memory`）、`--ledger`、`--kit`、`--safety-plan`、`--all`。每次删除前都要输入「确认」，加 `--yes` 可以跳过。删除时会销毁加密用的钥匙，留下的文件副本也再也打不开 |
| `olivia privacy` | 隐私说明：OLIVIA 在这台电脑上存了什么、存在哪个目录、哪些始终加密、哪些从不保存，以及怎么查看（`olivia memory`）和删除（`olivia health`、`olivia forget`）。运行时全程不联网 |
| `olivia resources` | 查看所在地区的求助电话（还没设置时显示全球通用的资源） |
| `olivia settings` | 设置开关，目前只有系统提醒（默认关闭）。打开前会说明要在系统里装一个什么样的定时任务，并再问一次；关闭或 `olivia forget --all` 会把它删掉 |
| `olivia chat --inspect` | 每一轮多显示一个内部状态面板，只有编号、等级和数值，不含你说的话，也不含回复原文。测试和反馈问题时有用 |
| `olivia chat --rules` | 危机筛查只用规则，不参考本机模型。以前的 `olivia chat --model` 仍然可以用，效果和直接 `olivia chat` 一样；两个不能同时给 |
| `olivia --help` | 查看全部命令 |

### 退出码

每个命令结束时的退出码遵循同一个约定，方便脚本判断：

| 退出码 | 含义 |
| --- | --- |
| `0` | 完成了要做的事（包括只是显示信息，或在输入结束时安静地退出；聊天中按 Ctrl-C 与输入结束相同） |
| `1` | 什么也没做：还没有完成第一次设置（`olivia chat` 在设置完成前结束也算），这台电脑上是未满 18 岁的记录，或者保存的数据现在读不出来、钥匙串打不开 |
| `2` | 命令写错了：参数不对，或者给的值认不出来（例如未知的地区、时区或陪伴方式） |

不需要先设置就能用的命令：`olivia resources`、`olivia privacy`、`olivia --help`、`olivia --version`，以及用来清理残留数据的 `olivia forget --all`。

## 数据存在哪里

OLIVIA 保存的东西都在下面这个目录里：设置文件 `profile.json`（你的称呼、年龄确认、国家/地区和时区、第一次设置时的选择；健康信息加密保存）和它的几份自动备份；以及只在有系统钥匙串时才保存、并且始终加密的：每次聊天的小结和你让它记住的话（`ledger/`）、锦囊与方法偏好（`state.bin`）、危机后的关心提醒（`care.bin`）、安全计划（`safety_plan.bin`），加密用的钥匙在 `keys/` 和系统钥匙串里。聊天原文和程序内部的分析结果不会写进文件。用 `olivia memory` 可以查看，用 `olivia forget` 可以删除。

默认位置：

- macOS：`~/Library/Application Support/olivia/`
- Linux：`~/.local/share/olivia/`
- Windows：`%LOCALAPPDATA%\olivia\`

设置环境变量 `OLIVIA_HOME` 可以换一个目录。想清除全部本地数据，请运行 `olivia forget --all`：它会连同系统钥匙串里的那把钥匙一起删掉（只删除目录的话，钥匙还会留在钥匙串里）。

安装和更新时需要联网下载程序；运行时不联网：没有账号，没有使用统计，也不会自动检查更新。

## 反馈问题

请在 <https://github.com/Olivia295/OLIVIA/issues> 提交，写上：

- `olivia --version` 的输出和你的操作系统
- 你做了什么，看到了什么，原本希望看到什么
- 如果和某一轮回复有关，可以附上 `olivia chat --inspect` 的面板

这个仓库是公开的，请不要贴真实的聊天内容，也不要写任何能认出你或别人的信息。

## 开发

```bash
pip install -e '.[dev]'
bash scripts/check.sh
```

两个维护用的脚本：

- `python scripts/eval_crisis.py 文件.csv [--mode rules|model|both] [--show-ids]`：把一份标注好的 CSV（`id,text,level[,category]`）逐句交给产品的危机筛查（规则模式与模型模式），打印混淆矩阵、L2+L3 召回、L0 误报率和按类别的漏报与误报。从不打印原句；`--show-ids` 只额外列出出错样本的 id。
- `python scripts/check_hotline_freshness.py`：热线数据里任何条目的核验日期超过 90 天就以非零状态退出；GitHub Actions 每季度自动运行一次（`.github/workflows/hotline-freshness.yml`），负责人和复核步骤见 `docs/resources/hotline-sources.md`。
