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
    "名街逛头墓灵仪馆堂"
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
    # Round 7 (2026-11-01): the round-7 frames (Wu 覅 / 毋, Cantonese 瞓 / 嘞 / 返, 熄灭, 菩萨,
    # 保姆, 烘焙 ...) and their everyday exceptions.
    "介佑刷剖勤喘嘞噪坑姆巡席庇抵擦毋汰洞涯液淘混漆烘焙熄王瞓章缺菩覅趴返"
    # Round 8 (2026-11-25): passive ideation, the unnamed way and the plan with a time, and
    # their everyday exceptions (士兵, 英雄, 警察, 罪犯, 人渣, 哲学, 政策, 受益人, 午觉打盹 ...).
    "兵凡判否哲增士富察尿怖憾或摸政映渣犯珍畜瘦益盹碗罪肌至英警逢配金雄"
    "仰佛娩宗展康延悲懂扭拒摘撕核歇烈瘤碑陵霾骨薪"
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


# Unicode's Default_Ignorable_Code_Point (DerivedCoreProperties.txt) outside Cf, whitespace
# and the variation selectors, which the test below already covers. Python's unicodedata
# has no such property, so the list is static. Left out: the unassigned U+E01F0-E0FFF.
_OTHER_DEFAULT_IGNORABLE = (
    (0x034F, 0x034F),  # combining grapheme joiner (Mn)
    (0x115F, 0x1160),  # Hangul choseong / jungseong filler (Lo)
    (0x17B4, 0x17B5),  # Khmer inherent vowels (Mn)
    (0x180B, 0x180D),  # Mongolian free variation selectors (Mn)
    (0x180F, 0x180F),
    (0x2065, 0x2065),  # reserved (Cn)
    (0x3164, 0x3164),  # Hangul filler (Lo), a chat nickname's "blank"
    (0xFFA0, 0xFFA0),  # half-width Hangul filler (Lo)
    (0xFFF0, 0xFFF8),  # reserved (Cn)
    (0xE0000, 0xE0000),  # reserved (Cn)
    (0xE0002, 0xE001F),
    (0xE0080, 0xE00FF),
)


@pytest.mark.parametrize(
    "cp", [cp for first, last in _OTHER_DEFAULT_IGNORABLE for cp in range(first, last + 1)]
)
def test_every_default_ignorable_code_point_is_dropped(cp):
    # Metamorphic testing (2026-11-25): one of these between two characters hid any phrase.
    assert normalize(f"想{chr(cp)}死") == "想死"


def test_braille_blank_is_dropped_like_the_hangul_filler():
    assert normalize("我\u2800想\u3164死\uffa0了") == "我想死了"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("想\u0332死\u0332", "想死"),  # underlined by a "fancy text" maker
        ("不\u0336想\u0336活\u0336了\u0336", "不想活了"),  # struck through: still read
        ("d\u0332i\u0332e\u0332", "die"),
        ("想\u0301\u0308\u0353死\u1ab0\u1dc0\ufe20", "想死"),  # stacked marks of every block
        ("考了5\ufe0f\u20e30\ufe0f\u20e3分", "考了50分"),  # keycap digits
        ("想\u20dd死", "想死"),  # enclosing circle (Me)
    ],
)
def test_leftover_combining_marks_are_dropped(raw, expected):
    assert normalize(raw) == expected


def test_combining_marks_that_compose_are_kept():
    # NFKC composes these before the fold, so the letter keeps its accent.
    assert normalize("cafe\u0301") == "café"
    assert normalize("nin\u0303o") == "niño"


def test_every_combining_diacritical_mark_is_dropped():
    blocks = ((0x0300, 0x036F), (0x1AB0, 0x1AFF), (0x1DC0, 0x1DFF), (0x20D0, 0x20FF))
    blocks += ((0xFE20, 0xFE2F),)
    # U+0345 (the Greek ypogegrammeni, written under a Greek vowel) casefolds to the letter
    # iota before the fold, as it should.
    marks = [
        chr(cp)
        for first, last in blocks
        for cp in range(first, last + 1)
        if unicodedata.category(chr(cp)) in ("Mn", "Me") and cp != 0x0345
    ]
    kept = [f"U+{ord(m):04X}" for m in marks if normalize(f"想{m}死") != "想死"]
    assert not kept


def test_fold_words_reads_blank_fillers_as_word_breaks():
    assert fold_words("no\u3164i\u2800meant\uffa0it") == "no i meant it"
    assert fold_words("no\u034fpe") == "nope"  # the joiner is invisible, not a blank


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
        # 2026-11-25 (metamorphic testing): lexicon phrases whose Traditional form was missed.
        ("帳號都註銷了", "账号都注销了"),
        ("殯儀館", "殡仪馆"),
        ("我打算參加培訓", "我打算参加培训"),
        ("偶爾會想 這周又沒達標 嚴重", "偶尔会想这周又没达标严重"),
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
