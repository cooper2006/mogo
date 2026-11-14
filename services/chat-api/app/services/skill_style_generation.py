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


from app.services.skill_contracts import (
    UserSkill,
    SkillContractModel,
    _split_frontmatter,
    _slugify,
    _normalize_skill_role,
    _normalize_skill_type,
    _as_string_list,
    _normalize_token_inputs,
    _normalize_target_length,
    _normalize_section_structure,
    _flatten_section_titles,
    _render_section_structure_lines,
    _normalize_contract_json,
    _contract_json_from_markdown,
    _heuristic_enrich_contract,
    _render_skill_markdown_from_contract,
    _has_executable_workflow_steps,
    _workflow_markdown_from_config,
    _infer_role_from_fields,
    _split_list_tokens,
    _canonical_block_token,
    _compile_skill_contract,
)


class SkillStyleGenerationMixin:
    async def generate_style_skill_from_document(self, filename: str, content: bytes) -> Dict[str, Any]:
        """
        Orchestrator for the style extraction pipeline.
        Generates a role:style SKILL.md (YAML style_contract + LLM writing guidelines)
        from an uploaded document.
        """
        import re
        from app.utils.document_loader import extract_text_from_file

        extracted_text = extract_text_from_file(content, filename)
        if not extracted_text:
            raise ValueError("Could not extract text from the provided file.")

        def _normalize_text(t: str) -> str:
            t = t.replace("\r\n", "\n").replace("\r", "\n")
            t = re.sub(r"\n{3,}", "\n\n", t)
            return t.strip()

        extracted_text = _normalize_text(extracted_text)

        flavor_snippet = extracted_text[:6000]
        mid_snippet = ""
        if len(extracted_text) > 8000:
            mid_start = len(extracted_text) // 2 - 1000
            mid_snippet = extracted_text[mid_start:mid_start + 2000]
        tail_snippet = extracted_text[-2000:] if len(extracted_text) > 2000 else ""

        # Phase 1: Analyze writing style
        logger.info("style skill phase started", extra={"event": "skills.style_phase", "phase": "analyze_style"})
        style_analysis = await self._analyze_writing_style(filename, flavor_snippet, mid_snippet, tail_snippet)

        # Phase 2: Compile style SKILL.md
        logger.info("style skill phase started", extra={"event": "skills.style_phase", "phase": "compile_style", "doc_type": style_analysis.get("doc_type", "unknown")})
        skill_md = await self._compile_style_skill_md(style_analysis, flavor_snippet)

        # Phase 3: Validate and repair
        logger.info("style skill phase started", extra={"event": "skills.style_phase", "phase": "validate_style"})
        final_skill_md = await self._validate_style_skill(skill_md, style_analysis)

        # Ensure frontmatter
        final_skill_md = final_skill_md.strip()
        if final_skill_md.startswith("```"):
            final_skill_md = re.sub(r"^```\w*\n?", "", final_skill_md)
            final_skill_md = re.sub(r"\n?```$", "", final_skill_md)
            final_skill_md = final_skill_md.strip()
        if "---" in final_skill_md and not final_skill_md.startswith("---"):
            final_skill_md = final_skill_md[final_skill_md.find("---"):]

        meta, body = _split_frontmatter(final_skill_md)
        name = str(meta.get("name") or style_analysis.get("skill_name") or "user_writing_style")
        description = str(meta.get("description") or style_analysis.get("skill_description") or style_description_fallback(source_style_language(style_analysis, flavor_snippet)))

        return {
            "name": name,
            "description": description,
            "category": "style",
            "role": "style",
            "execution_plane": "runtime",
            "skill_contract": {
                "version": "v1",
                "role": "style",
                "execution_plane": "runtime",
            },
            "skill_markdown": final_skill_md,
        }

    async def _analyze_writing_style(
        self, filename: str, flavor: str, mid: str, tail: str
    ) -> Dict[str, Any]:
        """Phase 1: LLM-based writing style analysis. Returns structured JSON."""
        system = (
            "You are an expert in analyzing writing styles. Extract the author's writing conventions precisely from the provided document excerpts.\n"
            "Output only valid JSON, without explanation.\n\n"
            "Analyze these dimensions and return a JSON object:\n"
            "1. doc_type: document type, such as 'tech_blog', 'research_report', 'tutorial', 'news_article', "
            "'marketing_copy', 'product_doc', 'newsletter', or 'opinion_piece'\n"
            "2. opening_style: opening approach, such as 'narrative_hook', 'data_driven', 'question', "
            "'direct_thesis', 'case_study', 'historical_context', or 'quote'\n"
            "3. tone: such as 'conversational_professional', 'formal', 'casual', 'academic', "
            "'authoritative', 'humorous', or 'inspirational'\n"
            "4. conclusion_style: such as 'call_to_action', 'summary', 'memorable_takeaway', "
            "'open_question', or 'future_outlook'\n"
            "5. heading_style: object containing max_depth (1-4), approximate max_headings, "
            "numbered (whether headings are numbered), and style ('descriptive', 'question', 'action', or 'mixed')\n"
            "6. paragraph_style: 'long_narrative', 'short_punchy', 'mixed', or 'list_heavy'\n"
            "7. list_usage: 'minimal', 'moderate', or 'heavy'\n"
            "8. visual_usage: charts or infographics, 'none', 'occasional', or 'frequent'\n"
            "9. code_usage: code blocks, 'none', 'occasional', or 'frequent'\n"
            "10. separator_usage: frequency of horizontal rules; output integer max_separators (0 none, 1 occasional, 2+ frequent)\n"
            "11. language: primary language, 'zh', 'en', or 'mixed'\n"
            "12. notable_phrases: recurring stylistic phrases or verbal habits (list of at most 5)\n"
            "13. anti_patterns: writing habits this style should avoid (list of at most 8)\n"
            "14. distinctive_features: the author's 2-3 most distinctive traits, described in natural language\n"
            "15. skill_name: concise English snake_case identifier, such as 'tech_blog_conversational'\n"
            "16. skill_description: one-sentence description of this style in the source document's primary language\n"
        )
        user = (
            f"Filename: {filename}\n\n"
            f"--- Document opening ---\n{flavor}\n\n"
        )
        if mid:
            user += f"--- Document middle ---\n{mid}\n\n"
        if tail:
            user += f"--- Document ending ---\n{tail}\n\n"
        user += "Output JSON:"

        try:
            resp = await llm_service.chat_complete(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=1.0,
            )
            cleaned = resp.replace("```json", "").replace("```", "").strip()
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1:
                cleaned = cleaned[start:end + 1]
            return json.loads(cleaned)
        except Exception as e:
            logger.warning("style analysis failed", extra={"event": "skills.style_analysis_failed", "error": str(e)})
            return {
                "doc_type": "article",
                "opening_style": "narrative_hook",
                "tone": "conversational_professional",
                "conclusion_style": "summary",
                "language": source_style_language({}, flavor),
                "skill_name": "user_custom_style",
                "skill_description": (
                    "从用户文档提取的写作规范"
                    if source_style_language({}, flavor) == "zh"
                    else "Writing style guide extracted from the user's document"
                ),
            }

    async def _compile_style_skill_md(self, style_analysis: Dict, flavor: str) -> str:
        """Phase 2: Compile a style SKILL.md from the analysis results."""
        analysis_str = json.dumps(style_analysis, indent=2, ensure_ascii=False)
        skill_name = str(style_analysis.get("skill_name") or "user_writing_style")
        language = source_style_language(style_analysis, flavor)
        skill_desc = str(style_analysis.get("skill_description") or style_description_fallback(language))

        system = (
            "You compile writing-style skills. Generate a SKILL.md file from the style analysis.\n"
            "An AI writing system will read this file when it needs to write in this style.\n\n"
            "Output a complete Markdown file with YAML frontmatter and a body.\n\n"
            "== YAML frontmatter format ==\n"
            "Follow this structure exactly, enclosed by ---:\n"
            "```\n"
            "---\n"
            f"name: {skill_name}\n"
            f"description: \"{skill_desc}\"\n"
            "role: style\n"
            "style_contract:\n"
            "  structure:\n"
            "    max_heading_depth: <from analysis>\n"
            "    max_headings: <from analysis>\n"
            "    max_separators: <from analysis>\n"
            "    paragraph_first: <true if paragraphs are preferred over lists>\n"
            "    max_consecutive_lists: 2\n"
            "  visual_policy:\n"
            "    min_infographics: <0, 1, or 2 based on analysis>\n"
            "    include_infographic_blocks: <true/false>\n"
            "    image_render_enabled: <true/false>\n"
            "    visual_spec_format: \"[VISUAL:label]...[/VISUAL]\"\n"
            "  defaults:\n"
            "    opening_style: <from analysis>\n"
            "    tone: <from analysis>\n"
            "    conclusion_style: <from analysis>\n"
            "  length:\n"
            "    min_words: <reasonable estimate>\n"
            "    max_words: <reasonable estimate>\n"
            "  anti_patterns:\n"
            "    - <from analysis, one item per line>\n"
            "---\n"
            "```\n\n"
            "== Markdown body ==\n"
            f"Write the body as natural-language writing guidance (soft constraints). {style_body_language_instruction(language)} Cover:\n"
            "1. **Opening style**: concrete guidance and examples for starting a piece\n"
            "2. **Overall tone and narrative pace**: how to maintain a consistent tone\n"
            "3. **Paragraph and structural habits**: paragraph length and transitions\n"
            "4. **Heading style**: how to write headings that fit this style\n"
            "5. **Visual elements**: infographic rules when needed\n"
            "6. **Conclusion style**: how to close the piece\n"
            "7. **Taboos and anti-patterns**: what this style must never do\n\n"
            "Important:\n"
            "- Do not include execution-skill sections such as # Purpose, # Inputs, # Workflow, or # Failure handling\n"
            "- The body should read as a writing manual, not code logic\n"
            "- Use second-person guidance\n"
            "- Quote actual sentence patterns from the source as positive examples\n"
            "- Return plain Markdown without a code fence\n"
        )
        user = (
            f"Style analysis:\n{analysis_str}\n\n"
            f"Source style sample (for examples):\n{flavor[:3000]}\n\n"
            "Generate the complete style SKILL.md:"
        )

        return await llm_service.chat_complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=1.0,
        )

    async def _validate_style_skill(self, skill_md: str, style_analysis: Dict, max_retries: int = 2) -> str:
        """Phase 3: Validate and repair style SKILL.md."""
        import re

        def _check_errors(md: str) -> List[str]:
            errors = []
            md_lower = md.lower()

            # Must have frontmatter
            if "---" not in md:
                errors.append("Missing YAML frontmatter (must be enclosed by ---)")

            # Must have role: style
            if "role: style" not in md_lower and "role: 'style'" not in md_lower and 'role: "style"' not in md_lower:
                errors.append("Frontmatter must contain role: style")

            # Must have style_contract
            if "style_contract:" not in md:
                errors.append("Frontmatter must contain a style_contract block")

            # Must NOT have execution skill sections
            execution_headers = ["# Purpose", "# Inputs", "# Workflow", "# Failure handling"]
            for h in execution_headers:
                if h in md:
                    errors.append(f"Must not contain execution-skill section '{h}' (this is a style skill)")

            # Must have style_contract sub-sections
            if "style_contract:" in md:
                if "structure:" not in md:
                    errors.append("style_contract is missing the structure section")
                if "defaults:" not in md:
                    errors.append("style_contract is missing the defaults section")

            # Body should exist (writing guidelines)
            meta, body = _split_frontmatter(md)
            if len(body.strip()) < 100:
                errors.append("The body (LLM writing guidance) is too short; at least 100 characters are required")

            return errors

        current_md = skill_md
        for attempt in range(max_retries + 1):
            errors = _check_errors(current_md)
            if not errors:
                return current_md

            if attempt < max_retries:
                logger.warning("style skill validation failed", extra={"event": "skills.style_validation_failed", "attempt": attempt + 1, "errors": errors})
                system = (
                    "You are a strict Style SKILL.md repair engine.\n"
                    "Fix the supplied SKILL.md according to these validation errors.\n\n"
                    f"Validation errors:\n" + "\n".join(f"- {e}" for e in errors) + "\n\n"
                    "Repair requirements:\n"
                    "- This is a style skill (writing guidance), not an execution skill\n"
                    "- Frontmatter must include role: style and style_contract\n"
                    "- The body is LLM writing guidance, not an execution procedure\n"
                    "- Output the entire repaired Markdown directly, beginning with ---\n"
                    "- Do not wrap the output in a code fence\n"
                )
                try:
                    resp = await llm_service.chat_complete(
                        [{"role": "system", "content": system}, {"role": "user", "content": current_md}],
                        temperature=1.0,
                    )
                    resp = resp.strip()
                    if resp.startswith("```"):
                        resp = re.sub(r"^```\w*\n?", "", resp)
                        resp = re.sub(r"\n?```$", "", resp)
                    current_md = resp.strip()
                except Exception as e:
                    logger.warning("style skill repair failed", extra={"event": "skills.style_repair_failed", "error": str(e)})
            else:
                logger.warning("style skill validation exhausted", extra={"event": "skills.style_validation_exhausted", "max_retries": max_retries})

        return current_md
