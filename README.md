# Combo Agent Skills

Skills for [Combo Agent](https://xipnex.nox-lumen.com) — code review, binary document editing, Word/Excel generation, cross-session retrieval from local IDEs, and more.

See the [docs · Skills](https://xipnex.nox-lumen.com/docs/skills) for the full skill catalog.

## Skills

### Document handling

| Skill | Description |
|-------|-------------|
| [document-editing](./document-editing/) | Binary document (DOCX/XLSX/PPTX) incremental editing with Copy-on-Write snapshots |
| [docx](./docx/) | Create, read, edit, and manipulate Word documents (.docx) with full formatting support |
| [xlsx](./xlsx/) | Create, read, edit, and manipulate Excel spreadsheets (.xlsx/.xls) |

### Code review — L2 (semantic, LLM-driven)

[Overview](https://xipnex.nox-lumen.com/docs/skills/code-review)

| Skill | Description |
|-------|-------------|
| [code-review](./code-review/) | Enterprise L2 review. Cross-checks code against requirements / design docs / coding standards / bug history. Produces structured reports across 8 categories × 3 severities |

### Code review — L1 (static analysis, deterministic)

L1 skills run upstream tools and emit a unified `CodeEvidence` JSON consumed by [code-review](./code-review/).

| Skill | Language | Tool wrapped |
|-------|----------|--------------|
| [bandit](./bandit/) | Python | Python security scanner — SQLi / command injection / hard-coded secrets / unsafe funcs |
| [ruff](./ruff/) | Python | Ultra-fast lint (replaces Flake8/Pylint/isort/Black, 900+ rules, Rust) |
| [mypy](./mypy/) | Python | Type checker — PEP 484 reference implementation |
| [semgrep](./semgrep/) | Multi (30+) | Cross-language SAST with custom YAML rules |
| [checkstyle](./checkstyle/) | Java | Style & naming conventions (Google Java Style / Sun) |
| [pmd](./pmd/) | Java / Kotlin | Anti-pattern detection + CPD copy-paste detector |
| [spotbugs](./spotbugs/) | Java | Bytecode-level bug detection + FindSecBugs (OWASP) |
| [clang-tidy](./clang-tidy/) | C / C++ | LLVM-based — bugprone / performance / modernize / cert / MISRA |
| [cppcheck](./cppcheck/) | C / C++ | No-build bug detection — leaks / null deref / OOB / UB |
| [detekt](./detekt/) | Kotlin | Code smells, complexity, ktlint rules built-in |

### Local IDE bridge

| Skill | Description |
|-------|-------------|
| [graft-comboagent](./graft-comboagent/) | **Local IDE → Combo Agent cloud bridge.** Lets Cursor / Claude Code / Codex / Trae fetch session digests, rounds, and files from your Combo Agent tenant over HTTPS |

## Installation

### A. From Combo Agent chat (cloud-side skills)

In Combo Agent chat, use the skill install command:

```
/skill-install Nox-Lumen-tech/combo-skills/<skill-name>
```

For example:

```
/skill-install Nox-Lumen-tech/combo-skills/code-review
/skill-install Nox-Lumen-tech/combo-skills/ruff
/skill-install Nox-Lumen-tech/combo-skills/checkstyle
/skill-install Nox-Lumen-tech/combo-skills/clang-tidy
/skill-install Nox-Lumen-tech/combo-skills/docx
/skill-install Nox-Lumen-tech/combo-skills/document-editing
/skill-install Nox-Lumen-tech/combo-skills/xlsx
```

> The full **L1 + L2 review suite** is just 11 `/skill-install` commands away.
> See [docs · code-review](https://xipnex.nox-lumen.com/docs/skills/code-review) for how the layers compose.

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

See individual skill directories for license information. The L1 wrappers carry the upstream tool's license tag in the SKILL.md frontmatter (e.g. `pmd` = BSD-4-Clause, `checkstyle` = LGPL-2.1) — the wrapper itself is part of this repo.
