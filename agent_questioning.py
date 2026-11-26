# agent_question_rewriter.py
# -*- coding: utf-8 -*-
# from __future__ import annotations

from typing import List, Optional
from llm_common import _chat
import logging
import jieba
logging.getLogger("jieba").setLevel(logging.WARNING)
__all__ = ["rewrite_question"]


def _tokens(s: str) -> List[str]:
    """
    将句子用中文分词切成词片段，并做基础清洗：
    - strip / lower
    - 去掉纯标点符号
    - 去重但保留首次出现的顺序
    返回的是去重后的词序列（可用于后续构建集合）
    """
    # 1. 用 jieba 切成词序列
    words = jieba.lcut(s)

    cleaned = []
    for w in words:
        w = w.strip().lower()
        if not w:
            continue
        # 如果这个 token 全部由标点/空白符组成，就跳过
        if all(ch in "，。！？、：；,.!?;:()（）{}[]<>“”‘’\"' \t\n\r" for ch in w):
            continue
        cleaned.append(w)

    # 去重但保留第一次出现的顺序（跟你原本逻辑一致）
    seen = set()
    deduped = []
    for w in cleaned:
        if w not in seen:
            seen.add(w)
            deduped.append(w)

    return deduped


def _jaccard_similarity(a: str, b: str) -> float:
    """
    基于词片段集合的 Jaccard 相似度，用于判断再次提问是否与上一轮过于相似。
    J(A,B) = |A ∩ B| / |A ∪ B|
    """
    if not a or not b:
        return 0.0

    A = set(_tokens(a))
    B = set(_tokens(b))

    if not A or not B:
        return 0.0

    return len(A & B) / float(len(A | B))



