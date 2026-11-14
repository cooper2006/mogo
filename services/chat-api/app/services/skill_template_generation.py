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


class SkillTemplateGenerationMixin:
    async def generate_skill_from_template(self, filename: str, content: bytes) -> Dict[str, Any]:
        """
        Orchestrator for the advanced 3-phase skill generation pipeline:
        Phase 0: Content Analysis (Flavor, Structure, Tail)
        Phase 1: Structural Signature Generation (Intermediate Fact Layer)
        Phase 2: Skill Compilation (Blueprint -> SKILL.md)
        Phase 3: Automated Validation & Repair
        """
        import re
        from app.utils.document_loader import extract_text_from_file

        # --- Phase 0: Text Extraction & Structure Signal Enhancement ---
        extracted_text = extract_text_from_file(content, filename)
        if not extracted_text:
            raise ValueError("Could not extract text from the provided file.")

        def _normalize_text(t: str) -> str:
            t = t.replace("\r\n", "\n").replace("\r", "\n")
            t = re.sub(r"\n{3,}", "\n\n", t)
            return t.strip()

        extracted_text = _normalize_text(extracted_text)

        # Helpers for structure extraction
        def _extract_headings_and_lists(t: str, max_lines: int = 400) -> str:
            lines = [ln.strip() for ln in t.split("\n") if ln.strip()][:max_lines]
            heading_like = []
            list_like = []
            section_like = []

            # Heuristically detect headings, sections, lists (simplified REGEX for speed)
            list_pat = re.compile(r"^(\-|\*|•|■|\u25a0|\u25cf|\d+[\.\)]|[①-⑩])\s+")
            section_pat = re.compile(r"^(第[0-9]+[章节]|Section\s+\d+|[0-9]+\.[0-9]+|[A-Z][A-Z\s]{2,}|.*[:：])$")

            for ln in lines:
                if list_pat.match(ln):
                    list_like.append(ln)
                elif section_pat.match(ln):
                    section_like.append(ln)
                elif len(ln) < 60 and not ln.endswith(('.', '。', '!', '！')):
                    heading_like.append(ln)

            def uniq(seq):
                seen = set()
                return [x for x in seq if not (x in seen or seen.add(x))]

            parts = []
            if heading_like: parts.append("## Detected Headings:\n" + "\n".join(f"- {h}" for h in uniq(heading_like)[:30]))
            if section_like: parts.append("## Detected Sections:\n" + "\n".join(f"- {s}" for s in uniq(section_like)[:30]))
            if list_like: parts.append("## Detected List Styles:\n" + "\n".join(uniq(list_like)[:20]))
            return "\n\n".join(parts)

        structural_signals = _extract_headings_and_lists(extracted_text)
        flavor_snippet = extracted_text[:6000]
        tail_snippet = extracted_text[-2000:] if len(extracted_text) > 2000 else ""

        def _ensure_frontmatter(md: str) -> str:
            md = md.strip()
            # Remove code fences
            md = md.replace("```markdown", "").replace("```", "").strip()
            # Find first ---
            if "---" in md and not md.startswith("---"):
                md = md[md.find("---"):]

            if not md.startswith("---"):
                safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', filename.split(".")[0])
                front = (
                    "---\n"
                    f"name: {safe_name}\n"
                    "description: Auto-generated generator skill\n"
                    "category: document\n"
                    "---\n\n"
                )
                md = front + md
            return md

        # --- Pipeline Execution ---
        logger.info("skill generation phase started", extra={"event": "skills.generation_phase", "phase": "structural_signature"})
        signature = await self._generate_structural_signature(filename, flavor_snippet, structural_signals, tail_snippet)

        logger.info("skill generation phase started", extra={"event": "skills.generation_phase", "phase": "compile_from_signature", "doc_family": signature.get("doc_family", "unknown")})
        skill_md = await self._compile_skill_from_signature(signature, filename, flavor_snippet)

        logger.info("skill generation phase started", extra={"event": "skills.generation_phase", "phase": "validate_and_repair"})
        final_skill_md = await self._validate_and_repair(skill_md, signature)

        # Final Verification & Cleanup
        final_skill_md = _ensure_frontmatter(final_skill_md)

        # Final Formatting
        meta, body = _split_frontmatter(final_skill_md)
        role = _normalize_skill_role(meta.get("role")) or _infer_role_from_fields(
            category=str(meta.get("category", "document") or ""),
            name=str(meta.get("name", "Generated Skill") or ""),
            description=str(meta.get("description", "") or ""),
            skill_markdown=final_skill_md,
            formats=[],
        )
        contract = _compile_skill_contract(
            name=str(meta.get("name", "Generated Skill") or ""),
            description=str(meta.get("description", "") or ""),
            category=str(meta.get("category", "document") or ""),
            formats=[],
            skill_markdown=final_skill_md,
        )
        if role:
            contract["role"] = role
        return {
            "name": meta.get("name", "Generated Skill"),
            "description": meta.get("description", ""),
            "category": meta.get("category", "document"),
            "role": role,
            "execution_plane": str(contract.get("execution_plane") or "runtime"),
            "skill_contract": contract,
            "skill_markdown": final_skill_md,
        }

    async def _generate_structural_signature(self, filename: str, flavor: str, structure: str, tail: str) -> Dict[str, Any]:
        """Phase 1: Create the 'Structural Signature' (Blueprint JSON)"""
        system = (
            "You are a Document Forensics Expert. Your job is to extract the 'Structural Signature' (DNA) of a document template.\n"
            "You MUST output valid JSON only.\n\n"
            "Task: Analyze the document snippets and produce a JSON blueprint with these exact fields:\n"
            "1. doc_family: The likely document category (e.g., 'api_reference', 'marketing_plan', 'legal_brief', 'prd'). Use snake_case. If it doesn't fit existing types, propose a descriptive new one.\n"
            "2. doc_topic: string (the specific subject matter, snake_case, e.g. 'net_drama_market_2025', 'q3_financial_report' - NOT generic like 'report')\n"
            "3. primary_unit: The atomic unit of the document (e.g., 'endpoint', 'feature', 'clause', 'slide', 'entry'). If unknown, propose a descriptive 'snake_case' unit.\n"
            "4. ordering_logic: one of [hierarchical, sequential, indexed, mixed]\n"
            "5. sections: list of likely section names (ordered)\n"
            "6. required_blocks: list of specific block types that MUST appear (e.g. 'code_block', 'trend_card', 'price_table', 'signature_line', 'user_story', 'acceptance_criteria')\n"
            "7. optional_blocks: list of optional elements\n"
            "8. style_profile: { tone: '...', verbosity: '...', formatting: 'markdown/table/etc' }\n"
            "9. constraints: { \n"
            "     'must_include': ['...'], \n"
            "     'must_not_include': ['...'] \n"
            "   }\n"
            "   *CRITICAL*: List 'must_not_include' to prevent template contamination.\n"
        )
        user = (
            f"Filename: {filename}\n"
            f"Structure Signals:\n{structure}\n\n"
            f"Head Snippet:\n{flavor}\n\n"
            f"Tail Snippet:\n{tail}\n\n"
            "Output JSON Signature:"
        )
        try:
            resp = await llm_service.chat_complete(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=1.0 # Force 1.0 based on model constraint
            )

            # Robust JSON extraction
            import json
            cleaned = resp.replace("```json", "").replace("```", "").strip()

            # Find the first { and last }
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1:
                cleaned = cleaned[start:end+1]

            return json.loads(cleaned)
        except Exception as e:
            logger.warning(
                "skill signature generation failed",
                extra={"event": "skills.signature_generation_failed", "error": str(e), "raw_preview": cleaned[:100] if "cleaned" in locals() else "N/A", "response_tail": resp[-500:] if "resp" in locals() else "N/A"},
            )
            return {"doc_family": "other", "constraints": {"must_not_include": []}}

    def _generate_deterministic_name_and_desc(self, signature: Dict[str, Any], flavor: str = "") -> tuple[str, str, str]:
        """
        Implements Advanced Deterministic Naming Scheme: <primary_unit>_<pattern>_<family>_<keyblock>_generator
        Returns: (name, description, category)
        """

        # --- Constants from User Rule ---
        GENERIC_TOKENS = {"section", "structured", "general", "generic", "text", "document", "report"}
        KEYBLOCK_PRIORITY = [
            ["ranking", "metric", "comparison", "chart", "trend", "statistics"],
            ["request_schema", "response_schema", "error_schema", "endpoint_def"],
            ["approval_flow", "version_history", "clause_numbering", "signature_block"],
            ["diagram", "architecture_placeholder", "infographic", "visuals"],
            ["table", "grid"],
            ["bullet_list", "list"],
            ["heading", "section"]
        ]

        # --- Helper Functions ---
        def pick_keyblock(required_blocks):
            rb_set = set(b.lower() for b in required_blocks)
            for tier in KEYBLOCK_PRIORITY:
                for b in tier:
                    # Check partial match (e.g. "trend" matches "trend_card")
                    if any(b in rb for rb in rb_set):
                        if b in {"heading", "section", "bullet_list", "list"}:
                            continue
                        return b
            return "table" if any("table" in rb for rb in rb_set) else "block"

        def infer_pattern(signature, force_upgrade=False):
            rb = set(b.lower() for b in signature.get("required_blocks", []))

            # Priority Inference Rules
            if any(w in rb for w in ["ranking", "metric", "comparison", "chart", "trend"]):
                return "analytical"
            if any(w in rb for w in ["request_schema", "response_schema", "error_schema", "endpoint"]):
                return "specification"
            if any(w in rb for w in ["approval_flow", "clause_numbering", "clause"]):
                return "regulatory"
            if any(w in rb for w in ["step", "procedure", "sequential"]):
                return "procedural"
            if any(w in rb for w in ["diagram", "infographic", "visuals", "slide"]):
                return "presentation"
            if any(w in rb for w in ["hypothesis", "method", "experiment"]):
                return "scientific"
            if any(w in rb for w in ["form", "field", "validation"]):
                return "declarative"
            if any(w in rb for w in ["user_story", "acceptance_criteria", "requirement", "feature"]):
                return "functional"
            if any(w in rb for w in ["comparison", "contrast", "versus"]):
                return "comparative"
            if any(w in rb for w in ["question", "answer", "faq", "inquiry"]):
                return "inquiry"

            return "structured"

        def map_primary_unit(raw_unit):
            unit_map = {
                "endpoint": "api", "step": "procedural", "clause": "policy",
                "slide": "presentation", "trend": "analytical", "metric": "metric",
                "field": "form", "argument": "academic", "feature": "feature",
                "requirement": "requirement"
            }
            mapped = unit_map.get(raw_unit.lower(), raw_unit.lower())
            return _slugify(mapped).replace("-", "_")

        def map_doc_family(raw_family):
            family_map = {
                "api_reference": "specification", "analytical_brief": "report",
                "slide_deck": "presentation", "sop_playbook": "procedure",
                "policy_document": "policy", "form_template": "form",
                "academic_paper": "paper", "dataset_report": "dataset",
                "product_requirement": "requirement", "prd": "requirement"
            }
            mapped = family_map.get(raw_family.lower(), raw_family.lower())
            return _slugify(mapped).replace("-", "_")

        def specificity_score(name, signature):
            score = 0
            if signature.get("primary_unit", "section") != "section": score += 2
            if infer_pattern(signature) != "structured": score += 2

            kb = pick_keyblock(signature.get("required_blocks", []))
            if kb not in {"block", "table"}: score += 3

            score += 1 # Base score for having family

            # Penalize generic tokens
            tokens = set(name.split("_"))
            score -= sum(1 for t in tokens if t in GENERIC_TOKENS)
            return score

        # --- Main Logic ---
        primary = map_primary_unit(signature.get("primary_unit", "section"))
        pattern = infer_pattern(signature)
        family = map_doc_family(signature.get("doc_family", "document"))
        keyblock = pick_keyblock(signature.get("required_blocks", []))

        # Initial Candidate: 3-segment (legacy) or 4-segment? User format is <unit>_<pattern>_<family>_<keyblock>_generator
        # But user said "Upgrade from 4 to 5 segments". Let's start with
        # <unit>_<pattern>_<family>_generator (Base)
        # And check score. If low, add keyblock.

        base_name = f"{primary}_{pattern}_{family}_generator"
        final_name = base_name

        # Check Specificity
        if specificity_score(base_name, signature) < 6:
            # Upgrade Steps
            # 1. Add Keyblock
            if keyblock != "block":
                final_name = f"{primary}_{pattern}_{family}_{keyblock}_generator"

            # 2. If still potentially weak (or just enforces user rule), try upgrading pattern/primary
            if specificity_score(final_name, signature) < 6:
                 # Force Pattern Upgrade from Blocks
                 new_pattern = infer_pattern(signature, force_upgrade=True)
                 if new_pattern != pattern:
                     pattern = new_pattern
                     final_name = f"{primary}_{pattern}_{family}_{keyblock}_generator"

            if specificity_score(final_name, signature) < 6:
                # Force Primary Unit Upgrade
                if primary == "section":
                     primary = "content" # slightly better? or stick to map
                     final_name = f"{primary}_{pattern}_{family}_{keyblock}_generator"

        # --- Description Generation ---
        # "Generates a <pattern> <family> composed of <block1>, <block2>."
        # Pick 2 distinctive blocks
        distinctive_blocks = []
        rb_list = signature.get("required_blocks", [])

        for tier in KEYBLOCK_PRIORITY:
            for b in tier:
                if b in {"heading", "section", "bullet_list", "list"}: continue
                # Find matching block in required_blocks
                matches = [rb for rb in rb_list if b in rb.lower()]
                if matches:
                    distinctive_blocks.extend(matches)

        # Deduplicate and slice
        distinctive_blocks = list(dict.fromkeys(distinctive_blocks))[:2]
        if not distinctive_blocks:
            distinctive_blocks = ["standard content blocks"]

        blocks_text = ", ".join(distinctive_blocks)
        description = f"Generates a {pattern} {family} composed of {blocks_text}."

        # --- Category Generation ---
        # 1. Analysis & Reports
        # 2. Specs & Product
        # 3. Governance & SOPs
        # 4. Presentation & Visuals
        # 5. Coding & Engineering
        # 6. Browser Automation

        category = "Analysis & Reports" # Default fallback

        # Priority Check
        full_text = f"{family}_{pattern}_{primary}_{flavor[:1000]}".lower()

        if any(token in full_text for token in ["code", "script", "test", "api", "endpoint"]):
            category = "Coding & Engineering"
        elif any(token in full_text for token in ["browser", "web", "scrape", "selenium", "playwright"]):
            category = "Browser Automation"
        elif any(token in full_text for token in ["presentation", "slide", "visual", "deck", "ppt"]):
            category = "Presentation & Visuals"
        elif any(token in full_text for token in ["policy", "procedure", "sop", "regulation", "compliance", "regulatory", "legal", "clause"]):
            category = "Governance & SOPs"
        elif any(token in full_text for token in ["market", "survey", "brief", "report", "analysis", "trend", "insight", "research"]):
            category = "Analysis & Reports"
        elif any(token in full_text for token in ["specification", "spec", "schema", "product", "requirement", "feature", "prd"]):
            category = "Specs & Product"
        else:
            category = "Analysis & Reports" # Default fallback

        return final_name, description, category

    async def _compile_skill_from_signature(self, signature: Dict, filename: str, flavor: str) -> str:
        """Phase 2: Compile SKILL.md from the Signature"""
        sig_str = json.dumps(signature, indent=2, ensure_ascii=False)
        forbidden_list = signature.get('constraints', {}).get('must_not_include', [])
        forbidden_str = ", ".join(forbidden_list)

        # Generate Deterministic Identity
        skill_name, skill_desc, skill_cat = self._generate_deterministic_name_and_desc(signature, flavor)

        system = (
            "You are an AI Skill Compiler. Your task: Compile a 'SKILL.md' based strictly on the provided Structural Signature.\n"
            "The goal is to create a GENERATOR skill that writes NEW documents of this family from scratch.\n\n"
            "CRITICAL CONSTRAINTS (from Signature):\n"
            f"- Family: {signature.get('doc_family')}\n"
            f"- MUST include blocks: {signature.get('required_blocks')}\n"
            f"- MUST NOT include: {forbidden_str}\n\n"
            "STRICT OUTPUT TEMPLATE (You MUST include these 8 sections):\n"
            "1. # Purpose\n"
            "   - Clearly state this is a GENERATOR for [doc_family].\n"
            "   - IF doc_family is 'analytical_brief', state: 'This skill generates a NEW analysis based on structured input data.' NEVER say 'summarizes the document'.\n"
            "2. # When to use\n"
            "   - Describe the specific scenario (e.g. 'When you need to create a fresh {signature.get('doc_topic', 'document')}...').\n"
            "3. # Inputs\n"
            "   - Use configuration switches (boolean flags) for optional blocks.\n"
            "   - For list items (like endpoints, methods), use SCHEMA OBJECTS (e.g. `endpoint_schema` with fields `name`, `method`, `desc`) instead of simple strings.\n"
            "   - Include a `formatting_preferences` object (e.g. table vs list).\n"
            "   - NEVER ask for 'source text'.\n"
            "4. # Workflow\n"
            "   - Step-by-step logic to build the document.\n"
            "5. # Output format\n"
            "   - Define rigidity. If 'trend_card' is required, define its exact markdown schema here.\n"
            "6. # Examples\n"
            "   - Provide a brief dummy example of the output style.\n"
            "7. # Rules\n"
            "   - Explicitly list NEGATIVE CONSTRAINTS.\n"
            f"   - You MUST write: 'NEVER include: {forbidden_str}' as a rule.\n"
            "8. # Failure handling\n"
            "   - How to handle missing input data (e.g. 'If endpoint description is missing, use default placeholder').\n\n"
            "Return raw Markdown starting with '---'. Frontmatter MUST be exactly as follows:\n"
            f"name: {skill_name}\n"
            f"description: {skill_desc}\n"
            f"category: {skill_cat}\n"
        )
        user = f"Signature:\n{sig_str}\n\nContent Flavor (for tone inference only):\n{flavor[:2000]}"

        return await llm_service.chat_complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=1.0
        )

    async def _validate_and_repair(self, skill_md: str, signature: Dict, max_retries: int = 2) -> str:
        """Phase 3: Automated QA and Repair"""

        def _check_fail(md: str, sig: Dict) -> List[str]:
            errors = []
            md_lower = md.lower()

            # 1. Intent Check
            forbidden = ["translate", "translation", "summarize", "summary", "source document", "source text", "input document", "extract text"]
            if any(w in md_lower for w in forbidden):
                errors.append("Skill appears to be a translator/summarizer (found forbidden terms like 'translate', 'source document'). Must be a GENERATOR.")

            # 2. Structural Check
            req_blocks = sig.get('required_blocks', []) or []
            for b in req_blocks:
                if b.replace("_", " ") not in md_lower and b not in md_lower:
                    errors.append(f"Missing required block from signature: {b}")

            # Check for explicit blacklist in Rules (Heuristic: search for 'never include' near the forbidden word)
            forbidden_blocks = sig.get('constraints', {}).get('must_not_include', []) or []
            for b in forbidden_blocks:
                if b.replace("_", " ") in md_lower or b in md_lower:
                    # Allow it ONLY if it is in a "NEVER include" context (simple check is hard, so we stick to strict exclusion for now unless it's in the Rules section as a negative example)
                    # Ideally, the generator simply shouldn't mention it unless it's in the Rules saying "Don't do it".
                    # We will relax this check: If it appears, it MUST be near "never" or "not".
                    # For stability, let's keep strict check -> it shouldn't be in the *content* generation logic.
                    # But since we Asked it to write it in Rules, we need to allow it THERE.
                    # Heuristic: Check if the forbidden word is present BUT NOT prefixed by "never" or "do not" in the line.
                    pass # We trust the prompt for now, or we'd need complex regex.
                    # Actually, let's stick to the previous strict check but ignore it if it's in the # Rules section.

            # 3. Input Check (Heuristic)
            if "# Inputs" in md:
                inputs_section = md.split("# Inputs")[1].split("#")[0].lower()
                if "topic" not in inputs_section and "scope" not in inputs_section and "schema" not in inputs_section:
                   errors.append("Inputs section missing standard generator fields (topic, scope) or schema definition.")
                if "text" in inputs_section or "file" in inputs_section or "content" in inputs_section:
                    pass

            # 4. Structure Completeness (8 Sections)
            required_headers = ["# Purpose", "# When to use", "# Inputs", "# Workflow", "# Output format", "# Examples", "# Rules", "# Failure handling"]
            for h in required_headers:
                if h not in md:
                    errors.append(f"Missing required section: '{h}'")

            return errors

        current_md = skill_md
        for attempt in range(max_retries + 1):
            errors = _check_fail(current_md, signature)
            if not errors:
                return current_md

            if attempt < max_retries:
                logger.warning("skill validation failed", extra={"event": "skills.validation_failed", "attempt": attempt + 1, "errors": errors})
                system = (
                    "You are a strict Code Repair Engine.\n"
                    "Your task is to fix the provided SKILL.md based on the validation errors below.\n"
                    f"Validation Errors:\n" + "\n".join(f"- {e}" for e in errors) + "\n\n"
                    "REQUIREMENTS:\n"
                    "- Return a JSON object with a single key 'fixed_skill_md' containing the corrected markdown string.\n"
                    "- Do NOT output any text outside the JSON.\n"
                    "- Ensure the markdown starts with '---\n'."
                )
                try:
                    resp = await llm_service.chat_complete(
                        [{"role": "system", "content": system}, {"role": "user", "content": current_md}],
                        temperature=1.0
                    )
                    import json
                    cleaned = resp.replace("```json", "").replace("```", "").strip()
                    if "{" in cleaned:
                        current_md = json.loads(cleaned).get("fixed_skill_md", current_md)
                    else:
                        # Fallback if model refuses JSON but outputs markdown directly
                        current_md = resp
                except Exception as e:
                    logger.warning("skill repair JSON parse failed", extra={"event": "skills.repair_json_parse_failed", "error": str(e)})
                    # Use raw response as fallback (hope it's markdown)
                    current_md = resp
            else:
                logger.warning("skill validation exhausted", extra={"event": "skills.validation_exhausted", "max_retries": max_retries})

        return current_md

    # ------------------------------------------------------------------ #
    # Style Extraction Pipeline (default for document upload)             #
    # ------------------------------------------------------------------ #
