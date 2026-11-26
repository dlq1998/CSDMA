# llm_common.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, re, requests
from typing import List, Dict, Any, Optional


API_URL = os.getenv("LLM_API_URL", "xxxxxx")
API_KEY = os.getenv("LLM_API_KEY", "xxxxx")
MODEL   = os.getenv("LLM_MODEL",   "gpt-4o")
TIMEOUT = int(os.getenv("LLM_TIMEOUT_SEC", "60"))



def _chat(
    messages: List[Dict[str, str]],
    temperature: float = 0.0,
    max_tokens: Optional[int] = None,   # ← 新增
) -> str:
    if not API_KEY or API_KEY == "YOUR_API_KEY":
        raise RuntimeError("请设置 LLM_API_KEY")
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": float(temperature),
    }
    if max_tokens is not None:          # ← 新增
        payload["max_tokens"] = int(max_tokens)

    r = requests.post(API_URL, headers=headers, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict:
    raw = text.strip()

    # 1) 严格 JSON
    try:
        return json.loads(raw)
    except Exception:
        pass

    # 2) 去除 ```json / ``` 包裹
    code_fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, flags=re.I)
    if code_fence:
        candidate = code_fence.group(1).strip()
        try:
            return json.loads(candidate)
        except Exception:
            raw = candidate  # 继续后续容错

    # 3) 提取第一个 {...}
    obj = None
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        obj = m.group(0).strip()
        try:
            return json.loads(obj)
        except Exception:
            pass

    # 4) 规范化：容忍 {score:1} / {'score':1}
    candidate = obj or raw
    # 去掉换行与多余空白，便于替换
    compact = re.sub(r"\s+", " ", candidate)

    # key 无引号 → 加引号；先只处理 score 这个键，避免误伤
    compact = re.sub(r"\{[\s]*score[\s]*:", r'{"score":', compact)
    # 单引号 → 双引号
    compact = compact.replace("'", '"')

    try:
        return json.loads(compact)
    except Exception:
        pass

    # 5) 兜底：直接抓分数
    m2 = re.search(r'"?score"?\s*:\s*([1-4])', candidate)
    if m2:
        return {"score": int(m2.group(1))}

    # 仍失败 → 抛错误并附原文，便于排查
    raise ValueError(f"LLM did not return valid JSON: {text}")


