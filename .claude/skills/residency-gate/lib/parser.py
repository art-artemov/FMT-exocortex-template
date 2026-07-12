"""Parser for data-needs manifest blocks in SKILL.md and bash hooks."""

import re
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class DataNeed:
    """Single data requirement declaration."""
    name: str
    type: str  # 2.1, 2.2, 2.3, 2.4
    flow_direction: str  # inbound | outbound
    schema_version: int = 1

    def key(self) -> str:
        """Unique identifier for this need within a function."""
        return f"{self.type}_{self.flow_direction}_{self.name}"


class ManifestParser:
    """Parse data-needs blocks from skill/hook files."""

    @staticmethod
    def parse_markdown(content: str, skill_id: str) -> List[DataNeed]:
        """Extract data-needs from SKILL.md frontmatter or body."""
        needs = []

        # Pattern 1: YAML frontmatter block
        yaml_pattern = r'data[-_]needs:\s*\n((?:^\s+[-*].+\n?)*)'
        for match in re.finditer(yaml_pattern, content, re.MULTILINE):
            block = match.group(1)
            needs.extend(ManifestParser._parse_yaml_needs(block, skill_id))

        # Pattern 2: Markdown code fence with data-needs comment
        fence_pattern = r'```(?:python|bash)?\n# --- data-needs\n(.*?)\n# ---\n```'
        for match in re.finditer(fence_pattern, content, re.DOTALL):
            block = match.group(1)
            needs.extend(ManifestParser._parse_comment_needs(block, skill_id))

        return needs

    @staticmethod
    def parse_bash_manifest(content: str, script_name: str) -> List[DataNeed]:
        """Extract data-needs from bash hook file (# --- data-needs ... --- comment block)."""
        needs = []

        # Bash pattern: # --- data-needs ... ---
        pattern = r'# --- data-needs\n((?:#.*\n)*?)# ---'
        for match in re.finditer(pattern, content, re.MULTILINE):
            block = match.group(1)
            needs.extend(ManifestParser._parse_bash_comment_block(block, script_name))

        return needs

    @staticmethod
    def _parse_yaml_needs(block: str, skill_id: str) -> List[DataNeed]:
        """Parse YAML-style list of needs."""
        needs = []
        # Simple YAML parser for our restricted subset
        for line in block.strip().split('\n'):
            line = line.strip()
            if line.startswith('-') or line.startswith('*'):
                # Parse: - type: 2.1, flow: inbound, name: user-profile
                pairs = re.findall(r'(\w+):\s*([^,]+)', line)
                need_dict = {k.strip(): v.strip() for k, v in pairs}

                if 'type' in need_dict and 'flow' in need_dict:
                    try:
                        needs.append(DataNeed(
                            name=need_dict.get('name', f"{skill_id}_0"),
                            type=need_dict['type'],
                            flow_direction=need_dict['flow'],
                            schema_version=int(need_dict.get('schema_version', 1))
                        ))
                    except (KeyError, ValueError):
                        pass
        return needs

    @staticmethod
    def _parse_comment_needs(block: str, skill_id: str) -> List[DataNeed]:
        """Parse from comment block inside code fence."""
        needs = []
        for line in block.strip().split('\n'):
            line = line.strip('#').strip()
            if ':' in line:
                pairs = re.findall(r'(\w+):\s*([^,]+)', line)
                need_dict = {k.strip(): v.strip() for k, v in pairs}

                if 'type' in need_dict and 'flow_direction' in need_dict:
                    try:
                        needs.append(DataNeed(
                            name=need_dict.get('name', f"{skill_id}_0"),
                            type=need_dict['type'],
                            flow_direction=need_dict['flow_direction'],
                            schema_version=int(need_dict.get('schema_version', 1))
                        ))
                    except (KeyError, ValueError):
                        pass
        return needs

    @staticmethod
    def _parse_bash_comment_block(block: str, script_name: str) -> List[DataNeed]:
        """Parse bash-style comment block."""
        needs = []
        for line in block.strip().split('\n'):
            line = line.strip('#').strip()
            if ':' in line and line:
                pairs = re.findall(r'(\w+):\s*([^,]+)', line)
                need_dict = {k.strip(): v.strip() for k, v in pairs}

                if 'type' in need_dict and 'flow_direction' in need_dict:
                    try:
                        needs.append(DataNeed(
                            name=need_dict.get('name', f"{script_name}_0"),
                            type=need_dict['type'],
                            flow_direction=need_dict['flow_direction'],
                            schema_version=int(need_dict.get('schema_version', 1))
                        ))
                    except (KeyError, ValueError):
                        pass
        return needs
