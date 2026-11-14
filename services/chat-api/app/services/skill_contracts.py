from __future__ import annotations

import datetime
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import uuid

import yaml
from pydantic import BaseModel, Field, ValidationError

from app.core.db import get_db
from app.services.skill_assets.publish_channels import publish_channel_registry
from app.services.skill_assets.composite_task import parse_composite_skill
from app.services.llm import llm_service
from app.services.org_skill_adapter import _workflow_markdown, _workflow_nodes
from app.services.style_skill_locale import source_style_language, style_body_language_instruction, style_description_fallback
from app.utils.oss_uploader import AliyunOSSUploader


logger = logging.getLogger(__name__)


@dataclass
class UserSkill:
    id: str
    user_id: str
    main_id: str
    name: str
    description: str
    summary: str
    category: str
    role: str
    skill_type: str
    tags: List[str]
    visibility: str
    formats: List[str]
    input_profile: Dict[str, Any]
    contract_json: Dict[str, Any]
    skill_markdown: str
    skill_object_path: str
    sources: List[Dict[str, Any]]
    resources: Dict[str, List[Dict[str, Any]]]
    advanced: Dict[str, Any]
    notes: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    is_active: bool = True


class SkillContractModel(BaseModel):
    skill_type: str = "style"
    name: str = Field(default="", min_length=1, max_length=120)
    summary: str = Field(default="", max_length=500)
    applicable_scenarios: str = Field(default="", max_length=1500)
    publish_channel: List[str] = Field(default_factory=list)
    content_form: List[str] = Field(default_factory=list)
    target_audience: List[str] = Field(default_factory=list)
    preferred_style: List[str] = Field(default_factory=list)
    target_length: Dict[str, Any] = Field(default_factory=dict)
    section_structure: List[Dict[str, Any]] = Field(default_factory=list)
    required_sections: List[str] = Field(default_factory=list)
    required_elements: List[str] = Field(default_factory=list)
    forbidden_elements: List[str] = Field(default_factory=list)
    reference_materials: List[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=4000)


