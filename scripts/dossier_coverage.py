#!/usr/bin/env python3
"""dossier_coverage.py - how far each of the 60 distress dossiers reaches the runtime.

Plan D-2 / PRD §8.2. One row per dossier (taxonomy ``distress_spectra``, file in
``situations/``):

  cues    perception.yaml ``situation_cues`` phrases for the code; for the seven red-flag
          dossiers the red_flags.yaml patterns instead, marked ``rf`` (the red-flag
          detector reads them and the referral path takes over).
  images  metaphors.yaml ``by_situation`` images (the ``{metaphor}`` slot prefers them).
  lenses  grade_bc_info.yaml ``situation_lenses``: the Grade B methods the dossier names
          (the one S_clarify lens prefers them).
  contra  contraindications that reach the solver through A1's path: a taxonomy
          ``detection_source`` naming the code, or, for a red flag, its own masks.
  route   ``m0`` (COLBO-06), ``rf`` (red-flag referral) or ``-``.

Then totals, and every action or wording a dossier says to avoid that has no runtime
hook of its own, with the reason. Exit status 0; 1 when a dossier file is missing.

Usage: python scripts/dossier_coverage.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from olivia.core.language.data import load_language_data  # noqa: E402
from olivia.core.methods.contraindications import source_links  # noqa: E402
from olivia.core.methods.solver import M0_SITUATIONS  # noqa: E402
from olivia.core.perception.lexicon import load_perception_lexicon  # noqa: E402
from olivia.core.taxonomy import load_taxonomy  # noqa: E402

CUE_TARGET = 0.80

# What a dossier says to avoid that is not a contraindication link, and why (section
# numbers are the dossier's own: 五节 = "循证心理调节方向与临床边界").
NOT_WIRED = {
    "SIT-01-02": "五节“发作巅峰期严禁讲复杂道理”：唤醒度规则已覆盖（≥0.80 只给稳定化，"
    "≥0.85 ACUTE_AROUSAL_OVERLOAD），只在高唤醒的那一轮生效，不做会话级禁忌",
    "SIT-09-03": "五节“怒火冲顶时严禁沟通或解决问题”：同上，由唤醒度规则逐轮覆盖",
    "SIT-01-05": "五节“见血/打针晕厥型恐惧不可用放松降血压法”：taxonomy 没有对应的禁忌"
    "枚举，未接入（待 G-0 决定是否新增）",
    "SIT-04-05": "未链接 TOXIC_SHAME_SPIRAL：taxonomy 把 17、18（自我关怀）列为它的禁忌，"
    "而本档案五节推荐的正是 Neff 自我关怀，两者冲突（待 G-0）",
    "SIT-02-01": "五节“严禁说想开点”：措辞层面，WILLOW 说教改写已含“想开点”",
    "SIT-06-04": "五节“禁止说节哀顺变/想开点/该走出来了”：措辞层面，WILLOW 只含“想开点”；"
    "动作层面已有 m0 与 ACUTE_BEREAVEMENT_SHOCK",
    "SIT-08-02": "五节“绝不说这只是你的心理作用”：措辞层面，WILLOW 未收录（模板本身不含）",
    "SIT-05-03": "五节“绝不说教熬夜伤身体”：措辞层面，模板不含",
    "SIT-03-06": "五节“绝不强行粗暴清空”：做法层面，没有对应的方法或枚举",
    "SIT-07-02": "五节“绝不强行破门”：做法层面，没有对应的方法或枚举",
    "SIT-10-02": "五节“绝不单纯做粗暴戒断”：做法层面，没有对应的方法或枚举",
    "SIT-08-03": "五节“暴食后绝不惩罚性绝食”：没有对应的方法或枚举",
    "SIT-09-01": "五节推荐冷水敷脸 TIPP，与 PRD §9.3 及红线禁用 12:tipp_cold_water 冲突："
    "红线规则优先，未改动",
}


def main() -> int:
    tax = load_taxonomy()
    lexicon = load_perception_lexicon(tax)
    lang = load_language_data(tax)
    links = source_links(tax)
    flags = tax.red_flags()
    rf_doc = yaml.safe_load(
        (ROOT / "olivia/data/lexicons/red_flags.yaml").read_text(encoding="utf-8")
    )
    rf_patterns: dict[str, int] = {}
    for entry in rf_doc["entries"]:
        rf_patterns[entry["code"]] = rf_patterns.get(entry["code"], 0) + len(entry["patterns"])

    tax_doc = yaml.safe_load((ROOT / "olivia/data/taxonomy.yaml").read_text(encoding="utf-8"))
    rows: list[tuple[str, ...]] = []
    missing: list[str] = []
    totals = {"cues": 0, "rf": 0, "images": 0, "lenses": 0, "contra": 0}
    for spectrum in tax_doc["distress_spectra"]:
        for item in spectrum["items"]:
            code, name, file = item["code"], item["name_zh"], item["file"]
            if not (ROOT / "situations" / file).is_file():
                missing.append(file)
            cues = len(lexicon.situation_cues.get(code, ()))
            if code in flags:
                cue_cell = f"rf {rf_patterns.get(code, 0)}"
                # A red flag always applies its own allowed/banned masks; most also link
                # one contraindication enum through their detection_source.
                contra = sorted(links.red_flags.get(code, frozenset()))
                contra_cell = ",".join([*contra, "masks"])
                route = "rf"
                totals["rf"] += 1
            else:
                cue_cell = str(cues) if cues else "-"
                contra = sorted(links.situations.get(code, frozenset()))
                contra_cell = ",".join(contra) or "-"
                route = "m0" if code in M0_SITUATIONS else "-"
                totals["cues"] += bool(cues)
            images = len(lang.metaphors.by_situation.get(code, ()))
            lenses = lang.situation_lenses.get(code, ())
            totals["images"] += bool(images)
            totals["lenses"] += bool(lenses)
            totals["contra"] += bool(contra) or code in flags
            rows.append(
                (
                    code,
                    cue_cell,
                    str(images) if images else "-",
                    ",".join(lenses) or "-",
                    contra_cell,
                    route,
                    name,
                )
            )

    print("dossier    cues   images lenses    contra                         route name")
    for code, cue_cell, images_cell, lens_cell, contra_cell, route, name in rows:
        print(
            f"{code:<10} {cue_cell:<6} {images_cell:<6} {lens_cell:<9} {contra_cell:<30} "
            f"{route:<5} {name}"
        )
    total = len(rows)
    textual = totals["cues"] + totals["rf"]
    print()
    print(f"dossiers: {total}")
    print(
        f"situation cues: {totals['cues']}/{total} ({totals['cues'] / total:.0%}); "
        f"red-flag detector: {totals['rf']}/{total}; read from text in all: "
        f"{textual}/{total} ({textual / total:.0%}); target >= {CUE_TARGET:.0%}"
    )
    print(f"dossier imagery used: {totals['images']}/{total}")
    print(f"Grade B lenses used: {totals['lenses']}/{total}")
    print(f"contraindications reaching the solver: {totals['contra']}/{total}")
    without = [code for code, cue_cell, *_ in rows if cue_cell == "-"]
    print(f"no situation cues: {', '.join(without) or 'none'}")
    print()
    print("not wired (what a dossier asks to avoid, and why):")
    for code, note in NOT_WIRED.items():
        print(f"  {code}: {note}")
    if missing:
        print(f"missing dossier files: {missing}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
