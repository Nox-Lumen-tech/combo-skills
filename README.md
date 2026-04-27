# Combo Agent Skills

Skills for [Combo Agent](https://xipnex.nox-lumen.com) — binary document editing, Word/Excel generation, cross-session retrieval from local IDEs, and more.

## Skills

| Skill | Description |
|-------|-------------|
| [document-editing](./document-editing/) | Binary document (DOCX/XLSX/PPTX) incremental editing with Copy-on-Write snapshots |
| [docx](./docx/) | Create, read, edit, and manipulate Word documents (.docx) with full formatting support |
| [xlsx](./xlsx/) | Create, read, edit, and manipulate Excel spreadsheets (.xlsx/.xls) |
| [eea-gac-cross-reference](./eea-gac-cross-reference/) | Cross-reference EEA / GAC ASPICE artifacts (requirements ↔ design ↔ test) |
| [graft-comboagent](./graft-comboagent/) | **Local IDE → Combo Agent cloud bridge.** Lets Cursor / Claude Code / Codex / Trae fetch session digests, rounds, and files from your Combo Agent tenant over HTTPS |

## Installation

### A. From Combo Agent chat (cloud-side skills)

In Combo Agent chat, use the skill install command:

```
/skill-install Nox-Lumen-tech/combo-skills/<skill-name>
```

For example:

```
/skill-install Nox-Lumen-tech/combo-skills/document-editing
/skill-install Nox-Lumen-tech/combo-skills/docx
/skill-install Nox-Lumen-tech/combo-skills/xlsx
/skill-install Nox-Lumen-tech/combo-skills/eea-gac-cross-reference
```

### B. Into a local IDE (Cursor / Claude Code / Codex / Trae)

For skills meant to run inside a local IDE host (currently: `graft-comboagent`):

```bash
git clone https://github.com/Nox-Lumen-tech/combo-skills.git ~/src/combo-skills

# Cursor
cp -r ~/src/combo-skills/graft-comboagent ~/.cursor/skills/

# Claude Code
cp -r ~/src/combo-skills/graft-comboagent ~/.claude/skills/

# Codex
cp -r ~/src/combo-skills/graft-comboagent ~/.codex/skills/

# Trae
cp -r ~/src/combo-skills/graft-comboagent ~/.trae/skills/
```

See each skill's own `README.md` / `SKILL.md` for first-time setup (e.g. `graft-comboagent` needs `python scripts/login.py` against your Combo Agent server before first use).

## License

See individual skill directories for license information.
