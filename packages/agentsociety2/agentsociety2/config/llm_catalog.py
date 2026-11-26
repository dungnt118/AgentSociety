"""Master AI Provider & Model Catalog, Rate Cards, and Resolution Helpers.

Tham chiếu kiến trúc quản trị AI đa mô hình của EvidenceAtlas, cung cấp:
- Danh mục 11 nhà cung cấp AI & ~50+ mô hình đã xác minh kèm thông số (Context, Max Output, Vision, Reasoning).
- Bảng đơn giá chuẩn xác (USD / 1M tokens) cho Input / Cached Read / Output.
- Mặc định hệ thống ưu tiên ``gpt-6-luna`` với chế độ Reasoning ``off``.
- Các hàm chuẩn hóa ``base_url``, ``api_type``, ``thinking``, ``reasoning_effort``,
  bộ lọc mô hình lỗi thời và hàm khớp đơn giá theo độ dài khóa giảm dần.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "AI_PROVIDER_PRESETS",
    "DEFAULT_LLM_MODEL",
    "DEFAULT_LLM_PROVIDER",
    "DEFAULT_LLM_THINKING",
    "DEFAULT_REASONING_EFFORT_WHEN_ON",
    "MODEL_RATES_USD_PER_TOKEN",
    "VALID_REASONING_EFFORTS",
    "VALID_THINKING_MODES",
    "VERIFIED_MODEL_CATALOG",
    "get_llm_catalog_payload",
    "is_obsolete_model_id",
    "normalize_thinking_config",
    "resolve_model_rates_usd",
    "resolve_provider_api_type",
    "resolve_provider_base_url",
]

DEFAULT_LLM_PROVIDER = "openai"
DEFAULT_LLM_MODEL = "gpt-6-luna"
DEFAULT_LLM_THINKING = "off"
DEFAULT_REASONING_EFFORT_WHEN_ON = "low"

VALID_THINKING_MODES: tuple[str, ...] = ("off", "on", "inherit")
VALID_REASONING_EFFORTS: tuple[str, ...] = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)

AI_PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "openai": {
        "provider": "openai",
        "label": "OpenAI (GPT-6 Luna / Sol / Terra / Astra & GPT-5.x)",
        "short_label": "OpenAI",
        "tag_color": "green",
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-6-luna",
        "api_type": "openai",
        "key_prefix_hint": "sk-proj-...",
        "notes_vi": "Hỗ trợ chuẩn OpenAI /v1/chat/completions & /v1/models. Mặc định ưu tiên gpt-6-luna (Reasoning: off) siêu tiết kiệm.",
    },
    "gemini": {
        "provider": "gemini",
        "label": "Google Gemini (Gemini 4 Argon / 3.8 Flash / 3.1 Pro / 2.5)",
        "short_label": "Google Gemini",
        "tag_color": "blue",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-3.8-flash",
        "api_type": "openai",
        "key_prefix_hint": "AIzaSy...",
        "notes_vi": "Dùng endpoint OpenAI-compatible của Google AI Studio (/v1beta/openai) để tương thích hoàn toàn tool-calling & reasoning_effort.",
    },
    "claude": {
        "provider": "claude",
        "label": "Anthropic Claude (Claude 5.5 Haiku / Sonnet / Opus / Fable 5.1)",
        "short_label": "Anthropic Claude",
        "tag_color": "volcano",
        "default_base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-haiku-5-5",
        "api_type": "anthropic",
        "key_prefix_hint": "sk-ant-api03-...",
        "notes_vi": "Gọi chuẩn Anthropic Messages API (/v1/messages) và đồng bộ danh sách mô hình từ /v1/models.",
    },
    "deepseek": {
        "provider": "deepseek",
        "label": "DeepSeek (V4.1 Flash / V4 Pro / V3 Chat / R1 Reasoner)",
        "short_label": "DeepSeek",
        "tag_color": "purple",
        "default_base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-v4.1-flash",
        "api_type": "openai",
        "key_prefix_hint": "sk-...",
        "notes_vi": "Tương thích chuẩn DeepSeek API (/v1/chat/completions & /v1/models), hỗ trợ Context Caching tự động.",
    },
    "xai": {
        "provider": "xai",
        "label": "xAI Grok (Grok 4.7 / 4.6 / 4.3 / 4.20)",
        "short_label": "xAI Grok",
        "tag_color": "magenta",
        "default_base_url": "https://api.x.ai/v1",
        "default_model": "grok-4.7",
        "api_type": "openai",
        "key_prefix_hint": "xai-...",
        "notes_vi": "Kết nối trực tiếp xAI API (/v1/chat/completions & /v1/models) hỗ trợ Grok 4.x.",
    },
    "qwen": {
        "provider": "qwen",
        "label": "Alibaba Qwen / DashScope (Qwen3.8 Omni-Flash / Max / 3.7 Plus)",
        "short_label": "Alibaba Qwen",
        "tag_color": "orange",
        "default_base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen3.8-omni-flash",
        "api_type": "openai",
        "key_prefix_hint": "sk-...",
        "notes_vi": "Kết nối Alibaba Cloud Model Studio (DashScope OpenAI-Compatible API) hỗ trợ Qwen 3.8 / 3.7 / 2.5.",
    },
    "mistral": {
        "provider": "mistral",
        "label": "Mistral AI (Small 4 / Large 4 / Medium 3.5 / Codestral)",
        "short_label": "Mistral AI",
        "tag_color": "gold",
        "default_base_url": "https://api.mistral.ai/v1",
        "default_model": "mistral-small-4-0",
        "api_type": "openai",
        "key_prefix_hint": "...",
        "notes_vi": "Kết nối trực tiếp Mistral La Plateforme API (/v1/chat/completions & /v1/models).",
    },
    "openai_compatible": {
        "provider": "openai_compatible",
        "label": "OpenAI-Compatible Gateway (OpenRouter / LiteLLM / Groq / Azure)",
        "short_label": "OpenAI-Compatible",
        "tag_color": "cyan",
        "default_base_url": "https://openrouter.ai/api/v1",
        "default_model": "openai/gpt-6-luna",
        "api_type": "openai",
        "key_prefix_hint": "sk-or-v1-...",
        "notes_vi": "Dành cho OpenRouter, LiteLLM Proxy, Groq, Azure hoặc cổng proxy nội bộ chuẩn OpenAI.",
    },
    "zhipuai": {
        "provider": "zhipuai",
        "label": "ZhipuAI (GLM-4)",
        "short_label": "ZhipuAI",
        "tag_color": "geekblue",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
        "api_type": "openai",
        "key_prefix_hint": "...",
        "notes_vi": "Kết nối ZhipuAI BigModel API chuẩn OpenAI-compatible.",
    },
    "siliconflow": {
        "provider": "siliconflow",
        "label": "SiliconFlow",
        "short_label": "SiliconFlow",
        "tag_color": "lime",
        "default_base_url": "https://api.siliconflow.cn/v1",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "api_type": "openai",
        "key_prefix_hint": "sk-...",
        "notes_vi": "Kết nối SiliconFlow API cho các mô hình mã nguồn mở hiệu năng cao.",
    },
    "vllm": {
        "provider": "vllm",
        "label": "vLLM / Self-Hosted Local Endpoint",
        "short_label": "vLLM / Local",
        "tag_color": "default",
        "default_base_url": "http://host.docker.internal:8000/v1",
        "default_model": "",
        "api_type": "openai",
        "key_prefix_hint": "EMPTY",
        "notes_vi": "Dành cho cụm vLLM / Ollama / SGLang tự triển khai nội bộ.",
    },
}


def _model(
    provider: str,
    model_id: str,
    display_name: str,
    context_window: int,
    max_output_tokens: int,
    input_usd_per_1m: float,
    cached_input_usd_per_1m: float,
    output_usd_per_1m: float,
    *,
    supports_reasoning: bool = True,
    supports_vision: bool = True,
    is_recommended_default: bool = False,
    notes_vi: str = "",
) -> dict[str, Any]:
    return {
        "provider": provider,
        "model_id": model_id,
        "display_name": display_name,
        "context_window": context_window,
        "max_output_tokens": max_output_tokens,
        "input_usd_per_1m": input_usd_per_1m,
        "cached_input_usd_per_1m": cached_input_usd_per_1m,
        "output_usd_per_1m": output_usd_per_1m,
        "supports_reasoning": supports_reasoning,
        "supports_vision": supports_vision,
        "is_recommended_default": is_recommended_default,
        "notes_vi": notes_vi,
    }


VERIFIED_MODEL_CATALOG: list[dict[str, Any]] = [
    # --- OpenAI ---
    _model(
        "openai",
        "gpt-6-luna",
        "OpenAI GPT-6 Luna (Mặc định khuyến nghị 1.05M)",
        1_050_000,
        128_000,
        0.10,
        0.01,
        0.50,
        supports_reasoning=True,
        supports_vision=True,
        is_recommended_default=True,
        notes_vi="Mặc định ưu tiên: siêu tiết kiệm ($0.10/$0.50 per 1M), 1.05M context, khuyến nghị tắt Reasoning (off) khi chạy Agent nhiều lượt.",
    ),
    _model(
        "openai",
        "gpt-6.1-terra",
        "OpenAI GPT-6.1 Terra (Fast Multimodal & Agentic)",
        1_050_000,
        128_000,
        1.00,
        0.05,
        5.00,
        notes_vi="Tốc độ cao, cân bằng chất lượng đa phương thức & tác vụ Agentic 1.05M context.",
    ),
    _model(
        "openai",
        "gpt-6.1-sol",
        "OpenAI GPT-6.1 Sol (Coding & Reasoning)",
        1_050_000,
        128_000,
        2.00,
        0.10,
        10.00,
        notes_vi="Tối ưu sinh code và suy luận Agentic phức tạp với 1.05M context.",
    ),
    _model(
        "openai",
        "gpt-6-sol",
        "OpenAI GPT-6 Sol (Balanced Frontier)",
        1_050_000,
        128_000,
        2.00,
        0.20,
        10.00,
        notes_vi="Cân bằng hiệu năng suy luận và chi phí thế hệ GPT-6.",
    ),
    _model(
        "openai",
        "gpt-6-astra",
        "OpenAI GPT-6 Astra (Frontier Flagship)",
        1_050_000,
        128_000,
        10.00,
        1.00,
        50.00,
        notes_vi="Flagship mạnh nhất dòng GPT-6 cho phân tích kiến trúc & lập kế hoạch phức tạp.",
    ),
    _model(
        "openai",
        "gpt-5.6",
        "OpenAI GPT-5.6 (Previous Frontier 1.05M)",
        1_050_000,
        128_000,
        2.50,
        0.625,
        10.00,
        notes_vi="Flagship thế hệ GPT-5.6 với 1.05M context.",
    ),
    _model(
        "openai",
        "gpt-5.5",
        "OpenAI GPT-5.5 (High-Precision Multimodal)",
        1_050_000,
        128_000,
        1.25,
        0.125,
        10.00,
        notes_vi="Mô hình GPT-5.5 tiêu chuẩn với 1.05M context.",
    ),
    _model(
        "openai",
        "gpt-5.4",
        "OpenAI GPT-5.4 (Enterprise Coding & Synthesis)",
        1_050_000,
        128_000,
        2.00,
        0.50,
        8.00,
        notes_vi="Mô hình GPT-5.4 doanh nghiệp.",
    ),
    _model(
        "openai",
        "gpt-5.4-mini",
        "OpenAI GPT-5.4 Mini (400K Context)",
        400_000,
        128_000,
        0.75,
        0.075,
        4.50,
        notes_vi="Mô hình GPT-5.4 Mini (đơn giá OpenAI $0.75/$4.50 per 1M tokens).",
    ),
    _model(
        "openai",
        "gpt-5.4-nano",
        "OpenAI GPT-5.4 Nano (Ultra-Fast Triage)",
        400_000,
        128_000,
        0.20,
        0.020,
        1.25,
        notes_vi="Mô hình GPT-5.4 Nano siêu nhẹ cho phân loại & mô phỏng khối lượng lớn.",
    ),
    _model(
        "openai",
        "gpt-5",
        "OpenAI GPT-5",
        400_000,
        128_000,
        1.80,
        0.45,
        7.20,
        notes_vi="Mô hình nền tảng GPT-5 chuẩn 400K context.",
    ),
    _model(
        "openai",
        "gpt-5-mini",
        "OpenAI GPT-5 Mini",
        400_000,
        128_000,
        0.35,
        0.085,
        1.40,
        notes_vi="Mô hình GPT-5 Mini cân bằng chi phí.",
    ),
    _model(
        "openai",
        "gpt-4.1",
        "OpenAI GPT-4.1",
        1_047_576,
        32_768,
        2.00,
        0.50,
        8.00,
        supports_reasoning=False,
        notes_vi="Thế hệ GPT-4.1 (non-reasoning) ổn định, 1M context.",
    ),
    _model(
        "openai",
        "gpt-4.1-mini",
        "OpenAI GPT-4.1 Mini",
        1_047_576,
        32_768,
        0.40,
        0.10,
        1.60,
        supports_reasoning=False,
        notes_vi="GPT-4.1 Mini tốc độ cao, chi phí thấp.",
    ),
    _model(
        "openai",
        "gpt-4.1-nano",
        "OpenAI GPT-4.1 Nano",
        1_047_576,
        16_384,
        0.10,
        0.025,
        0.40,
        supports_reasoning=False,
        notes_vi="GPT-4.1 Nano siêu nhẹ.",
    ),
    _model(
        "openai",
        "gpt-4o",
        "OpenAI GPT-4o",
        128_000,
        16_384,
        2.50,
        1.25,
        10.00,
        supports_reasoning=False,
        notes_vi="Mô hình đa phương thức GPT-4o.",
    ),
    _model(
        "openai",
        "gpt-4o-mini",
        "OpenAI GPT-4o Mini",
        128_000,
        16_384,
        0.15,
        0.075,
        0.60,
        supports_reasoning=False,
        notes_vi="GPT-4o Mini tiết kiệm chi phí.",
    ),
    _model(
        "openai",
        "o3",
        "OpenAI o3 (Advanced Reasoning)",
        200_000,
        100_000,
        2.00,
        0.50,
        8.00,
        notes_vi="Mô hình suy luận chuyên sâu o3.",
    ),
    _model(
        "openai",
        "o4-mini",
        "OpenAI o4-mini (Fast Reasoning)",
        200_000,
        100_000,
        1.10,
        0.275,
        4.40,
        notes_vi="Mô hình suy luận tốc độ cao o4-mini.",
    ),
    # --- Google Gemini ---
    _model(
        "gemini",
        "gemini-3.8-flash",
        "Google Gemini 3.8 Flash (Khuyến nghị)",
        1_048_576,
        65_536,
        0.75,
        0.075,
        3.75,
        is_recommended_default=True,
        notes_vi="Gemini 3.8 Flash 1M context, hỗ trợ Thinking & Vision tốc độ cao.",
    ),
    _model(
        "gemini",
        "gemini-4-argon",
        "Google Gemini 4 Argon (Frontier 1M)",
        1_048_576,
        65_536,
        2.00,
        0.20,
        10.00,
        notes_vi="Flagship Gemini 4 Argon suy luận kiến trúc & đa phương thức.",
    ),
    _model(
        "gemini",
        "gemini-3.8-live",
        "Google Gemini 3.8 Live",
        1_048_576,
        65_536,
        0.75,
        0.075,
        3.75,
        notes_vi="Độ trễ siêu thấp cho tác vụ Agentic tương tác thời gian thực.",
    ),
    _model(
        "gemini",
        "gemini-3.6-flash",
        "Google Gemini 3.6 Flash",
        1_048_576,
        65_536,
        0.75,
        0.075,
        3.75,
        notes_vi="Gemini 3.6 Flash đa phương thức kèm suy luận chuỗi.",
    ),
    _model(
        "gemini",
        "gemini-3.5-flash",
        "Google Gemini 3.5 Flash",
        1_048_576,
        65_536,
        0.30,
        0.075,
        2.50,
        notes_vi="Gemini 3.5 Flash cân bằng hiệu năng & chi phí.",
    ),
    _model(
        "gemini",
        "gemini-3.1-pro",
        "Google Gemini 3.1 Pro",
        1_048_576,
        65_536,
        1.50,
        0.375,
        12.00,
        notes_vi="Flagship Gemini 3.1 Pro chuyên sâu cho phân tích phức tạp.",
    ),
    _model(
        "gemini",
        "gemini-3.1-flash",
        "Google Gemini 3.1 Flash",
        1_048_576,
        65_536,
        0.28,
        0.07,
        2.20,
        notes_vi="Gemini 3.1 Flash tốc độ cao.",
    ),
    _model(
        "gemini",
        "gemini-3.1-flash-lite",
        "Google Gemini 3.1 Flash-Lite (Ultra Low-Cost)",
        1_048_576,
        65_536,
        0.10,
        0.025,
        0.40,
        supports_reasoning=False,
        notes_vi="Gemini 3.1 Flash-Lite siêu tiết kiệm.",
    ),
    _model(
        "gemini",
        "gemini-2.5-pro",
        "Google Gemini 2.5 Pro",
        1_048_576,
        65_536,
        1.25,
        0.31,
        10.00,
        notes_vi="Gemini 2.5 Pro 1M context hỗ trợ suy luận sâu.",
    ),
    _model(
        "gemini",
        "gemini-2.5-flash",
        "Google Gemini 2.5 Flash",
        1_048_576,
        65_536,
        0.30,
        0.075,
        2.50,
        notes_vi="Gemini 2.5 Flash ổn định, cân bằng tốc độ và chi phí.",
    ),
    _model(
        "gemini",
        "gemini-2.5-flash-lite",
        "Google Gemini 2.5 Flash-Lite",
        1_048_576,
        32_768,
        0.10,
        0.025,
        0.40,
        supports_reasoning=False,
        notes_vi="Gemini 2.5 Flash-Lite siêu tiết kiệm cho lưu lượng cao.",
    ),
    # --- Anthropic Claude ---
    _model(
        "claude",
        "claude-haiku-5-5",
        "Anthropic Claude Haiku 5.5 (Khuyến nghị High-Volume)",
        1_000_000,
        128_000,
        0.10,
        0.01,
        0.50,
        is_recommended_default=True,
        notes_vi="Claude Haiku 5.5 siêu nhanh, siêu tiết kiệm ($0.10/$0.50 per 1M) với 1M context.",
    ),
    _model(
        "claude",
        "claude-sonnet-5-5",
        "Anthropic Claude Sonnet 5.5 (Balanced Default)",
        1_000_000,
        128_000,
        2.00,
        0.20,
        10.00,
        notes_vi="Claude Sonnet 5.5 tối ưu Agentic & coding với 1M context.",
    ),
    _model(
        "claude",
        "claude-opus-5-5",
        "Anthropic Claude Opus 5.5",
        1_000_000,
        128_000,
        4.00,
        0.40,
        20.00,
        notes_vi="Flagship Claude Opus 5.5 chuyên sâu kiểm toán & code.",
    ),
    _model(
        "claude",
        "claude-fable-5-1",
        "Anthropic Claude Fable 5.1 (Frontier)",
        1_000_000,
        128_000,
        10.00,
        0.25,
        50.00,
        notes_vi="Claude Fable 5.1 cho bài toán Agentic dài hạn phức tạp.",
    ),
    _model(
        "claude",
        "claude-sonnet-4-6",
        "Anthropic Claude Sonnet 4.6",
        1_000_000,
        128_000,
        3.00,
        0.30,
        15.00,
        notes_vi="Claude Sonnet 4.6 tương thích rộng rãi.",
    ),
    _model(
        "claude",
        "claude-opus-4-8",
        "Anthropic Claude Opus 4.8",
        1_000_000,
        128_000,
        15.00,
        1.50,
        75.00,
        notes_vi="Claude Opus 4.8 thế hệ 4 với 1M context.",
    ),
    _model(
        "claude",
        "claude-sonnet-4-5-20250929",
        "Anthropic Claude Sonnet 4.5",
        200_000,
        64_000,
        3.00,
        0.30,
        15.00,
        notes_vi="Claude Sonnet 4.5 tối ưu Agentic.",
    ),
    _model(
        "claude",
        "claude-haiku-4-5-20251001",
        "Anthropic Claude Haiku 4.5",
        200_000,
        64_000,
        0.80,
        0.08,
        4.00,
        notes_vi="Claude Haiku 4.5 tốc độ cao.",
    ),
    _model(
        "claude",
        "claude-3-7-sonnet-latest",
        "Anthropic Claude 3.7 Sonnet",
        200_000,
        64_000,
        3.00,
        0.30,
        15.00,
        notes_vi="Claude 3.7 Sonnet hybrid reasoning.",
    ),
    _model(
        "claude",
        "claude-3-5-haiku-latest",
        "Anthropic Claude 3.5 Haiku",
        200_000,
        8_192,
        0.80,
        0.08,
        4.00,
        supports_reasoning=False,
        notes_vi="Claude 3.5 Haiku nhanh, tiết kiệm.",
    ),
    # --- DeepSeek ---
    _model(
        "deepseek",
        "deepseek-v4.1-flash",
        "DeepSeek-V4.1 Flash (Khuyến nghị Multimodal 1M)",
        1_048_576,
        393_216,
        0.15,
        0.006,
        0.60,
        is_recommended_default=True,
        notes_vi="DeepSeek-V4.1 Flash mới nhất: 1M context, chi phí cực thấp ($0.15/$0.60).",
    ),
    _model(
        "deepseek",
        "deepseek-v4-flash",
        "DeepSeek-V4 Flash",
        1_048_576,
        393_216,
        0.25,
        0.06,
        1.00,
        supports_vision=False,
        notes_vi="DeepSeek-V4 Flash tốc độ cao 1M context.",
    ),
    _model(
        "deepseek",
        "deepseek-v4-pro",
        "DeepSeek-V4 Pro (Frontier Reasoning)",
        1_048_576,
        393_216,
        1.32,
        0.044,
        3.96,
        supports_vision=False,
        notes_vi="DeepSeek-V4 Pro suy luận chuyên sâu 1M context.",
    ),
    _model(
        "deepseek",
        "deepseek-v4-flash-vision-exp",
        "DeepSeek-V4 Flash Vision",
        1_048_576,
        393_216,
        0.30,
        0.075,
        1.20,
        notes_vi="DeepSeek-V4 hỗ trợ Vision đa phương thức.",
    ),
    _model(
        "deepseek",
        "deepseek-chat",
        "DeepSeek-V3 Chat",
        128_000,
        8_192,
        0.27,
        0.07,
        1.10,
        supports_reasoning=False,
        supports_vision=False,
        notes_vi="DeepSeek-V3 Chat ổn định, chi phí thấp.",
    ),
    _model(
        "deepseek",
        "deepseek-reasoner",
        "DeepSeek-R1 Reasoner",
        128_000,
        8_192,
        0.55,
        0.14,
        2.19,
        supports_vision=False,
        notes_vi="DeepSeek-R1 suy luận chuỗi chuyên sâu.",
    ),
    # --- xAI Grok ---
    _model(
        "xai",
        "grok-4.7",
        "xAI Grok 4.7 (Khuyến nghị Flagship)",
        500_000,
        131_072,
        2.00,
        0.50,
        6.00,
        is_recommended_default=True,
        notes_vi="Flagship Grok 4.7 (500K context) cho coding & agentic.",
    ),
    _model(
        "xai",
        "grok-4.6",
        "xAI Grok 4.6",
        500_000,
        131_072,
        2.00,
        0.50,
        6.00,
        notes_vi="Grok 4.6 ổn định cho Agentic.",
    ),
    _model(
        "xai",
        "grok-4.3",
        "xAI Grok 4.3 (1M Balanced)",
        1_000_000,
        131_072,
        1.25,
        0.20,
        2.50,
        notes_vi="Grok 4.3 hỗ trợ 1M context chi phí tối ưu.",
    ),
    _model(
        "xai",
        "grok-4.20",
        "xAI Grok 4.20 (2M Multi-Agent)",
        2_000_000,
        131_072,
        1.25,
        0.20,
        2.50,
        notes_vi="Grok 4.20 với 2M context cho mô phỏng đa tác tử.",
    ),
    _model(
        "xai",
        "grok-build-0.1",
        "xAI Grok Build 0.1",
        256_000,
        65_536,
        1.00,
        0.20,
        2.00,
        supports_reasoning=False,
        supports_vision=False,
        notes_vi="Grok Build 0.1 cho tác vụ tần suất cao.",
    ),
    # --- Alibaba Qwen ---
    _model(
        "qwen",
        "qwen3.8-omni-flash",
        "Alibaba Qwen3.8-Omni-Flash (Khuyến nghị Siêu Tiết Kiệm)",
        1_000_000,
        131_072,
        0.15,
        0.016,
        0.47,
        is_recommended_default=True,
        notes_vi="Qwen3.8-Omni-Flash tốc độ cao, chi phí cực thấp ($0.15/$0.47).",
    ),
    _model(
        "qwen",
        "qwen3.7-plus",
        "Alibaba Qwen3.7-Plus",
        1_000_000,
        131_072,
        0.32,
        0.064,
        1.28,
        notes_vi="Cân bằng hoàn hảo chi phí & độ chính xác 1M context.",
    ),
    _model(
        "qwen",
        "qwen3.8-max",
        "Alibaba Qwen3.8-Max (Flagship 1M)",
        1_000_000,
        131_072,
        2.00,
        0.25,
        6.00,
        notes_vi="Flagship Qwen3.8-Max 1M context.",
    ),
    _model(
        "qwen",
        "qwen3.8-max-prime",
        "Alibaba Qwen3.8-Max Prime",
        1_000_000,
        131_072,
        4.00,
        0.50,
        12.00,
        notes_vi="Qwen3.8-Max Prime cho suy luận phức tạp.",
    ),
    _model(
        "qwen",
        "qwen-plus",
        "Alibaba Qwen Plus",
        131_072,
        8_192,
        0.40,
        0.10,
        1.20,
        notes_vi="Qwen Plus ổn định.",
    ),
    _model(
        "qwen",
        "qwen-turbo",
        "Alibaba Qwen Turbo",
        1_000_000,
        8_192,
        0.05,
        0.0125,
        0.20,
        supports_reasoning=False,
        notes_vi="Qwen Turbo siêu nhanh.",
    ),
    _model(
        "qwen",
        "qwen-max",
        "Alibaba Qwen Max",
        32_768,
        8_192,
        1.60,
        0.40,
        6.40,
        notes_vi="Qwen Max cổ điển.",
    ),
    # --- Mistral ---
    _model(
        "mistral",
        "mistral-small-4-0",
        "Mistral Small 4 (Khuyến nghị High-Efficiency)",
        262_144,
        65_536,
        0.15,
        0.015,
        0.60,
        supports_reasoning=False,
        is_recommended_default=True,
        notes_vi="Mistral Small 4 siêu nhẹ, chi phí thấp ($0.15/$0.60).",
    ),
    _model(
        "mistral",
        "mistral-large-4-0",
        "Mistral Large 4 (Flagship 1M)",
        1_048_576,
        262_144,
        0.70,
        0.07,
        2.10,
        notes_vi="Flagship Mistral Large 4 (1M context, 262K output).",
    ),
    _model(
        "mistral",
        "mistral-medium-3-5",
        "Mistral Medium 3.5",
        262_144,
        131_072,
        1.50,
        0.15,
        7.50,
        notes_vi="Mistral Medium 3.5 cho doanh nghiệp và Agentic.",
    ),
    _model(
        "mistral",
        "codestral-latest",
        "Mistral Codestral",
        256_000,
        65_536,
        0.30,
        0.03,
        0.90,
        supports_reasoning=False,
        supports_vision=False,
        notes_vi="Codestral chuyên sinh mã nguồn.",
    ),
    # --- OpenAI-Compatible (OpenRouter / LiteLLM / Proxy) ---
    _model(
        "openai_compatible",
        "openai/gpt-6-luna",
        "OpenRouter: OpenAI GPT-6 Luna (Khuyến nghị)",
        1_050_000,
        128_000,
        0.10,
        0.01,
        0.50,
        is_recommended_default=True,
        notes_vi="Định tuyến OpenRouter/LiteLLM tới OpenAI GPT-6 Luna.",
    ),
    _model(
        "openai_compatible",
        "openai/gpt-6.1-sol",
        "OpenRouter: OpenAI GPT-6.1 Sol",
        1_050_000,
        128_000,
        2.00,
        0.10,
        10.00,
        notes_vi="Định tuyến qua OpenRouter tới GPT-6.1 Sol.",
    ),
    _model(
        "openai_compatible",
        "google/gemini-3.8-flash",
        "OpenRouter: Google Gemini 3.8 Flash",
        1_048_576,
        65_536,
        0.75,
        0.075,
        3.75,
        notes_vi="Định tuyến qua OpenRouter tới Gemini 3.8 Flash.",
    ),
    _model(
        "openai_compatible",
        "anthropic/claude-haiku-5-5",
        "OpenRouter: Anthropic Claude Haiku 5.5",
        1_000_000,
        128_000,
        0.10,
        0.01,
        0.50,
        notes_vi="Định tuyến qua OpenRouter tới Claude Haiku 5.5.",
    ),
    _model(
        "openai_compatible",
        "deepseek/deepseek-v4.1-flash",
        "OpenRouter: DeepSeek V4.1 Flash",
        1_048_576,
        393_216,
        0.15,
        0.006,
        0.60,
        notes_vi="Định tuyến qua OpenRouter tới DeepSeek V4.1 Flash.",
    ),
    _model(
        "openai_compatible",
        "meta/muse-spark-1.3",
        "OpenRouter: Meta Muse Spark 1.3",
        1_048_576,
        131_072,
        1.25,
        0.15,
        4.25,
        notes_vi="Meta Muse Spark 1.3 (1M context) qua OpenRouter.",
    ),
    _model(
        "openai_compatible",
        "meta/muse-wonder",
        "OpenRouter: Meta Muse Wonder",
        1_048_576,
        131_072,
        4.00,
        0.20,
        20.00,
        notes_vi="Flagship Meta Muse Wonder qua OpenRouter.",
    ),
    # --- ZhipuAI ---
    _model(
        "zhipuai",
        "glm-4-flash",
        "ZhipuAI GLM-4-Flash (Khuyến nghị)",
        128_000,
        16_384,
        0.01,
        0.002,
        0.05,
        supports_reasoning=False,
        is_recommended_default=True,
        notes_vi="GLM-4-Flash tốc độ cao, chi phí cực thấp.",
    ),
    _model(
        "zhipuai",
        "glm-4-air",
        "ZhipuAI GLM-4-Air",
        128_000,
        16_384,
        0.14,
        0.035,
        0.14,
        supports_reasoning=False,
        notes_vi="GLM-4-Air cân bằng hiệu năng.",
    ),
    _model(
        "zhipuai",
        "glm-4-plus",
        "ZhipuAI GLM-4-Plus",
        128_000,
        16_384,
        0.70,
        0.175,
        0.70,
        notes_vi="GLM-4-Plus chất lượng cao.",
    ),
    # --- SiliconFlow ---
    _model(
        "siliconflow",
        "deepseek-ai/DeepSeek-V3",
        "SiliconFlow: DeepSeek-V3 (Khuyến nghị)",
        128_000,
        8_192,
        0.27,
        0.07,
        1.10,
        supports_reasoning=False,
        supports_vision=False,
        is_recommended_default=True,
        notes_vi="DeepSeek-V3 trên SiliconFlow.",
    ),
    _model(
        "siliconflow",
        "Pro/deepseek-ai/DeepSeek-V3",
        "SiliconFlow: Pro/DeepSeek-V3",
        128_000,
        8_192,
        0.27,
        0.07,
        1.10,
        supports_reasoning=False,
        supports_vision=False,
        notes_vi="Bản Pro băng thông cao trên SiliconFlow.",
    ),
    _model(
        "siliconflow",
        "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B",
        "SiliconFlow: DeepSeek-R1-Distill-Qwen-32B",
        65_536,
        8_192,
        0.18,
        0.045,
        0.18,
        supports_vision=False,
        notes_vi="DeepSeek R1 Distill 32B.",
    ),
    _model(
        "siliconflow",
        "Qwen/QwQ-32B",
        "SiliconFlow: Qwen/QwQ-32B",
        65_536,
        8_192,
        0.18,
        0.045,
        0.18,
        supports_vision=False,
        notes_vi="Qwen QwQ 32B reasoning.",
    ),
]


def _build_rates_map() -> dict[str, tuple[float, float, float]]:
    rates: dict[str, tuple[float, float, float]] = {}
    for entry in VERIFIED_MODEL_CATALOG:
        key = str(entry["model_id"]).strip().lower()
        rates[key] = (
            float(entry["input_usd_per_1m"]) * 1e-6,
            float(entry["cached_input_usd_per_1m"]) * 1e-6,
            float(entry["output_usd_per_1m"]) * 1e-6,
        )
    return rates


MODEL_RATES_USD_PER_TOKEN: dict[str, tuple[float, float, float]] = _build_rates_map()
_SORTED_RATE_KEYS: tuple[str, ...] = tuple(
    sorted(MODEL_RATES_USD_PER_TOKEN.keys(), key=len, reverse=True)
)


def resolve_model_rates_usd(model_name: str | None) -> tuple[float, float, float]:
    """Tra cứu đơn giá USD mỗi token ``(input, cached_input, output)`` theo tên mô hình.

    Khớp chính xác trước (kể cả sau khi tách tiền tố ``provider/``), sau đó mới tìm
    chuỗi con theo thứ tự **độ dài khóa giảm dần** để ``gpt-5.4-mini`` không bao giờ
    khớp nhầm vào ``gpt-5.4`` hay ``gpt-5``.
    """
    clean = str(model_name or "").strip().lower()
    if clean in MODEL_RATES_USD_PER_TOKEN:
        return MODEL_RATES_USD_PER_TOKEN[clean]
    if "/" in clean:
        tail = clean.rsplit("/", 1)[-1]
        if tail in MODEL_RATES_USD_PER_TOKEN:
            return MODEL_RATES_USD_PER_TOKEN[tail]
    for key in _SORTED_RATE_KEYS:
        if key in clean:
            return MODEL_RATES_USD_PER_TOKEN[key]
    return MODEL_RATES_USD_PER_TOKEN["gpt-5.4-mini"]


def get_model_pricing_per_1m(model_name: str | None) -> dict[str, float]:
    """Trả về đơn giá quy đổi USD / 1M tokens cho UI."""
    in_r, cache_r, out_r = resolve_model_rates_usd(model_name)
    return {
        "input_usd_per_1m": round(in_r * 1_000_000, 4),
        "cached_input_usd_per_1m": round(cache_r * 1_000_000, 4),
        "output_usd_per_1m": round(out_r * 1_000_000, 4),
    }


def resolve_provider_api_type(
    provider: str | None,
    explicit_api_type: str | None = None,
) -> str:
    """Chuẩn hóa giao thức LiteLLM (``openai`` hoặc ``anthropic``)."""
    explicit = str(explicit_api_type or "").strip().lower()
    if explicit in {"openai", "anthropic"}:
        return explicit
    prov = str(provider or "").strip().lower()
    if prov in {"claude", "anthropic"}:
        return "anthropic"
    return "openai"


def resolve_provider_base_url(
    provider: str | None,
    explicit_base_url: str | None = None,
) -> str:
    """Chuẩn hóa Base URL theo từng nhà cung cấp.

    Với ``gemini``, nếu người dùng nhập URL gốc ``.../v1beta`` (theo thói quen từ EvidenceAtlas)
    thì tự bổ sung ``/openai`` để LiteLLM gọi qua OpenAI-compatible endpoint của Google AI Studio.
    """
    prov = str(provider or DEFAULT_LLM_PROVIDER).strip().lower()
    raw = str(explicit_base_url or "").strip().rstrip("/")
    if not raw:
        preset = AI_PROVIDER_PRESETS.get(prov) or AI_PROVIDER_PRESETS[DEFAULT_LLM_PROVIDER]
        return str(preset["default_base_url"])
    if prov == "gemini" and re.search(r"/v1beta$", raw, flags=re.IGNORECASE):
        return f"{raw}/openai"
    return raw


def normalize_thinking_config(
    thinking: str | None,
    reasoning_effort: str | None = None,
) -> tuple[str, str | None]:
    """Chuẩn hóa cấu hình ``(thinking, reasoning_effort)``.

    Mặc định ưu tiên ``("off", "none")`` nếu không truyền hoặc rỗng.
    """
    raw_t = str(thinking or "").strip().lower()
    if not raw_t or raw_t in {"off", "0", "false", "no", "disable", "disabled"}:
        return "off", "none"
    if raw_t in {"on", "1", "true", "yes", "enable", "enabled"}:
        raw_e = str(reasoning_effort or "").strip().lower()
        effort = (
            raw_e
            if raw_e in {"minimal", "low", "medium", "high", "xhigh"}
            else DEFAULT_REASONING_EFFORT_WHEN_ON
        )
        return "on", effort
    if raw_t == "inherit":
        return "inherit", None
    return "off", "none"


_OBSOLETE_OR_NONCHAT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^gpt-3\.5", re.I),
    re.compile(r"^text-davinci", re.I),
    re.compile(r"^code-davinci", re.I),
    re.compile(r"^babbage", re.I),
    re.compile(r"^ada(?:-|$)", re.I),
    re.compile(r"^curie", re.I),
    re.compile(r"^davinci", re.I),
    re.compile(r"embed|embedding", re.I),
    re.compile(r"^gpt-4-(?:0314|0613|32k|vision-preview|1106-preview|0125-preview)", re.I),
    re.compile(r"^claude-(?:1|2|instant)", re.I),
    re.compile(r"^gemini-1\.0|^gemini-pro(?:-vision)?$", re.I),
    re.compile(r"^(?:chat|text)-bison|^aqa$", re.I),
    re.compile(r"^whisper|^tts-|^dall-e|^omni-moderation|^text-moderation", re.I),
    re.compile(r"(?:^|-)(?:audio|realtime|transcribe|sora|image)(?:-|$)", re.I),
)


def is_obsolete_model_id(model_id: str | None) -> bool:
    """Lọc bỏ các mô hình lỗi thời hoặc không dùng cho hội thoại/tác tử."""
    clean = str(model_id or "").strip()
    if not clean:
        return True
    return any(rx.search(clean) for rx in _OBSOLETE_OR_NONCHAT_PATTERNS)


def find_catalog_model(model_id: str | None, provider: str | None = None) -> dict[str, Any] | None:
    """Tìm entry metadata của mô hình trong danh mục đã xác minh."""
    clean = str(model_id or "").strip().lower()
    if not clean:
        return None
    prov = str(provider or "").strip().lower()
    if prov:
        for entry in VERIFIED_MODEL_CATALOG:
            if entry["provider"] == prov and entry["model_id"].lower() == clean:
                return entry
    for entry in VERIFIED_MODEL_CATALOG:
        if entry["model_id"].lower() == clean:
            return entry
    return None


def get_llm_catalog_payload() -> dict[str, Any]:
    """Xuất payload danh mục nhà cung cấp, mô hình và mặc định cho API ``/api/llm-catalog``."""
    return {
        "defaults": {
            "provider": DEFAULT_LLM_PROVIDER,
            "model": DEFAULT_LLM_MODEL,
            "thinking": DEFAULT_LLM_THINKING,
            "reasoning_effort": "none",
            "reasoning_effort_when_on": DEFAULT_REASONING_EFFORT_WHEN_ON,
        },
        "providers": list(AI_PROVIDER_PRESETS.values()),
        "models": list(VERIFIED_MODEL_CATALOG),
        "reasoning_efforts": ["minimal", "low", "medium", "high", "xhigh"],
    }
