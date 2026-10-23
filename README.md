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
| `olivia chat` | 开始聊天。第一次会先完成几步设置：确认你已满 18 岁、怎么称呼你、所在地区等。输入 `/exit` 结束 |
| `olivia region` | 查看保存的国家/地区；`olivia region HK` 修改，`olivia region --clear` 清除。有多个时区的地区需要加上时区，例如 `olivia region US --timezone America/New_York` |
| `olivia persona` | 查看四种陪伴方式（温和包裹、沉静哲思、平视战友、静默树洞）和现在用的是哪一种；`olivia persona 2` 或 `olivia persona 沉静哲思` 更换，下次聊天生效 |
| `olivia health` | 查看或修改你愿意告诉 OLIVIA 的健康情况（以往的诊断，以及心脏或呼吸方面的情况、家里是否安全），用来避开不适合你的练习。只在这台电脑上加密保存；电脑没有系统钥匙串时不会保存 |
| `olivia safety-plan` | 在平静的时候写一份自己的安全计划：预警信号、能让自己好受一点的方法、能让自己分心的人或地方、可以求助的人和电话、让环境更安全。每一部分都可以跳过，之后可以查看、修改或清空。只在这台电脑上加密保存；电脑没有系统钥匙串时不会保存。聊天中特别难熬的时候，OLIVIA 会把其中的安抚方法、分心去处和求助的人拿出来给你看 |
| `olivia resources` | 查看所在地区的求助电话 |
| `olivia chat --inspect` | 每一轮多显示一个内部状态面板，只有编号、等级和数值，不含你说的话，也不含回复原文。测试和反馈问题时有用 |
| `olivia chat --model` | 试验功能。危机筛查默认只看规则；加上它会同时参考一个装在本机的小模型。这个模型只会让判断更谨慎，不会放松规则已经做出的判断 |
| `olivia --help` | 查看全部命令 |

## 数据存在哪里

OLIVIA 只保存一个设置文件 `profile.json`（你的称呼、年龄确认、国家/地区和时区、第一次设置时的选择），以及它的几份自动备份。聊天内容、程序内部的分析结果和危机记录都不会写进文件。

默认位置：

- macOS：`~/Library/Application Support/olivia/`
- Linux：`~/.local/share/olivia/`
- Windows：`%LOCALAPPDATA%\olivia\`

设置环境变量 `OLIVIA_HOME` 可以换一个目录。删除这个目录，就清除了全部本地数据。

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
