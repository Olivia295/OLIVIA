import sys
import unicodedata
from collections import defaultdict

import pytest

from olivia.core.safety._trad2simp import TRAD_TO_SIMP
from olivia.core.safety.lexicon import load_safety_lexicons
from olivia.core.safety.normalize import (
    PERCEPTION_HEAD,
    PERCEPTION_TAIL,
    clip_for_perception,
    fold_words,
    normalize,
)
from olivia.core.taxonomy import load_taxonomy

# Lexicon characters written the same way in Traditional Chinese, so the fold table has no
# entry mapping to them. A lexicon character that is neither here nor a fold-table target
# fails test_every_lexicon_character_is_classified until someone checks its Traditional form.
SAME_IN_TRADITIONAL = frozenset(
    "一三上下不世之乎也事二五些交人什今他代以任但住何作依保信修倒候值做停偷傻像全公再冷凳刀切"
    "到割力十半去又友反受另可司吞吵命和哪哭啥啦喝噩四囤在地型多大天太失套好如子孕存孩安完定室害"
    "封少尬就屋己已希年底很得心忍忙快怎怕思急性怪恨想惹意感成我手打找把抑抖拖拿挺掉接搬撞放故整"
    "方日早明是晚最月有朋望期木束果枯查格次止正死每毒比永江河法洗活浪浴消激灰炭焦然煤照熬爸片物"
    "狂玻璃瓶生用界畏留疼痛百的盆盒直相盼看眠眼睡知磨社神空突窗站笑等算精累罐聊肉胃胎能脖腕臂自"
    "草蒸藏血行被西要解言走起跟跳躁身躺送逃通道那部都酒醒量陪隔障需非食高魂毛病唯泥海砂磕紫茶路陶常老"
    "亡先具冇功咋咩唔啲嘅妥容弄式息操攻效救新易服步段率略省短程粒舒苦防阻靠平悄此默吧旁"
    # Round 5 (2026-10-29): characters of the round-5 compositions.
    "伸似位便充列剃咖售啡喜堤堵宵尺度必拆挑枕根民汽油深渡番眉稼篷糕置茄蛋袋裙趁越踩限鞋"
    # fix F1: characters of the compositions section of risk.yaml.
    "七中主久乘九亮付件休俺假健兄八六冒凌分初刺刻前勿包匙午博卡印取同告咱哥唱坐墓外夜女奶她"
    "妹始姐姥姻婆婚客宴密小居岩崖工差巴幸弟影待律患您情戒戳房所抓抗拍拜掐排攀收散文施旅星春"
    "晨景晾暖更曾替未末本李案楚款歌母毫水求清演火烤爬父班理瓜甩甭由男目研破禁福究立策管翻考"
    "者聚脆船色花莫菜落蓄蜜衣角象跑蹲退重野院露"
    # fix F5a: ASK_INTENT_WORDS_LEFT (时光胶囊, 中秋) and the trailing particles.
    "光囊秋呀哦啊嘛"
    # fix F6a: the veiled-request, farewell and Cantonese 完咗佢 cues and their exceptions.
    "份佢剪加卸原吖咗咯喇嘢圈圾垃店搞改校煮玩痘睇篇耗餐餸麻黑"
    # fix F16a: L2_MEANS_HOARDED and its everyday stock (布洛芬, 降压, 胰岛素, 药箱 ...).
    "丸惠慢折敏洛狗疫箱糖素胰芬降"
    # 2026-10-26: means made ready, a time before an act, jumping from a height, Cantonese
    # weariness and reported speech, with their everyday exceptions.
    "串乜使免入冬冰助化叔口吐吹呢味喺姨山往怨悼抱抽拔拾捆捱控描攰槽歉池泳派淡滑版甲登移竹"
    "答粗索缸翔舅葬蹦辛追逼避醛除雨雪伯其利句叨吉哋姑娘帖座微提昨近阿「『"
    "名街逛头墓灵殡仪馆堂"
    # Round 2 (2026-10-26): heights, farewells, slang, the 别 non-negators and their
    # everyday exceptions.
    "令剁副合品哈埋培墅夏宿寄局恩截扔扛拉持探推播曝沉注流淹特球申白粉肥辣辨逑醉震音"
    # Round 3 (2026-10-27): plan, farewell and passive-ideation frames, slang (噶, 嚟) and
    # their everyday exceptions (蟑螂, 蚊子, 魔兽世界 ...).
    "元典各商噶嚟孝季寒建彩忘扮投按支敬暑架植泡渴湖漫牌甜祝租童美而胞舞苟蚊螂蟑迷集零首魔鼠桌梯椅沙器官捐稿"
    # 2026-10-28: dose questions and their pets and plants (仙人掌, 葡萄, 兔), PRD L1 wording
    # (心力交瘁, 身心俱疲, 努力), and the chores and fights that void 动手 (揍, 循环).
    "仙俱兔努嗑射巧循掌揍洋疲瘁皮菌萄葡指"
    # Round 6 (2026-10-29): the frames by meaning (calamities, a voice, starving, wiping
    # accounts, cuts) and their everyday exceptions (plants, places, chores, sport).
    "京仇伏例偶催共冤削劈北古叫史啤圳城塔孔宇屏州左市帝幕廊徒恐承括挨援摔敢斑普晶栽椎治溺澡炎爽牙"
    "牛狠猝疤痕癌砸碘祈票秀私科竟箭羞耳肚股肪脂腰航苗茉荷莉薄迎透逐速遇雷韭香鬼鼻嘻握攥裹雕勇孢材棵棺第肝螃蟹超跨"
    # 负责人 2026-10-30 决定: the everyday injuries that void S1_BLEEDING_UNSTOPPED.
    "碰"
    # 2026-10-30: the illnesses and preparations that void ASK_INTENT_PILLS_READY.
    "南咳嗽炸煎睛腹膏"
)