def _split_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith("---"):
        return {}, content
    parts = content.split("\n")
    end_idx = None
    for i in range(1, len(parts)):
        if parts[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return {}, content
    front = "\n".join(parts[1:end_idx])
    body = "\n".join(parts[end_idx + 1 :]).lstrip()
    try:
        meta = yaml.safe_load(front) or {}
    except Exception:
        meta = {}
    return meta, body


def _slugify(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9\-]+", "-", name)
    name = re.sub(r"-{2,}", "-", name)
    name = name.strip("-")
    return name[:64] if len(name) > 64 else name


def _normalize_skill_role(role: Optional[str]) -> str:
    raw = str(role or "").strip().lower()
    aliases = {
        "compose": "execution",
        "writer": "execution",
        "write": "execution",
        "execute": "execution",
        "execution": "execution",
        "renderer": "renderer",
        "render": "renderer",
        "style": "style",
        "guideline": "style",
        "policy": "style",
    }
    return aliases.get(raw, "")


def _normalize_skill_type(skill_type: Optional[str], *, role: Optional[str] = None) -> str:
    raw = str(skill_type or "").strip().lower()
    aliases = {
        "style": "style",
        "writing_style": "style",
        "guideline": "style",
        "policy": "style",
        "execution": "execution",
        "execute": "execution",
        "compose": "execution",
        "writer": "execution",
        "renderer": "renderer",
        "render": "renderer",
        # A composite_task skill describes an ordered list of natural-language
        # steps (optionally per-step site context) that the planner expands
        # into subtasks. See UserSkillResolver.expand_composite_skill.
        "composite_task": "composite_task",
        "composite": "composite_task",
        "browser_task": "composite_task",
        "workflow": "composite_task",
        "ordinary": "execution",
        "expert_package": "expert_package",
    }
    normalized = aliases.get(raw, "")
    if normalized:
        return normalized
    normalized_role = _normalize_skill_role(role)
    if normalized_role in {"style", "execution", "renderer", "composite_task"}:
        return normalized_role
    return "style"


def _as_string_list(values: Any) -> List[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    out: List[str] = []
    seen: set[str] = set()
    for item in values:
        val = str(item or "").strip()
        if not val:
            continue
        key = val.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(val)
    return out


def _normalize_token_inputs(values: Any) -> List[str]:
    if isinstance(values, list):
        parts: List[str] = []
        for item in values:
            parts.extend(_split_list_tokens(str(item or "")))
        return _as_string_list(parts)
    return _split_list_tokens(str(values or ""))


def _normalize_target_length(value: Any) -> Dict[str, Any]:
    raw = dict(value or {}) if isinstance(value, dict) else {}

    def _coerce_int(v: Any) -> int:
        try:
            return max(0, int(float(str(v or "").strip())))
        except Exception:
            return 0

    min_value = _coerce_int(raw.get("min") or raw.get("min_words") or raw.get("minWords"))
    max_value = _coerce_int(raw.get("max") or raw.get("max_words") or raw.get("maxWords"))
    unit = str(raw.get("unit") or raw.get("length_unit") or "chinese_chars").strip() or "chinese_chars"
    out: Dict[str, Any] = {"unit": unit}
    if min_value > 0:
        out["min"] = min_value
    if max_value > 0:
        out["max"] = max_value
    return out


def _normalize_section_structure(value: Any, *, level: int = 1, max_depth: int = 2) -> List[Dict[str, Any]]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    for raw in value:
        if isinstance(raw, str):
            title = raw.strip()
            if not title:
                continue
            item: Dict[str, Any] = {
                "title": title,
                "level": level,
                "must_include": [],
                "avoid": [],
                "notes": "",
                "children": [],
            }
        elif isinstance(raw, dict):
            title = str(raw.get("title") or raw.get("name") or raw.get("heading") or "").strip()
            if not title:
                continue
            try:
                raw_level = max(1, int(raw.get("level") or level or 1))
            except Exception:
                raw_level = max(1, level)
            item = {
                "title": title[:200],
                "level": raw_level,
                "must_include": _normalize_token_inputs(
                    raw.get("must_include")
                    or raw.get("mustInclude")
                    or raw.get("required_elements")
                    or raw.get("requiredElements")
                )[:24],
                "avoid": _normalize_token_inputs(
                    raw.get("avoid")
                    or raw.get("must_avoid")
                    or raw.get("mustAvoid")
                    or raw.get("forbidden_elements")
                    or raw.get("forbiddenElements")
                )[:24],
                "notes": str(raw.get("notes") or raw.get("description") or "").strip()[:1000],
                "children": [],
            }
            if level < max_depth:
                item["children"] = _normalize_section_structure(raw.get("children"), level=level + 1, max_depth=max_depth)
        else:
            continue
        out.append(item)
        if len(out) >= 32:
            break
    return out


def _flatten_section_titles(nodes: Any) -> List[str]:
    raw_text = json.dumps(nodes, ensure_ascii=False)
    use_cjk = bool(re.search(r"[\u4e00-\u9fff]", raw_text))
    out: List[str] = []

    def has_marker(title: str, level: int) -> bool:
        if level <= 1:
            return bool(re.match(r"^\s*(?:[一二三四五六七八九十]+、|\d+[\.、])", title))
        return bool(re.match(r"^\s*(?:（[一二三四五六七八九十]+）|\([一二三四五六七八九十]+\)|\d+(?:\.\d+)+[\.、]?)", title))

    def cjk_number(index: int) -> str:
        numerals = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
        if 1 <= index <= 10:
            return numerals[index - 1]
        if index < 20:
            return "十" + numerals[index - 11]
        return str(index)

    unnumbered_titles = {"开头总述", "引言", "导语", "摘要", "结语", "附录", "Introduction", "Executive Summary", "Summary"}

    def is_unnumbered(title: str) -> bool:
        return title in unnumbered_titles

    def render_title(title: str, level: int, index: int, parent_path: List[int]) -> str:
        if has_marker(title, level) or is_unnumbered(title):
            return title
        if use_cjk:
            return f"{cjk_number(index)}、{title}" if level <= 1 else f"（{cjk_number(index)}）{title}"
        if level <= 1:
            return f"{index}. {title}"
        return f"{'.'.join(str(x) for x in [*parent_path, index])} {title}"

    def walk(items: Any, level: int = 1, parent_path: List[int] | None = None) -> None:
        if not isinstance(items, list):
            return
        path = list(parent_path or [])
        numbered_index = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if title:
                if not is_unnumbered(title):
                    numbered_index += 1
                display_index = numbered_index if numbered_index > 0 else 1
                out.append(render_title(title, level, display_index, path))
            walk(item.get("children"), level + 1, [*path, display_index if title else numbered_index])

    walk(nodes)
    return _as_string_list(out)


def _render_section_structure_lines(nodes: Any, *, level: int = 1) -> List[str]:
    lines: List[str] = []
    if not isinstance(nodes, list):
        return lines
    indent = "  " * max(0, level - 1)
    for node in nodes:
        if not isinstance(node, dict):
            continue
        title = str(node.get("title") or "").strip()
        if not title:
            continue
        lines.append(f"{indent}- {title}")
        must_include = _as_string_list(node.get("must_include"))
        avoid = _as_string_list(node.get("avoid"))
        notes = str(node.get("notes") or "").strip()
        if must_include:
            lines.append(f"{indent}  - Must include: {'; '.join(must_include)}")
        if avoid:
            lines.append(f"{indent}  - Must avoid: {'; '.join(avoid)}")
        if notes:
            lines.append(f"{indent}  - Notes: {notes}")
        lines.extend(_render_section_structure_lines(node.get("children"), level=level + 1))
    return lines


def _normalize_contract_json(
    contract_json: Optional[Dict[str, Any]],
    *,
    skill_type: str,
    name: str,
    description: str,
    summary: str,
    notes: str,
) -> Dict[str, Any]:
    raw = dict(contract_json or {})
    section_structure = _normalize_section_structure(raw.get("section_structure") or raw.get("sectionStructure"))
    required_sections = _normalize_token_inputs(raw.get("required_sections"))
    if section_structure:
        required_sections = _flatten_section_titles(section_structure)
    normalized = {
        "skill_type": _normalize_skill_type(raw.get("skill_type"), role=skill_type) or skill_type,
        "name": str(raw.get("name") or name or "").strip(),
        "summary": str(raw.get("summary") or summary or description or "").strip(),
        "applicable_scenarios": str(raw.get("applicable_scenarios") or "").strip(),
        "publish_channel": _normalize_token_inputs(raw.get("publish_channel")),
        "content_form": _normalize_token_inputs(raw.get("content_form")),
        "target_audience": _normalize_token_inputs(raw.get("target_audience")),
        "preferred_style": _normalize_token_inputs(raw.get("preferred_style")),
        "target_length": _normalize_target_length(raw.get("target_length") or raw.get("targetLength")),
        "section_structure": section_structure,
        "required_sections": required_sections,
        "required_elements": _normalize_token_inputs(raw.get("required_elements")),
        "forbidden_elements": _normalize_token_inputs(raw.get("forbidden_elements")),
        "reference_materials": _as_string_list(raw.get("reference_materials")),
        "notes": str(raw.get("notes") or notes or "").strip(),
    }
    try:
        validated = SkillContractModel.model_validate(normalized)
        return validated.model_dump()
    except ValidationError:
        normalized["name"] = (normalized.get("name") or name or "Untitled Skill")[:120]
        normalized["summary"] = str(normalized.get("summary") or "")[:500]
        normalized["applicable_scenarios"] = str(normalized.get("applicable_scenarios") or "")[:1500]
        normalized["notes"] = str(normalized.get("notes") or "")[:4000]
        validated = SkillContractModel.model_validate(normalized)
        return validated.model_dump()


def _contract_json_from_markdown(
    skill_markdown: str,
    *,
    skill_type: str,
    name: str,
    description: str,
    summary: str,
    notes: str,
) -> Dict[str, Any]:
    meta, body = _split_frontmatter(skill_markdown or "")
    return _normalize_contract_json(
        {
            "skill_type": meta.get("skill_type") or skill_type,
            "name": meta.get("name") or name,
            "summary": meta.get("summary") or summary or description,
            "applicable_scenarios": meta.get("applicable_scenarios") or meta.get("when_to_use") or "",
            "publish_channel": meta.get("publish_channel") or [],
            "content_form": meta.get("content_form") or [],
            "target_audience": meta.get("target_audience") or [],
            "preferred_style": meta.get("preferred_style") or meta.get("tone") or [],
            "target_length": meta.get("target_length") or meta.get("targetLength") or {},
            "section_structure": meta.get("section_structure") or meta.get("sectionStructure") or [],
            "required_sections": meta.get("required_sections") or [],
            "required_elements": meta.get("required_elements") or [],
            "forbidden_elements": meta.get("forbidden_elements") or [],
            "reference_materials": meta.get("reference_materials") or [],
            "notes": notes or body,
        },
        skill_type=skill_type,
        name=name,
        description=description,
        summary=summary,
        notes=notes,
    )


def _heuristic_enrich_contract(contract_json: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(contract_json or {})
    text = " ".join(
        [
            str(out.get("name") or ""),
            str(out.get("summary") or ""),
            str(out.get("applicable_scenarios") or ""),
            str(out.get("notes") or ""),
        ]
    ).lower()

    channels = publish_channel_registry.canonicalize_many(_as_string_list(out.get("publish_channel")))
    if channels == ["generic"] or not channels:
        detected = publish_channel_registry.detect_from_text(text, default="")
        if detected:
            channels = [detected]
    out["publish_channel"] = channels or ["generic"]

    forms = _as_string_list(out.get("content_form"))
    if not forms:
        forms = ["article"]
    out["content_form"] = forms

    styles = _as_string_list(out.get("preferred_style"))
    if not styles:
        styles = ["professional"]
    for channel in out["publish_channel"]:
        for hint in publish_channel_registry.style_hints_for(channel):
            if hint not in styles:
                styles.append(hint)
    out["preferred_style"] = styles[:6]

    audience = _as_string_list(out.get("target_audience"))
    out["target_audience"] = audience or ["general_public"]

    required = _as_string_list(out.get("required_elements"))
    if not required:
        for channel in out["publish_channel"]:
            required.extend(publish_channel_registry.required_elements_for(channel))
        required = _as_string_list(required)
    out["required_elements"] = required[:12]

    forbidden = _as_string_list(out.get("forbidden_elements"))
    if not forbidden:
        for channel in out["publish_channel"]:
            forbidden.extend(publish_channel_registry.forbidden_elements_for(channel))
        forbidden = _as_string_list(forbidden)
    out["forbidden_elements"] = forbidden[:12]

    if not str(out.get("applicable_scenarios") or "").strip():
        for channel in out["publish_channel"]:
            default_scenarios = publish_channel_registry.applicable_scenarios_for(channel)
            if default_scenarios:
                out["applicable_scenarios"] = default_scenarios
                break
        if not str(out.get("applicable_scenarios") or "").strip():
            out["applicable_scenarios"] = "Use this skill in the intended target scenarios."
    return out


def _render_skill_markdown_from_contract(
    contract_json: Dict[str, Any],
    *,
    name: str,
    description: str,
) -> str:
    contract = _normalize_contract_json(
        contract_json,
        skill_type=str(contract_json.get("skill_type") or "style"),
        name=name,
        description=description,
        summary=str(contract_json.get("summary") or description or ""),
        notes=str(contract_json.get("notes") or ""),
    )
    frontmatter = {
        "skill_id": _slugify(contract.get("name") or name or "user-skill") or "user-skill",
        "name": contract.get("name") or name or "Untitled Skill",
        "description": description or contract.get("summary") or "",
        "skill_type": contract.get("skill_type") or "style",
        "summary": contract.get("summary") or "",
        "applicable_scenarios": contract.get("applicable_scenarios") or "",
        "publish_channel": contract.get("publish_channel") or [],
        "content_form": contract.get("content_form") or [],
        "target_audience": contract.get("target_audience") or [],
        "preferred_style": contract.get("preferred_style") or [],
        "target_length": contract.get("target_length") or {},
        "section_structure": contract.get("section_structure") or [],
        "required_sections": contract.get("required_sections") or [],
        "required_elements": contract.get("required_elements") or [],
        "forbidden_elements": contract.get("forbidden_elements") or [],
        "reference_materials": contract.get("reference_materials") or [],
    }
    body_sections = [
        ("Purpose", contract.get("summary") or description or "User-defined skill contract."),
        ("When To Use", contract.get("applicable_scenarios") or "Use this skill in the intended target scenarios."),
        (
            "Section Structure",
            "\n".join(_render_section_structure_lines(contract.get("section_structure") or [])) or "- ",
        ),
        ("Required Sections", "\n".join(f"- {item}" for item in (contract.get("required_sections") or [])) or "- "),
        ("Must Include", "\n".join(f"- {item}" for item in (contract.get("required_elements") or [])) or "- "),
        ("Must Avoid", "\n".join(f"- {item}" for item in (contract.get("forbidden_elements") or [])) or "- "),
        (
            "Style Notes",
            "\n".join(
                [
                    f"- Target audience: {', '.join(contract.get('target_audience') or []) or 'general'}",
                    f"- Preferred style: {', '.join(contract.get('preferred_style') or []) or 'professional'}",
                    f"- Publish channel: {', '.join(contract.get('publish_channel') or []) or 'generic'}",
                    f"- Content form: {', '.join(contract.get('content_form') or []) or 'article'}",
                ]
            ),
        ),
        ("Additional Notes", contract.get("notes") or "- "),
    ]
    fm = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    body = "\n\n".join(f"# {title}\n\n{content}".strip() for title, content in body_sections)
    return f"---\n{fm}\n---\n\n{body}\n"


def _has_executable_workflow_steps(skill_markdown: str) -> bool:
    parsed = parse_composite_skill(str(skill_markdown or ""))
    for step in list(parsed.get("steps") or []):
        if isinstance(step, dict) and "." in str(step.get("kind") or ""):
            return True
    return False


def _workflow_markdown_from_config(
    *,
    config: Dict[str, Any],
    name: str,
    description: str,
    scenario: str,
    type_value: Any = "",
    skill_type_value: Any = "",
    current_markdown: str = "",
) -> str:
    markdown = str(current_markdown or "").strip()
    raw_type = str(type_value or "").strip().lower()
    raw_skill_type = str(skill_type_value or "").strip().lower()
    nodes = _workflow_nodes(config if isinstance(config, dict) else {})
    is_workflow = raw_type == "workflow" or raw_skill_type in {"workflow", "composite_task"} or bool(nodes)
    if not is_workflow or _has_executable_workflow_steps(markdown):
        return markdown
    if not nodes:
        return markdown
    steps = [
        str(node.get("description") or "").strip()
        for node in nodes
        if str(node.get("description") or "").strip()
    ]
    return _workflow_markdown(
        name=name,
        description=description,
        scenario=scenario,
        steps=steps,
        nodes=nodes,
    )


def _infer_role_from_fields(
    *,
    category: str,
    name: str,
    description: str,
    skill_markdown: str,
    formats: Optional[List[str]] = None,
) -> str:
    normalized_formats = {str(item or "").strip().lower() for item in list(formats or []) if str(item or "").strip()}
    if normalized_formats.intersection({"docx", "pdf", "ppt", "pptx"}):
        return "renderer"
    normalized_category = str(category or "").strip().lower()
    if normalized_category in {"style", "guideline", "writing_style"}:
        return "style"
    return "execution"


def _split_list_tokens(text: str) -> List[str]:
    if not text:
        return []
    normalized = re.sub(r"[；;|/]+", ",", text)
    parts = [p.strip(" -\t\r\n") for p in re.split(r"[,，]+", normalized) if p.strip(" -\t\r\n")]
    dedup: List[str] = []
    seen: set[str] = set()
    for p in parts:
        low = p.lower()
        if low in seen:
            continue
        seen.add(low)
        dedup.append(p)
    return dedup


def _canonical_block_token(token: str) -> str:
    t = str(token or "").strip().lower()
    if not t:
        return ""
    t = re.sub(r"[\s\-]+", "_", t)
    mapping = {
        "feature_list": "feature_list",
        "feature": "feature_list",
        "code_block": "code_block",
        "code": "code_block",
        "use_case_block": "use_case_block",
        "use_case": "use_case_block",
        "usecase": "use_case_block",
        "conclusion": "conclusion_paragraph",
        "conclusion_paragraph": "conclusion_paragraph",
        "comparison": "comparison_block",
        "comparison_block": "comparison_block",
        "flow": "flow_block",
        "flow_block": "flow_block",
        "architecture": "architecture_block",
        "architecture_block": "architecture_block",
        "metric": "metric_block",
        "metric_block": "metric_block",
        "numbered_heading": "numbered_heading",
        "user_story": "user_story",
        "state_description": "state_description",
        "requirement_description": "requirement_description",
        "precondition_block": "precondition_block",
    }
    return mapping.get(t, "")


def _compile_skill_contract(
    *,
    name: str,
    description: str,
    category: str,
    formats: Optional[List[str]],
    skill_markdown: str,
    skill_type: str = "",
    contract_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    meta, body = _split_frontmatter(skill_markdown or "")
    raw_text = " ".join([str(meta or ""), str(body or ""), str(description or ""), str(category or "")]).lower()
    lines = [ln.strip() for ln in (body or "").splitlines()]

    required_blocks: List[str] = []
    forbidden_blocks: List[str] = []
    lint_warnings: List[str] = []

    required_patterns = [
        r"(always include|must include|必须包含|必须包括)[:：]\s*(.+)$",
        r"(if .* enabled.*must include)[:：]?\s*(.+)$",
    ]
    forbidden_patterns = [
        r"(never include|must not include|do not include|禁止|不得包含)[:：]\s*(.+)$",
    ]
    for ln in lines:
        low = ln.lower()
        for pat in required_patterns:
            m = re.search(pat, low)
            if m:
                required_blocks.extend(_split_list_tokens(m.group(2)))
        for pat in forbidden_patterns:
            m = re.search(pat, low)
            if m:
                forbidden_blocks.extend(_split_list_tokens(m.group(2)))

    marker_to_block = {
        "[comparison]": "comparison_block",
        "[flow]": "flow_block",
        "[architecture]": "architecture_block",
        "[metric]": "metric_block",
        "feature list": "feature_list",
        "code block": "code_block",
        "use case": "use_case_block",
        "conclusion": "conclusion_paragraph",
    }
    for marker, blk in marker_to_block.items():
        if marker in raw_text:
            required_blocks.append(blk)

    canonical_required: List[str] = []
    for raw in required_blocks:
        c = _canonical_block_token(raw)
        if c and c not in canonical_required:
            canonical_required.append(c)
    canonical_forbidden: List[str] = []
    for raw in forbidden_blocks:
        c = _canonical_block_token(raw)
        if c and c not in canonical_forbidden:
            canonical_forbidden.append(c)

    has_visual_markers = any(
        k in raw_text
        for k in [
            "infographic",
            "visual block",
            "comparison_block",
            "flow_block",
            "architecture_block",
            "metric_block",
            "[comparison]",
            "[flow]",
            "[architecture]",
            "[metric]",
        ]
    )
    image_render_enabled = any(
        k in raw_text
        for k in [
            "image_render_enabled=true",
            "generated by tool",
            "markdown image link generated by tool",
            "信息图",
            "图像生成",
            "图片生成",
        ]
    )
    required_visual_images = 0
    m = re.search(r"required_visual_images\s*=\s*(\d+)", raw_text)
    if m:
        required_visual_images = int(m.group(1))
    elif has_visual_markers:
        required_visual_images = 1

    renderer_markers = [
        "docx",
        "pdf",
        "pptx",
        "render",
        "renderer",
        "export",
    ]
    execution_markers = [
        "run external tools",
        "tool execution",
        "network access",
        "file system",
        "invoke",
        "api",
        "browser",
        "automation",
        "execute",
    ]
    graph_markers = [
        "stategraph",
        "langgraph",
        "graph recursion",
        "workflow graph",
    ]
    style_markers = [
        "purpose",
        "when to use",
        "workflow",
        "output format",
        "rules",
        "failure handling",
        "must include",
        "never include",
        "tone",
        "formatting preferences",
    ]

    renderer_score = sum(1 for m in renderer_markers if m in raw_text) + (
        2 if any(fmt in {"pdf", "docx", "pptx"} for fmt in (formats or [])) else 0
    )
    execution_score = sum(1 for m in execution_markers if m in raw_text)
    style_score = sum(1 for m in style_markers if m in raw_text)
    has_style_sections = all(k in raw_text for k in ["purpose", "workflow", "rules"]) or all(
        k in raw_text for k in ["when to use", "output format", "failure handling"]
    )

    explicit_role = _normalize_skill_role(meta.get("role"))
    if explicit_role:
        role = explicit_role
    elif renderer_score >= 3 and renderer_score > style_score + 1:
        role = "renderer"
    elif (style_score >= 4 and style_score >= execution_score) or has_style_sections:
        role = "style"
    elif execution_score >= 2:
        role = "execution"
    else:
        role = _infer_role_from_fields(
            category=category,
            name=name,
            description=description,
            skill_markdown=skill_markdown,
            formats=formats,
        )

    explicit_plane = str(meta.get("execution_plane") or "").strip().lower()
    if explicit_plane in {"runtime", "graph"}:
        execution_plane = explicit_plane
    elif any(m in raw_text for m in graph_markers):
        execution_plane = "graph"
    else:
        execution_plane = "runtime"

    if has_visual_markers and not image_render_enabled:
        lint_warnings.append("visual_blocks_detected_but_image_render_not_explicit")
    if "rules" not in raw_text:
        lint_warnings.append("missing_rules_section")
    if "workflow" not in raw_text:
        lint_warnings.append("missing_workflow_section")

    preferred_mode = "single_pass"
    if any(k in raw_text for k in ["sectional_long_report", "long report", "深度研究", "章节", "chapter-by-chapter"]):
        preferred_mode = "sectional_long_report"

    structured_contract = _normalize_contract_json(
        contract_json or _contract_json_from_markdown(
            skill_markdown,
            skill_type=skill_type or "style",
            name=name,
            description=description,
            summary="",
            notes="",
        ),
        skill_type=skill_type or role,
        name=name,
        description=description,
        summary="",
        notes="",
    )

    required_sections = _as_string_list(structured_contract.get("required_sections"))
    if required_sections:
        canonical_required = []
        for raw in required_sections:
            c = _canonical_block_token(raw)
            if c and c not in canonical_required:
                canonical_required.append(c)

    return {
        "version": "v1",
        "skill_type": _normalize_skill_type(skill_type or structured_contract.get("skill_type"), role=role),
        "role": role,
        "execution_plane": execution_plane,
        "contract_json": structured_contract,
        "structure": {
            "required_blocks": canonical_required[:24],
            "forbidden_blocks": canonical_forbidden[:24],
        },
        "visual_policy": {
            "enabled": bool(has_visual_markers),
            "required_visual_images": int(required_visual_images),
            "image_render_enabled": bool(image_render_enabled),
            "placement_mode": "inline_contextual",
        },
        "compose_profile": {
            "preferred_mode": preferred_mode,
            "human_readability_first": True,
            "anti_template_stack": True,
        },
        "signals": {
            "style_score": style_score,
            "execution_score": execution_score,
            "renderer_score": renderer_score,
        },
        "lint_warnings": lint_warnings,
    }
