#!/usr/bin/env python3
"""Self-check for install_skill 的打包环节（no pytest）：BOM 剥离 + 可移植性提醒.

BOM: 一个在 Windows 上打包的技能，四个文件都以 ``\\ufeff`` 开头。服务端的
front-matter 正则锚在第 0 字节，BOM 让它整条 miss，技能落库时
``description="\\ufeff---"``（前端没有备注），整段 front-matter 还漏进正文注入给模型。

可移植性: 技能根目录在两个引擎里不是同一个绝对路径，当前目录也都不是技能目录，
所以写死 ``/workspace/...`` 或裸文件名的技能换个引擎就读不到文件。
"""
import io
import json
import tempfile
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

import call

BOM = b"\xef\xbb\xbf"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake"
SKILL_MD = (
    b'---\nname: bom-skill\ndescription: "\xe5\xb8\xa6 BOM"\n---\n\n# Body\n\n'
    b"python3 /workspace/bom-skill/scripts/run.py\n"
)
SKILL_MD_FIXED = SKILL_MD.replace(
    b"/workspace/bom-skill/scripts/run.py", b"${CLAUDE_SKILL_DIR}/scripts/run.py",
)


def _make_skill(root: Path) -> Path:
    d = root / "bom-skill"
    (d / "scripts").mkdir(parents=True)
    (d / "assets").mkdir()
    (d / "SKILL.md").write_bytes(BOM + SKILL_MD)
    (d / "scripts" / "run.py").write_bytes(BOM + b"print(1)\n")
    (d / "assets" / "logo.png").write_bytes(BOM + PNG)  # 伪二进制：不该被剥
    (d / "tmp" / "run1").mkdir(parents=True)  # 本地 code-exec 落盘，不该进包
    (d / "tmp" / "run1" / "_exec_main.py").write_bytes(b"print('junk')\n")
    return d


def check_pack_strips_bom_and_fixes_paths() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        skill_dir = _make_skill(Path(tmp))
        captured = {}

        def fake_post(url, data=None, files=None, headers=None, **kwargs):
            captured["zip"] = files["file"][1]
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"code": 0, "data": {
                    "success": True, "skill_name": "bom-skill", "file_count": 3,
                }},
                text="",
            )

        original_post = call.requests.post
        call.requests.post = fake_post
        try:
            args = SimpleNamespace(
                skill_path=str(skill_dir), overwrite=False, allow_shadow=False,
                insecure=False, raw=True,
            )
            with redirect_stdout(io.StringIO()) as out:
                call.do_install_skill(args, {"server": "http://x", "auth_token": "t"})
        finally:
            call.requests.post = original_post

        assert json.loads(out.getvalue().splitlines()[-1])["ok"] is True

        with zipfile.ZipFile(io.BytesIO(captured["zip"])) as zf:
            uploaded = {n: zf.read(n) for n in zf.namelist()}
        # 只动上传副本：本地文件一个字节都没变
        assert (skill_dir / "SKILL.md").read_bytes() == BOM + SKILL_MD

    assert uploaded["bom-skill/SKILL.md"] == SKILL_MD_FIXED, "BOM 或绝对路径没处理"
    assert uploaded["bom-skill/scripts/run.py"] == b"print(1)\n"
    assert uploaded["bom-skill/assets/logo.png"] == BOM + PNG, "二进制不该被改"
    assert not [n for n in uploaded if "/tmp/" in n], f"tmp/ 进包了: {sorted(uploaded)}"


PACKED = [
    "SKILL.md", "scripts/generate_sdd.py", "data/sample.json", "README.md",
    "scripts/util.py", "tools/util.py",
]
VAR = call._SKILL_DIR_VAR


def check_path_rewrite() -> None:
    # Full 专属的技能根：剥掉 builtin-skills/<name>/ 前缀，留包里的相对路径
    md, fixes, _ = call._fix_skill_paths(
        "跑 `python3 /workspace/builtin-skills/sdd/scripts/generate_sdd.py`", PACKED,
    )
    assert f"python3 {VAR}/scripts/generate_sdd.py" in md, md
    assert len(fixes) == 1, fixes

    # <name> 占位也一样剥（写文档时常见）
    md, _, _ = call._fix_skill_paths(
        "见 /workspace/.claude/skills/<name>/data/sample.json", PACKED,
    )
    assert f"见 {VAR}/data/sample.json" in md, md

    # 把某个子目录当成 /workspace 的一级（现场案例：/workspace/sdd_skill/...）
    md, _, _ = call._fix_skill_paths("样例在 /workspace/sdd_skill/data/sample.json", PACKED)
    assert f"样例在 {VAR}/data/sample.json" in md, md

    # 改写后的正文再跑一遍不该变（幂等，--overwrite 重装不会套第二层）
    again, fixes, _ = call._fix_skill_paths(md, PACKED)
    assert again == md and fixes == [], fixes


def check_rewrite_declines() -> None:
    # 包里找不到对应文件 → 不猜，只提醒
    md, fixes, warns = call._fix_skill_paths("产物在 /workspace/mystuff/out.bin", PACKED)
    assert fixes == [] and "/workspace/mystuff/out.bin" in md
    assert any("包里没有对应文件" in w for w in warns), warns


def check_bare_name_is_warn_only() -> None:
    """裸文件名只提醒：是命令参数还是行文只有作者知道，自动改会改坏目录树示意图。"""
    md, fixes, warns = call._fix_skill_paths("先执行 generate_sdd.py 生成草稿", PACKED)
    assert md == "先执行 generate_sdd.py 生成草稿" and fixes == []
    assert any(f"{VAR}/scripts/generate_sdd.py" in w for w in warns), warns

    # 同名文件两处 → 提醒里不给单一建议
    _, _, warns = call._fix_skill_paths("import util.py", PACKED)
    assert any("scripts/util.py" in w and "tools/util.py" in w for w in warns), warns

    # 正文别处给过相对路径，模型找得到 → 不提醒
    assert call._fix_skill_paths(
        "跑 scripts/generate_sdd.py；下称 generate_sdd.py", PACKED,
    )[2] == []

    # 没扩展名的当普通英文词，不碰（真实案例：dist/browse）
    assert call._fix_skill_paths("browse the list", PACKED + ["dist/browse"])[2] == []


def check_rewrite_leaves_valid_paths() -> None:
    # 这些都对，动了就是回归
    for clean in (
        "执行 scripts/generate_sdd.py，样例见 data/sample.json",  # 完整相对路径
        "细节见 README.md",                                      # 技能根下的裸名
        "产物写到 /workspace/outputs/report.md",                  # 会话目录，两引擎都有
        "代码放在 /workspace/.../MyClass.java",                   # 文档占位
        "会话目录 /workspace/sessions/<sid>/ 下",
        f"已经是 {VAR}/scripts/generate_sdd.py",
    ):
        md, fixes, warns = call._fix_skill_paths(clean, PACKED)
        assert md == clean and fixes == [] and warns == [], (clean, fixes, warns)


def main() -> None:
    check_pack_strips_bom_and_fixes_paths()
    check_path_rewrite()
    check_rewrite_declines()
    check_bare_name_is_warn_only()
    check_rewrite_leaves_valid_paths()
    print("ok")


if __name__ == "__main__":
    main()