def _lexicon_phrases() -> list[str]:
    tax = load_taxonomy()
    lex = load_safety_lexicons(tax)
    phrases = [p for cue in lex.risk.values() for p in cue.patterns]
    phrases += [p for cue in lex.red_flags.values() for p in cue.patterns]
    phrases += list(lex.self_report_negations)
    phrases += [p for pair in lex.pairs for p in (*pair.anchors, *pair.requests, *pair.exceptions)]
    rules = lex.compositions
    phrases += [*rules.negators, *rules.non_negators, *rules.selves, *rules.others]
    phrases += list(rules.recipients)
    for entry in rules.entries:
        phrases += [*entry.heads, *entry.tails, *entry.context, *entry.unless]
        phrases += [*entry.exceptions, *entry.blockers, *(entry.trailing or ())]
    said = lex.reported_speech
    phrases += [*said.speakers, *said.speaker_exceptions, *said.verbs, *said.verb_exceptions]
    phrases += [*said.fillers, *said.vetoes]
    return phrases


def _traditional_views() -> dict[str, list[str]]:
    views: dict[str, list[str]] = defaultdict(list)
    for trad, simp in TRAD_TO_SIMP.items():
        views[simp].append(trad)
    return views


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("想 死", "想死"),
        ("想\u200b死", "想死"),
        ("想\u200c\u200d\u2060\ufeff死", "想死"),
        ("ＰＴＳＤ", "ptsd"),
        ("BPD", "bpd"),
        ("［５％］ 不想活了", "[5%]不想活了"),
        ("\t活着\n好累 ", "活着好累"),
        ("想\u3000死", "想死"),
    ],
)
def test_normalize_variants(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "想\u00ad死",  # soft hyphen (Cf)
        "想\u200e死",  # left-to-right mark (Cf)
        "想\ufe0f死",  # variation selector 16 (Mn, invisible)
        "想\u202e死",  # right-to-left override (Cf)
        "想\u2066死",  # left-to-right isolate (Cf)
        "想\U000e0001死",  # language tag (Cf, astral plane)
        "想\U000e0100死",  # variation selector 17 (Mn, astral plane)
    ],
)
def test_invisible_characters_are_dropped(raw):
    assert normalize(raw) == "想死"


def test_every_whitespace_and_invisible_character_is_dropped():
    # Checked against the running Python's Unicode database, so a newer database that
    # adds a format character fails here until the static ranges in normalize.py catch up.
    invisible = [
        chr(cp)
        for cp in range(sys.maxunicode + 1)
        if chr(cp).isspace()
        or unicodedata.category(chr(cp)) == "Cf"
        or 0xFE00 <= cp <= 0xFE0F
        or 0xE0100 <= cp <= 0xE01EF
    ]
    kept = [f"U+{ord(ch):04X}" for ch in invisible if normalize(f"想{ch}死") != "想死"]
    assert not kept


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("I don\u2019t want to die", "idon'twanttodie"),
        ("who says i\u2018m not suicidal", "whosaysi'mnotsuicidal"),
    ],
)
def test_curly_apostrophes_fold_to_ascii(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("我想自殺", "我想自杀"),
        ("遺書寫好了", "遗书写好了"),
        ("安眠藥已經買好了", "安眠药已经买好了"),
        ("活著好累", "活着好累"),
        ("雙相情感障礙", "双相情感障碍"),
        ("我確診了躁鬱症", "我确诊了躁郁症"),
        ("這個時候為什麼還沒來", "这个时候为什么还没来"),
        ("爲甚麼説不出口", "为甚么说不出口"),  # Hong Kong variants 爲 / 説
    ],
)
def test_traditional_folds_to_simplified(raw, expected):
    assert normalize(raw) == expected


def test_fold_table_is_well_formed():
    for trad, simp in TRAD_TO_SIMP.items():
        assert len(trad) == 1 and len(simp) == 1 and trad != simp, trad
        # Idempotent: a target is never itself folded again.
        assert simp not in TRAD_TO_SIMP, trad
        assert normalize(trad) == simp, trad


def test_every_lexicon_character_is_classified():
    targets = set(TRAD_TO_SIMP.values())
    chars = {ch for phrase in _lexicon_phrases() for ch in phrase if ord(ch) >= 0x3000}
    unclassified = sorted(chars - targets - SAME_IN_TRADITIONAL)
    assert not unclassified, "".join(unclassified)


def test_traditional_view_of_every_lexicon_phrase_normalizes_back():
    views = _traditional_views()
    for phrase in _lexicon_phrases():
        for pick in (0, -1):  # first and last Traditional variant of each character
            trad = "".join(views[ch][pick] if ch in views else ch for ch in phrase)
            assert normalize(trad) == phrase, (phrase, trad)


def test_clip_short_text_unchanged():
    text = "好" * (PERCEPTION_HEAD + PERCEPTION_TAIL)
    assert clip_for_perception(text) == text


def test_clip_keeps_tail():
    text = "a" * 1000 + "药已经买好了"
    clipped = clip_for_perception(text)
    assert len(clipped) == 384
    assert clipped.startswith("a" * 128) and clipped.endswith("药已经买好了")


def test_fold_words_keeps_every_whitespace_as_a_word_break():
    # Tabs, newlines and the ideographic space separate words just as a plain space does.
    assert fold_words("No\tI\nmeant　it") == "no i meant it"