def rewrite_question(
    base_prompt: str,
    context: Optional[str] = None,
    *,
    mode: str = "first",
    last_question: Optional[str] = None
) -> str:
    """
将量表原始条目改写为更自然、友善的中文问句。

支持两种模式：
- mode="first": 首次提问
- mode="reask": 同一条目二次追问（上一轮答非所问/很模糊时，需换话术与角度）

严格模式：
- 不做兜底文案；LLM 输出异常/为空/与上一轮过于相似时，打印并抛出异常。
"""
    ctx = (context or "").strip()
    if mode not in {"first", "reask"}:
        mode = "first"

    # === 组装提示词 ===
    if mode == "first":
        sys = (
            "你是一个面向会话式心理测量的提问智能体，具备心理测量、共情沟通与人际互动理解方面的专业知识。"
            "【目标】：将给定的量表题干改写为贴合当前上下文、富有温度且自然的中文对话问法。"
            "引导来访者围绕自己【最近一段时间在人际关系中的一般情况】来回答，而不是只针对某一次事件或某一个人。\n"
            "【可用信息】：最近对话上下文；本轮的目标条目题干。\n"
            "【写作要求】：\n"
            "1）信息使用方式：先阅读题干，明确本题要测量的心理特征及其价值方向；再阅读最近对话上下文，从中提取来访者刚才表达的核心内容，用于共情和过渡；在此基础上设计提问，使问题既紧扣题干，又自然承接上下文。\n"
            "2）共情：围绕来访者刚才的主要内容，用自然、温和、贴近语境的语言进行回应，使其感到被理解与接纳；只依据信息本身进行合理推断，不添加文本中不存在的关键经历或评价。\n"
            "3）过渡：用一到两句简洁的衔接语，将共情内容平滑地过渡到本题所关注的心理特征；需要点到来访者上一轮的核心内容，同时清晰引出本题的关注方向；不得只做量表题干的同义改写，也不得使用空泛、模板化的套话。\n"
            "4）提问：必须紧扣题干对应的心理特征及其方向，保持题干中对他人态度、关系变化或自我感受的原始含义。必须保留题干中用于描述心理特征强度或他人评价态度的关键用语，不得删除或替换。改写时不得改变该特征的严重程度，不得将较为宽泛的主观感受收缩为单一情绪类别，也不得引入题干中未包含的极端表述或新的关注焦点。\n"
            "提问需为口语化、开放式问句，引导来访者描述【最近一段时间在人际关系中的总体情况】，而不是某一次偶发现象；情境范围应与题干内容保持一致，但不局限于上下文中的单一对象。\n"
            "5）语言多样性：在生成本轮内容前，应先完整阅读当前会话的所有上下文，禁止对治疗师先前发言进行同义或轻微改写，避免语义或表述高度相似，确保语言具有足够的多样性与新鲜感。\n"
            "【输出形式】：\n"
            "输出2–3句，顺序为“共情 → 过渡 → 单点提问”。语气自然、不审问、不贴标签；不得出现“量表”“测试”“评分”“题目”等字样；只输出可直接发送给来访者的内容，不要解释、不加引号。"
        )
        usr = (
            f"【题干】{base_prompt}\n"
            f"【近期上下文】\n{ctx}\n"
            "请严格按照“共情 → 过渡（必要时）→ 单点提问”的结构生成 2–3 句，满足以上要求。"
        )
        temp = 0.25

    else:  # mode == "reask"
        sys = (
            "你是一个面向会话式心理测量的提问智能体，具备心理测量、共情沟通与人际互动理解方面的专业知识。"
            "【目标】：当来访者在上一轮对同一题干的回答偏离主题、未触及核心或表达模糊时，在保持题干的核心含义和情绪强度不变的前提下，使用与上一轮问法显著不同的方式重新提问，并温和提醒来访者按照【最近一段时间在人际关系中的一般情况】来回答，而不是只围绕某一次具体事件。\n"
            "【可用信息】：当前题干、上一轮问法、最近对话上下文。\n"
            "【写作要求】：\n"
            "1）信息使用方式：先阅读题干，明确本题要测量的心理特征及其方向；再阅读上一轮问法，明确其提问角度和语言表达；最后结合最近对话上下文，从来访者最近一轮回复中提取适合作为共情与过渡的核心内容，在此基础上重新设计新的问法。\n"
            "2）共情：围绕来访者最近回复中关键的事实或情绪，用简短、真诚、贴近语境的语言表达理解与接纳；仅在现有文本信息基础上进行适度推断，不添加文本中不存在的关键经历或评价。\n"
            "3）过渡：用一到两句自然的衔接语，将内容平滑引向本题关注的心理特征；需要同时承接来访者上一轮的主要内容，并清晰导入新的提问方向；不得仅对量表题干或上一轮提问进行机械的同义转换，也不得使用空泛、模板化的套话。\n"
            "4）提问：必须紧扣题干对应的心理特征及其方向，保持题干中对他人态度、关系变化或自我感受的原始含义。必须保留题干中用于描述心理特征强度或他人评价态度的关键用语，不得删除或替换。改写时不得改变该特征的严重程度，不得将较为宽泛的主观感受收缩为单一情绪类别，也不得引入题干中未包含的极端表述或新的关注焦点。\n"
            "5）提问需为口语化的开放式问句，引导来访者概括【最近一段时间在人际关系中的总体情况】，而非仅针对单一事件或单一关系对象作答；情境范围与题干内容保持一致，但不局限于上下文中的某一个具体人物或情境。\n"
            "6）差异性要求：新的提问在措辞、结构和切入角度上须与上一轮问法具有明显差异，不得只替换个别词语或仅调整语序，不得重复使用上一轮问法中的关键短语或固定句型。\n"
            "【输出形式】：\n"
            "按“共情 → 过渡（可省略）→ 单点提问”的顺序输出2–3句，自然口语化，不审问、不贴标签；不得出现“量表”“测试”“评分”“题目”等字样；只输出可直接发送给来访者的内容，不要解释、不加引号。"
        )
        usr = (
            f"【题干】{base_prompt}\n"
            f"【近期上下文】\n{ctx}\n"
            f"【上一轮问法】{last_question}\n"
            "请按“共情 → 过渡（可省略）→ 单点提问”的结构生成 2–3 句，满足以上要求。"
        )
        temp = 0.35

    # === 生成 ===
    try:
        out = _chat(
            [{"role": "system", "content": sys}, {"role": "user", "content": usr}],
            temperature=temp,
        )
    except Exception as e:
        print(f"[agent_question_rewriter] LLM 调用失败: {e}")
        print("[agent_question_rewriter] system:", sys)
        print("[agent_question_rewriter] user:", usr)
        raise

    q = (out or "").strip().replace("\n", " ")
    if not q:
        print("[agent_question_rewriter] 输出为空")
        print("[agent_question_rewriter] raw:", out)
        print("[agent_question_rewriter] system:", sys)
        print("[agent_question_rewriter] user:", usr)
        raise ValueError("rewrite_question 生成空字符串")

    # === 二次追问：强制“与上一问不同” ===
    if mode == "reask" and last_question:
        sim = _jaccard_similarity(q, last_question.strip())
        if sim >= 0.6 or q == last_question.strip():
            # 再请求一次：强调“不要复用上一轮任何词/句式”
            try:
                sys2 = (
                    "对下面的句子做明显不同的同义改写："
                    "不得复用其关键词和句式；换一个新的切入角度；保持友善口语化；只问一个点；"
                    "不出现“量表/测试/评分/题目”等字样。只输出改写后的问句，不要解释、不加引号。"
                )
                out2 = _chat(
                    [{"role": "system", "content": sys2}, {"role": "user", "content": q}],
                    temperature=0.6,
                )
                q2 = (out2 or "").strip().replace("\n", " ")
                if not q2:
                    print("[agent_question_rewriter] 二次改写输出为空")
                    print("[agent_question_rewriter] raw2:", out2)
                    raise ValueError("reask 二次改写空输出")
                q = q2
            except Exception as e:
                print(f"[agent_question_rewriter] 二次去重改写失败: {e}")
                print("[agent_question_rewriter] 原问法:", last_question)
                print("[agent_question_rewriter] 初稿:", q)
                raise

        # 最终再做一次相似度校验
        final_sim = _jaccard_similarity(q, last_question.strip())
        if final_sim >= 0.6 or q == last_question.strip():
            print("[agent_question_rewriter] 最终问法仍与上一轮过于相似")
            print("[agent_question_rewriter] last_question:", last_question)
            print("[agent_question_rewriter] new_question:", q)
            raise ValueError("reask 与上一轮过于相似")

    return q
