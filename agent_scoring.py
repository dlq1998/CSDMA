# -*- coding: utf-8 -*-
from __future__ import annotations
import json
from typing import Any, Dict, List
from llm_common import _chat, _extract_json

# -------- 全局缓存，避免每次都重复加载 --------
_SCL90_BY_INDEX: Dict[int, Dict[str, Any]] = {}


# -------- 全局缓存，避免每次都重复加载 --------
_IPSM_LEVELS_BY_INDEX: Dict[int, Dict[str, Any]] = {}


def load_ipsm_levels(path: str = "ipsm-cs_level.json") -> Dict[int, Dict[str, Any]]:
    global _IPSM_LEVELS_BY_INDEX
    if _IPSM_LEVELS_BY_INDEX:
        return _IPSM_LEVELS_BY_INDEX

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("ipsm-cs_level.json 顶层必须是数组。")

    by_index: Dict[int, Dict[str, Any]] = {}
    for item in data:
        idx = int(item["index"])
        by_index[idx] = item

    _IPSM_LEVELS_BY_INDEX = by_index
    return _IPSM_LEVELS_BY_INDEX


def _build_item_reference_text(item: Dict[str, Any], keep_per_level: int = 10) -> str:
    lines: List[str] = []
    for lvl in ("1", "2", "3", "4", "5"):
        examples: List[str] = item.get(lvl, [])[:keep_per_level]
        lines.append(f"【分值参考 - {lvl}分】")
        for ex in examples:
            lines.append(f"- {ex}")
        lines.append("")  # 空行分隔
    return "\n".join(lines).strip()


LEVEL_GUIDE = """
【分值含义（通用，IPSM-CS 5分制）】
1分＝很不符合我：明确否认条目描述，通常没有此类表现，或表现与描述相反。
2分＝不符合我：总体不符合，但偶尔或在少数情境下存在此类表现。
3分＝不确定：难以明确认同或否认，符合与不符合的表现均有体现。
4分＝符合我：总体符合，通常存在此类表现，但在部分情境下存在例外。
5分＝很符合我：高度符合，相关表现普遍出现，能够充分代表通常情况，几乎没有例外。
"""



def score_severity_1_5(
    text: str,
    item_index: int,
    question_text: str | None = None,
    context_text: str | None = None,
    levels_path: str = "ipsm-cs_level.json",
) -> int:
    by_index = load_ipsm_levels(levels_path)
    if item_index not in by_index:
        raise ValueError(f"未找到条目 index={item_index} 的参考定义，请检查 ipsm-cs_level.json。")

    item = by_index[item_index]
    prompt_cn = item.get("prompt", "")

    # 构造“仅限该条目”的评分参考
    refs = _build_item_reference_text(item, keep_per_level=10)

    sys_msg = """
    你是一个面向会话式心理测量的评分智能体，具备心理测量与文本信息分析方面的专业知识。
    【任务目标】
    根据来访者对心理量表条目的回答，评估其在“人际敏感性（IPSM）”维度上的特质程度。
    【可用信息】
    当前条目与问答语境、IPSM 四分制分值定义、当前条目对应的评分参考表述
    【IPSM-CS五分制评分锚点】
    1分（很不符合我）：
     核心定义：条目描述与受测者自身情况明显不符。
     判定标准：受测者明确否认条目描述，并说明自己通常没有此类想法、感受或行为，或通常表现与条目描述相反，未描述出符合条目的实际表现。
    2分（不符合我）：
     核心定义：条目描述总体不符合受测者自身情况，但存在少量符合的表现。
     判定标准：受测者总体否认条目描述，但明确提及自己偶尔会有此类想法、感受或行为，或在少数特定情境下确实如此。这些表现较为有限，不足以代表其通常情况。
    3分（不确定）：
     核心定义：受测者对条目是否符合自身情况没有明确倾向。
     判定标准：受测者在理解条目后仍难以认同或否认，或描述了随情境变化的不同表现，符合与不符合的情况均占一定比重，整体未明显偏向任何一方。
    4分（符合我）：
     核心定义：条目描述总体符合受测者自身情况，但存在一定例外。
     判定标准：受测者总体认同条目描述，所述想法、感受或行为能够代表其通常情况，但明确指出在某些对象、场合或条件下不符合条目描述。
    5分（很符合我）：
     核心定义：条目描述与受测者自身情况高度相符。
     判定标准：受测者的表达以高度认同为主，条目所述倾向在其相关经历中普遍出现，能够充分代表其通常情况，仅有极少或基本没有不符合的表现。
    """

    user_msg = f"""
    【评估条目】：
    编号：{item_index}
    题干：{prompt_cn}
    【问答语境】：
    当前问法：{question_text or '(无)'}
    近窗上下文：{context_text or '(无)'}
    注意：评分仅依据来访者当前回复及上下文中与当前条目直接相关的表达；上下文仅用于辅助理解，不作为额外评分依据。
    【来访者原话】：
    {text or '(无)'}
    【分值含义】：
    {LEVEL_GUIDE}
    【本条目参考表述】：
    {refs}
    【输出要求】
    仅输出一个纯 JSON 对象：{"score": int, "reason": "string"}
    """

    out = _chat(
        [{"role": "system", "content": sys_msg},
         {"role": "user", "content": user_msg}],
        temperature=0.0
    )


    data = _extract_json(out)

    if "score" not in data:
        raise ValueError("智能体未返回 'score' 字段。原始输出：{}".format(out))
    try:
        s = int(data["score"])
    except Exception as e:
        raise ValueError(f"智能体返回的 score 非整数：{data.get('score')}") from e

    if s < 1 or s > 5:
        raise ValueError(f"智能体返回的 score 超出范围：{s}（期望 1..5）")

    # 规范化：强制 score 为 int，reason 为字符串（可以为空）
    data["score"] = s
    if "reason" in data:
        try:
            data["reason"] = str(data["reason"])
        except Exception:
            data["reason"] = ""
    else:
        data["reason"] = ""

    return data


