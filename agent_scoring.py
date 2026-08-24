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
    """
    将“当前条目”的 1–4 分参考描述整理成可读文本，以提供给模型对齐判定依据。
    keep_per_level: 每个分值层级保留多少条参考语句（默认 10，全量保留）。
    """
    lines: List[str] = []
    for lvl in ("1", "2", "3", "4"):
        examples: List[str] = item.get(lvl, [])[:keep_per_level]
        lines.append(f"【分值参考 - {lvl}分】")
        for ex in examples:
            lines.append(f"- {ex}")
        lines.append("")  # 空行分隔
    return "\n".join(lines).strip()


LEVEL_GUIDE = """
【分值含义（通用，IPSM 4分制）】
1分＝完全不符合：完全没有这种体验或极为偶尔。
2分＝不太符合：偶尔有，但不太明显。
3分＝相当符合：经常出现或造成一定困扰。
4分＝非常符合：非常频繁且造成显著困扰。
"""



def score_severity_1_4(
    text: str,
    item_index: int,
    question_text: str | None = None,
    context_text: str | None = None,
    levels_path: str = "ipsm-cs_level.json",
) -> int:
    """
    针对“当前条目(item_index)”对用户自由文本进行 1..4 的严重度评分。

    评分机制：
    1) 只加载该条目的 1–4 分“参考表述”；
    2) 将这些参考作为判定依据喂给模型（few-shot 对齐）；
    3) 模型**必须**在 1..4 中选择一个分值并输出严格 JSON：{"score": x}；
    4) 若未返回合法 1..4，则抛出异常（不使用任何默认值）。
    """
    by_index = load_ipsm_levels(levels_path)
    if item_index not in by_index:
        raise ValueError(f"未找到条目 index={item_index} 的参考定义，请检查 ipsm-cs_level.json。")

    item = by_index[item_index]
    prompt_cn = item.get("prompt", "")

    # 构造“仅限该条目”的评分参考
    refs = _build_item_reference_text(item, keep_per_level=10)

    sys_msg = """
    你是一个面向会话式心理测量的评分智能体，具备心理测量与文本信息分析方面的专业知识。
    【目标】：
    请根据我提供的信息，判断来访者在特定心理特征（由条目定义）上的出现程度，并在 IPSM 4 分制下给出一致性评分。

    【可用信息】：
    当前条目与问答语境、IPSM 四分制分值定义、当前条目对应的评分参考表述

    【IPSM 四分制裁决锚点】
    1分（完全不符合）:
     核心定义：特征未出现，或来访者明确否认在意。
     判定标准：受测者的自我评价体系完全内部化，情绪与行为独立于外界反馈。对条目所述内容表现出一种"无涉感"，不存在针对人际关系的心理波动。
    2分（轻微符合）：
     核心定义：有轻微念头，但频率低、强度弱。
     判定标准：承认存在一过性的、微弱的情绪起伏。关键判定点在于"不占权重"和"转瞬即逝"。这种在意仅停留在表层意识，未进入深层认知加工，未造成心理滞留或反刍。
    3分（比较符合）：
     核心定义：特征明显，在特定情境下会有较强的心理反应。
     判定标准：情绪易感性高于平均水平。受测者在面对特定的人际刺激时（如被批评、冷落），会有明显的情绪波动和关注，可能需要一定时间来消化，但仍能维持基本的自我调节能力。
    4分（完全符合）：
     核心定义: 特征非常强烈，这种在意已成为一种惯性的思维或行为习惯。
     判定标准: 敏感性已成为其性格中的显著部分。受测者对他人的评价、情绪或关系变化保持高度觉察，并容易因此受到较大影响（如感到焦虑、为了维护关系而妥协）。这种特质在生活中高频出现，明显影响了其情绪状态或决策倾向.

    """

    user_msg = f"""
    【评估条目】：
    编号：{item_index}
    题干：{prompt_cn}
    【问答语境】：
    - 当前问法：{question_text or '(无)'}
    - 近窗上下文：{context_text or '(无)'}
    【来访者原话】：
    {text}
    【分值含义】：
    {LEVEL_GUIDE}
    【本条目参考表述】：
    {refs}

    请依据以上信息，判断来访者在该心理特征上的出现程度，只根据本条目本身进行评分，并严格按照上述 4 分制给出判断。

    请只输出一个严格的 JSON 对象，不要包含任何额外文字或注释：
    {{"score": 1|2|3|4, "reason": "请说明为何给出该分数"}}
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

    if s < 1 or s > 4:
        raise ValueError(f"智能体返回的 score 超出范围：{s}（期望 1..4）")

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


