#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Gaokao-Math-Problems-Compilation 的 LaTeX 源转成知识库的 JSON 与 Markdown。

与 tools/import_tex.py 的区别：后者写入 PostgreSQL 且丢弃 solution；本工具面向
Obsidian 知识库（Markdown + Question JSON），保留答案与解析，供人工审校与评测。

用法：
    python tools/tex2kb.py --year 2012 --vault "C:/Users/Viver/Desktop/高中数学" --dry-run
    python tools/tex2kb.py --year 2012 --only anhui_science --vault ...

设计约束：
  * 未知 LaTeX 命令不静默丢弃，记入报告文件。
  * 原始 .tex 只读，不改写。
  * 输出命名遵循 10_Indexes/字段映射与ID规则.md。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

LICENSE = "CC BY-SA 4.0"
UPSTREAM = "DxAThing/Gaokao-Math-Problems-Compilation"

REGION_CN = {
    "anhui": "安徽", "beijing": "北京", "chongqing": "重庆", "fujian": "福建",
    "guangdong": "广东", "hubei": "湖北", "hunan": "湖南", "jiangsu": "江苏",
    "jiangxi": "江西", "liaoning": "辽宁", "shaanxi": "陕西", "shandong": "山东",
    "shanghai": "上海", "sichuan": "四川", "tianjin": "天津", "zhejiang": "浙江",
    "syllabus": "大纲", "new_curriculum": "新课标",
    "national_paper_1": "全国I", "national_paper_2": "全国II", "national_paper_3": "全国III",
    "national_paper_a": "全国甲", "national_paper_b": "全国乙",
    "new_curriculum_paper_1": "新课标I", "new_curriculum_paper_2": "新课标II",
    "new_gaokao_paper_1": "新高考I", "new_gaokao_paper_2": "新高考II",
}
KIND_CN = {"science": "理", "liberal": "文"}

SECTION_TYPE = {
    "单选题": "single_choice",
    "选择题": "single_choice",
    "多选题": "multi_choice",
    "填空题": "fill_blank",
    "选考题：填空题": "fill_blank",
    "选做题：填空题": "fill_blank",
    "附加题：填空题": "fill_blank",
    "解答题": "solution",
    "选考题：解答题": "solution",
    "选做题：解答题": "solution",
    "选考题": "solution",
    "选做题": "solution",
    "附加题": "solution",
    "附加题：选择题": "single_choice",
    "附加题：解答题": "solution",
}

# 语料里出现的自定义/排版命令 -> MathJax 可识别写法
REPLACERS = [
    (r"\\bs\{([^{}]*)\}", r"\\mathbf{\1}"),
    (r"\\symbfit\{([^{}]*)\}", r"\\boldsymbol{\1}"),
    (r"\\symbfup\{([^{}]*)\}", r"\\mathbf{\1}"),
    (r"\\symbf\{([^{}]*)\}", r"\\mathbf{\1}"),
    (r"\\myarc\{([^{}]*)\}", r"\\overset{\\frown}{\1}"),
    (r"\\degree", r"^{\\circ}"),
    (r"\\R(?![a-zA-Z])", r"\\mathbb{R}"),
    (r"\\Z(?![a-zA-Z])", r"\\mathbb{Z}"),
    (r"\\N(?![a-zA-Z])", r"\\mathbb{N}"),
    (r"\\i(?![a-zA-Z])", r"\\mathrm{i}"),
    (r"\\e(?![a-zA-Z])", r"\\mathrm{e}"),
    (r"\\d(?![a-zA-Z])", r"\\mathrm{d}"),
    (r"\\Pr(?![a-zA-Z])", r"P"),
    (r"\\tfrac", r"\\frac"),
    (r"\\quad", "　"),
    (r"\\bs\s+([A-Za-z0-9])", r"\\mathbf{\1}"),
    (r"\\bs([0-9])", r"\\mathbf{\1}"),
    (r"\\textasciitilde(?![A-Za-z])", "~"),
]

# 直接删除的排版命令（正则，必须带边界，否则 \par 会吃掉 \parallel 的前缀）
DROP_CMDS = [
    r"\\quad(?![A-Za-z])", r"\\qquad(?![A-Za-z])", r"\\enspace(?![A-Za-z])",
    r"\\allowbreak(?![A-Za-z])", r"\\relax(?![A-Za-z])", r"\\hfill(?![A-Za-z])",
    r"\\centering(?![A-Za-z])", r"\\small(?![A-Za-z])", r"\\FloatBarrier(?![A-Za-z])",
    r"\\begin\{center\}", r"\\end\{center\}", r"\\problembodyend(?![A-Za-z])",
    r"\\problemresetlayout(?![A-Za-z])", r"\\problemcenterstart(?![A-Za-z])",
    r"\\problemcenterend(?![A-Za-z])", r"\\noindent(?![A-Za-z])",
    r"\\indent(?![A-Za-z])", r"\\par(?![A-Za-z])", r"\\linewidth(?![A-Za-z])",
    r"\\textwidth(?![A-Za-z])", r"\\paperwidth(?![A-Za-z])",
    r"\\begingroup(?![A-Za-z])", r"\\endgroup(?![A-Za-z])",
    r"\\leftskip(?![A-Za-z])", r"\\rightskip(?![A-Za-z])",
    r"\\parindent(?![A-Za-z])", r"\\dimexpr(?![A-Za-z])",
    r"\\problembodyindent(?![A-Za-z])", r"\\footnotesize(?![A-Za-z])",
    r"\\tallpagetrue(?![A-Za-z])", r"\\tallpagefalse(?![A-Za-z])",
    r"\\hline(?![A-Za-z])", r"\\cline\{[^}]*\}",
]
DROP_WITH_ARG = [
    r"\hspace", r"\vspace", r"\setlength", r"\setcounter", r"\tabcolsep",
    r"\arraystretch", r"\FigureLayoutDeclare", r"\label", r"\vskip",
]

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"


class Converter:
    def __init__(self) -> None:
        self.figures: list[dict] = []
        self.unknown: dict[str, str] = {}
        self.tables = 0

    # ---------- 基础工具 ----------
    @staticmethod
    def read_group(s: str, i: int) -> tuple[str, int]:
        """从 s[i] == '{' 开始读一个平衡花括号组，返回内容与结束位置。"""
        assert s[i] == "{", s[max(0, i - 10):i + 10]
        depth = 0
        start = i + 1
        while i < len(s):
            ch = s[i]
            if ch == "\\":
                i += 2
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return s[start:i], i + 1
            i += 1
        raise ValueError("unbalanced braces")

    def replace_cmd_n(self, s: str, cmd: str, nargs: int, fmt) -> str:
        """循环替换多参数命令，fmt 收到参数列表返回替换文本。"""
        while True:
            m = re.search(re.escape(cmd) + r"\s*\{", s)
            if not m:
                return s
            i = m.end() - 1
            args = []
            try:
                for _ in range(nargs):
                    while i < len(s) and s[i] in " \t\n":
                        i += 1
                    if i >= len(s) or s[i] != "{":
                        return s
                    arg, i = self.read_group(s, i)
                    args.append(arg)
            except (AssertionError, ValueError):
                return s
            s = s[: m.start()] + fmt(args) + s[i:]

    def replace_cmd_arg(self, s: str, cmd: str, fmt: str) -> str:
        """循环把名为 cmd 的单参数命令替换成 fmt.format(arg)，支持嵌套花括号。"""
        while True:
            m = re.search(re.escape(cmd) + r"\s*\{", s)
            if not m:
                return s
            start = m.end() - 1
            try:
                arg, end = self.read_group(s, start)
            except (AssertionError, ValueError):
                return s
            s = s[: m.start()] + fmt.format(arg) + s[end:]

    def take_cmd_args(self, s: str, cmd: str, nargs: int) -> tuple[list[str], str]:
        """从字符串中取出 cmd 及其 nargs 个 {...} 参数，返回(参数列表, 剩余字符串)。
        只处理第一次出现。"""
        idx = s.find(cmd)
        if idx < 0:
            return [], s
        i = idx + len(cmd)
        while i < len(s) and s[i] in " \t\n":
            i += 1
        if i < len(s) and s[i] == "[":
            j = s.find("]", i)
            i = j + 1
            while i < len(s) and s[i] in " \t\n":
                i += 1
        args = []
        for _ in range(nargs):
            while i < len(s) and s[i] in " \t\n":
                i += 1
            if i >= len(s) or s[i] != "{":
                break
            arg, i = self.read_group(s, i)
            args.append(arg)
        return args, s[:idx] + s[i:]

    # ---------- 主转换 ----------
    def take_inline_cmd(self, s: str, cmd: str) -> tuple[str, str]:
        """取出一次 cmd{...}，返回(去掉该命令后的文本, 参数内容)。"""
        idx = s.find(cmd)
        if idx < 0:
            return s, ""
        i = idx + len(cmd)
        while i < len(s) and s[i] in " \t\n":
            i += 1
        arg, end = self.read_group(s, i)
        return s[:idx] + s[end:], arg

    def expand_local_macros(self, s: str) -> str:
        """展开文件内 \\newcommand{\\name}{简单定义} 的调用（不支持带参数的宏）。"""
        defs = {}
        for m in re.finditer(r"\\newcommand\{?\\([A-Za-z]+)\}?\s*\{", s):
            try:
                body, end = self.read_group(s, m.end() - 1)
            except (AssertionError, ValueError):
                continue
            defs[m.group(1)] = (body, m.start(), end)
        if not defs:
            return s
        for name, (body, start, end) in sorted(defs.items(), key=lambda kv: -kv[1][1]):
            s = s[:start] + s[end:]
            s = re.sub(r"\\" + name + r"(?![A-Za-z])", lambda _m, b=body: b, s)
        return s

    def strip_wrapper(self, s: str, cmd: str, nargs: int, keep: int = -1) -> str:
        """剥掉纯排版包装命令，保留 keep 指定的参数（默认最后一个）。"""
        while True:
            i = s.find(cmd)
            if i < 0:
                return s
            j = i + len(cmd)
            while True:
                k = j
                while k < len(s) and s[k] in " \t\n":
                    k += 1
                if k < len(s) and s[k] == "[":
                    close = s.find("]", k)
                    if close < 0:
                        return s
                    j = close + 1
                else:
                    j = k
                    break
            args = []
            try:
                for _ in range(nargs):
                    while j < len(s) and s[j] in " \t\n":
                        j += 1
                    if j >= len(s) or s[j] != "{":
                        return s
                    arg, j = self.read_group(s, j)
                    args.append(arg)
            except (AssertionError, ValueError):
                return s
            s = s[:i] + (args[keep] if args else "") + s[j:]

    def convert(self, body: str) -> str:
        s = body

        # 图形
        for cmd, nargs, kind in (
            (r"\bitmapfigure", 1, "bitmap"),
            (r"\sourcefigure", 1, "bitmap"),
            (r"\texfigure", 1, "tex"),
            (r"\choicebitmap", 1, "bitmap"),
            (r"\choicetexfigure", 1, "tex"),
            (r"\bitmapinclude", 1, "bitmap"),
            (r"\texinclude", 1, "tex"),
            (r"\solutionfigure", 1, "solution"),
        ):
            while cmd in s:
                args, s = self.take_cmd_args(s, cmd, nargs)
                if not args:
                    break
                if args[0].strip():
                    self.figures.append({"kind": kind, "path": args[0].strip(), "usage": cmd.lstrip("\\")})

        # 纯排版包装：只保留内容
        for cmd, nargs in ((r"\examfiguregroup", 2), (r"\makebox", 1), (r"\adjustbox", 2),
                           (r"\resizebox", 3), (r"\parbox", 2)):
            s = self.strip_wrapper(s, cmd, nargs)

        # 文件内 \newcommand 定义的简单宏：先用定义体替换调用
        s = self.expand_local_macros(s)

        # 表格
        while r"\begin{tabular}" in s:
            m = re.search(r"\\begin\{tabular\}(\{[^}]*\})(.*?)\\end\{tabular\}", s, re.S)
            if not m:
                break
            self.tables += 1
            table = self.table_to_md(m.group(2))
            s = s[: m.start()] + "\n\n" + table + "\n\n" + s[m.end():]

        # 列表
        s = self.enumerate_to_md(s)

        # 数学定界符
        s = s.replace(r"\[", "$$").replace(r"\]", "$$")
        s = s.replace(r"\(", "$").replace(r"\)", "$")
        s = s.replace(r"$$$$", "$$")

        # \binom 在样式里被重定义为 C_n^m
        s = self.binom_to_c(s)

        # 单参数自定义命令（支持嵌套花括号）
        for cmd, fmt in (
            (r"\bs", r"\mathbf{{{}}}"),
            (r"\symbfit", r"\boldsymbol{{{}}}"),
            (r"\symbfup", r"\mathbf{{{}}}"),
            (r"\symbf", r"\mathbf{{{}}}"),
            (r"\myarc", r"\overset{{\frown}}{{{}}}"),
        ):
            s = self.replace_cmd_arg(s, cmd, fmt)

        # 展示型公式包装
        s = self.replace_cmd_n(
            s, r"\examdisplaycases", 2,
            lambda a: "$$" + a[0] + r"\begin{cases}" + a[1] + r"\end{cases}$$")
        s = self.replace_cmd_n(
            s, r"\examdisplayarray", 4,
            lambda a: "$$" + a[0] + r"\begin{array}{" + a[1] + "}" + a[2] + r"\end{array}" + a[3] + "$$")
        s = self.replace_cmd_n(
            s, r"\examdisplayaligned", 1,
            lambda a: "$$" + r"\begin{aligned}" + a[0] + r"\end{aligned}" + "$$")
        s = re.sub(r"\\rm(?![A-Za-z])", r"\\mathrm", s)

        # 非选项场合的 circlelist（如填空题的 ①②③ 命题）-> 逐行编号文本
        def circlelist_to_lines(m: re.Match) -> str:
            items = [x.strip() for x in re.split(r"\\item", m.group(1)) if x.strip()]
            out = []
            for idx, it in enumerate(items):
                mark = CIRCLED[idx] if idx < len(CIRCLED) else f"（{idx + 1}）"
                out.append(f"{mark} {self.convert(it)}")
            return "\n\n" + "\n\n".join(out) + "\n\n"

        s = re.sub(r"\\begin\{circlelist\}(.*?)\\end\{circlelist\}", circlelist_to_lines, s, flags=re.S)

        # 圈号
        def circ(m: re.Match) -> str:
            n = int(m.group(1))
            return CIRCLED[n - 1] if 1 <= n <= len(CIRCLED) else f"（{n}）"

        s = re.sub(r"\\circled\{(\d+)\}", circ, s)

        # 自定义命令
        for pat, rep in REPLACERS:
            s = re.sub(pat, rep, s)

        # 空白
        s = s.replace(r"\fillinblank", "______")
        s = s.replace("~", " ")

        # 带参数的排版命令
        for cmd in DROP_WITH_ARG:
            while True:
                args, new = self.take_cmd_args(s, cmd, 1)
                if not args or new == s:
                    break
                s = new

        # 无参数排版命令（正则边界替换，避免吃掉 \parallel 之类的前缀）
        for pat in DROP_CMDS:
            s = re.sub(pat, "", s)

        # \multicolumn{n}{fmt}{content} -> content
        while r"\multicolumn" in s:
            args, new = self.take_cmd_args(s, r"\multicolumn", 3)
            if len(args) != 3:
                break
            s = new.replace("@@MULTI@@", "")
            s = s  # 位置信息丢失，退回正则处理
            break
        s = re.sub(r"\\multicolumn\{\d+\}\{[^{}]*\}\{([^{}]*)\}", r"\1", s)

        # 带 2 个参数的排版命令（\renewcommand{\arraystretch}{1.2} 之类）
        for cmd in (r"\renewcommand", r"\newcommand"):
            while True:
                args, new = self.take_cmd_args(s, cmd, 2)
                if len(args) != 2 or new == s:
                    break
                s = new

        # 剩余未知命令（(?!<=\\) 避免把换行 \\y 误判成命令）
        for m in re.finditer(r"(?<!\\)\\([A-Za-z]+)", s):
            name = m.group(1)
            if name not in KNOWN_CMDS:
                self.unknown.setdefault(name, s[max(0, m.start() - 40): m.start() + 40])

        s = self.tidy(s)
        return s

    def binom_to_c(self, s: str) -> str:
        for cmd in (r"\binom", r"\dbinom", r"\tbinom"):
            while cmd in s:
                args, new = self.take_cmd_args(s, cmd, 2)
                if len(args) != 2 or new == s:
                    break
                s = new.replace("@@BINOM@@", "")  # placeholder no-op
                # 重新插入转换结果到原位置
                s = s  # 位置信息在 take_cmd_args 里丢失，改用正则替换
                break
        s = re.sub(r"\\binom\{([^{}]*)\}\{([^{}]*)\}", r"\\mathrm{C}_{{\1}}^{{\2}}", s)
        s = re.sub(r"\\dbinom\{([^{}]*)\}\{([^{}]*)\}", r"\\mathrm{C}_{{\1}}^{{\2}}", s)
        return s

    def enumerate_to_md(self, s: str) -> str:
        out = []
        pos = 0
        for m in re.finditer(r"\\begin\{enumerate\}(.*?)\\end\{enumerate\}", s, re.S):
            out.append(s[pos:m.start()])
            body = m.group(1)
            items = [x.strip() for x in re.split(r"\\item", body) if x.strip()]
            lines = []
            for i, it in enumerate(items, 1):
                lines.append(f"（{i}）{it}")
            out.append("\n\n" + "\n\n".join(lines) + "\n\n")
            pos = m.end()
        out.append(s[pos:])
        return "".join(out)

    def table_to_md(self, body: str) -> str:
        body = re.sub(r"\\(hline|cline\{[^}]*\}|toprule|midrule|bottomrule)", "", body)
        body = body.replace(r"\arraystretch", "")
        rows = [r.strip() for r in re.split(r"\\\\", body) if r.strip()]
        md_rows = []
        for row in rows:
            cells = [c.strip() for c in row.split("&")]
            md_rows.append("| " + " | ".join(cells) + " |")
        if not md_rows:
            return ""
        width = md_rows[0].count("|") - 1
        table = [md_rows[0], "|" + " --- |" * width] + md_rows[1:]
        return "\n".join(table)

    @staticmethod
    def tidy(s: str) -> str:
        s = re.sub(r"[ \t]+\n", "\n", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        s = re.sub(r"[ \t]{2,}", " ", s)
        return s.strip()


# MathJax 认识的常用命令（用于未知命令报告，不求完备，只求不漏自定义宏）
KNOWN_CMDS = set("""
frac dfrac sqrt left right cdot cdots ldots dots times div pm mp le leq ge geq neq ne
in notin ni subset subseteq subsetneq cup cap setminus varnothing emptyset complement
infty alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu
nu xi pi varpi rho sigma tau upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi
Sigma Upsilon Phi Psi Omega
sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh log ln lg exp lim max min det
sum prod int iint iiint oint bigcup bigcap bigvee bigwedge bigoplus bigotimes bigodot
overrightarrow overline underline hat widehat bar vec dot ddot tilde
langle rangle lvert rvert lVert rVert mid parallel perp angle triangle square circ degree
mathrm mathbf mathbb mathcal mathit mathsf mathtt boldsymbol bm text textbf textit
begin end item label tag nonumber quad qquad enspace hspace vspace
displaystyle textstyle scriptstyle limits nolimits
leftarrow rightarrow leftrightarrow Longleftrightarrow Longrightarrow iff implies to mapsto longmapsto
forall exists neg lnot land lor wedge vee oplus otimes odot ast star bullet
pmod bmod gcd lcm operatorname overbrace underbrace stackrel overset underset
cdots vdots ddots prime backslash colon
binom choose atop above
leqslant geqslant nleqslant ngeqslant
lfloor rfloor lceil rceil
therefore because
mathrm mathord mathbin mathrel mathop mathopen mathclose mathpunct mathinner
symbf symbfit symbfup
boxed bigl bigr bigg Bigl Bigr sim approx equiv not frown Rightarrow
parallel nparallel longrightarrow Longleftarrow nearrow searrow ell
sup inf nabla partial propto diamond cong nsubseteq nmid smallsetminus coth
big Big middle
FIGURE figure caption
""".split())


def parse_paper(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?<!\\)%.*", "", text)

    chapter = re.search(r"\\chapter\{([^}]*)\}", text)
    title = chapter.group(1) if chapter else path.stem
    year = int(re.search(r"(19|20)\d{2}", title).group(0)) if re.search(r"(19|20)\d{2}", title) else int(path.parent.name)

    stem = path.stem
    kind = ""
    base = stem
    for suffix, cn in (("_science", "sci"), ("_liberal", "arts")):
        if stem.endswith(suffix):
            base = stem[: -len(suffix)]
            kind = cn
    doc_id = f"gk_{year}_{base}" + (f"_{kind}" if kind else "")

    # 按 section 切块
    parts = re.split(r"\\section\{([^}]*)\}", text)
    sections = []
    for i in range(1, len(parts), 2):
        name = parts[i].strip()
        sections.append((name, parts[i + 1]))

    conv = Converter()
    questions = []
    num = 0
    for name, chunk in sections:
        qtype = SECTION_TYPE.get(name)
        if not qtype:
            continue
        pos = 0
        while True:
            m = re.search(r"\\begin\{problem\}", chunk[pos:])
            if not m:
                break
            start = pos + m.end()
            endm = re.search(r"\\end\{problem\}", chunk[start:])
            if not endm:
                break
            body = chunk[start:start + endm.start()]
            after = start + endm.end()

            ans = sol = ""
            am = re.search(r"\\begin\{answer\}(.*?)\\end\{answer\}", chunk[after:], re.S)
            sm = re.search(r"\\begin\{solution\}(.*?)\\end\{solution\}", chunk[after:], re.S)
            if am and (sm is None or am.start() < sm.start()):
                ans = am.group(1)
            if sm:
                sol = sm.group(1)

            # 行内 \answer{...} 写法：取出来当答案，从题干里删掉
            inline_ans = ""
            if r"\answer{" in body:
                try:
                    body, inline_ans = conv.take_inline_cmd(body, r"\answer")
                except (AssertionError, ValueError):
                    pass
                if inline_ans and not ans.strip():
                    ans = inline_ans

            if r"\reuseproblemnumber" in body:
                num = max(1, num)
            else:
                num += 1

            # 选项
            options = []
            fig_start = len(conv.figures)  # 图形归属从选项就开始计
            cm = re.search(r"\\choices(five)?\s*\{", body)
            circ = re.search(r"\\begin\{circlelist\}", body)
            if cm:
                nargs = 5 if cm.group(1) else 4
                args, rest = conv.take_cmd_args(body, r"\choicesfive" if nargs == 5 else r"\choices", nargs)
                body = rest
                labels = "ABCDE"[: len(args)]
                for lab, arg in zip(labels, args):
                    options.append({"label": lab, "content": conv.convert(arg)})
            elif circ and qtype in ("single_choice", "multi_choice"):
                m2 = re.search(r"\\begin\{circlelist\}(.*?)\\end\{circlelist\}", body, re.S)
                if m2:
                    inner = m2.group(1)
                    body = body[: m2.start()] + body[m2.end():]
                    items = [x.strip() for x in re.split(r"\\item", inner) if x.strip()]
                    for idx, it in enumerate(items):
                        options.append({"label": CIRCLED[idx] if idx < len(CIRCLED) else str(idx + 1),
                                        "content": conv.convert(it)})

            stem_md = conv.convert(body)
            ans_md = conv.convert(ans) if ans else ""
            sol_md = conv.convert(sol) if sol else ""

            qid = f"{doc_id}_q{num:02d}"
            q_figs = conv.figures[fig_start:]
            for i, f in enumerate(q_figs, 1):
                f["figure_id"] = f"{qid}_f{i}"
                f["question_id"] = qid
            questions.append({
                "question_id": qid,
                "document_id": doc_id,
                "question_number": str(num),
                "question_type": qtype,
                "section": name,
                "score": None,
                "stem": stem_md,
                "options": options,
                "answer": ans_md,
                "solution": sol_md,
                "figures": [f["figure_id"] for f in q_figs],
            })
            pos = after

    return {
        "document_id": doc_id,
        "title": title,
        "year": year,
        "source_tex": str(path),
        "license": LICENSE,
        "upstream": UPSTREAM,
        "count": len(questions),
        "questions": questions,
        "figures": conv.figures,
        "tables": conv.tables,
        "unknown": conv.unknown,
    }


SPECIAL = {
    "shanghai_spring": {"region": "上海", "kind_cn": "春", "folder": "上海-春季"},
}


def paper_meta(paper: dict) -> dict:
    stem = paper["source_tex"]
    name = pathlib.Path(stem).stem
    if name in SPECIAL:
        sp = SPECIAL[name]
        return {"label": f"{paper['year']}{sp['region']}{sp['kind_cn']}",
                "folder": sp["folder"], "region_cn": sp["region"], "kind": ""}
    kind = ""
    base = name
    for suffix, cn in (("_science", "sci"), ("_liberal", "arts")):
        if name.endswith(suffix):
            base = name[: -len(suffix)]
            kind = cn
    region_cn = REGION_CN.get(base, base)
    kind_cn = {"sci": "理", "arts": "文"}.get(kind, "")
    label = f"{paper['year']}{region_cn}{kind_cn}"
    folder = region_cn + ("-" + {"sci": "理科", "arts": "文科"}[kind] if kind else "")
    return {"label": label, "folder": folder, "region_cn": region_cn, "kind": kind}


def schema_question(q: dict, paper: dict) -> dict:
    return {
        "question_id": q["question_id"],
        "document_id": q["document_id"],
        "question_number": q["question_number"],
        "question_type": q["question_type"],
        "score": None,
        "stem": q["stem"],
        "stem_latex": [],
        "options": [{"label": o["label"], "content": o["content"]} for o in q["options"]],
        "answer": {"content": q["answer"], "status": "machine_extracted" if q["answer"] else "pending"},
        "solution": {"content": q["solution"], "status": "machine_extracted" if q["solution"] else "pending"},
        "figures": q.get("figures", []),
        "knowledge_points": [],
        "methods": [],
        "difficulty": None,
        "source": {"page_start": None, "page_end": None, "region": None},
        "quality": {"ocr_status": "needs_review", "text_confidence": None,
                    "formula_confidence": None, "human_verified": False},
        "human_edited": False,
    }


def write_question_md(path: pathlib.Path, q: dict, label: str, paper: dict) -> None:
    fm = [
        "---",
        f"question_id: {q['question_id']}",
        f"document_id: {q['document_id']}",
        f'question_number: "{q["question_number"]}"',
        f"question_type: {q['question_type']}",
        "score: null",
        "stem_latex: []",
        "figures: [" + ", ".join(q.get("figures", [])) + "]",
        "knowledge_points: []",
        "methods: []",
        "difficulty: null",
        "source:",
        "  page_start: null",
        "  page_end: null",
        "  region: null",
        "quality:",
        "  ocr_status: needs_review",
        "  text_confidence: null",
        "  formula_confidence: null",
        "  human_verified: false",
        "human_edited: false",
        "---",
        "",
    ]
    body = [f"# 第 {q['question_number']} 题 · {label}", "",
            f"> 出自 [[{label}]] 第 {q['question_number']} 题 ｜ 机转自 {paper['upstream']}（{paper['license']}）", "",
            "## 题目", "", q["stem"], ""]
    if q["options"]:
        body += ["## 选项", ""]
        for o in q["options"]:
            body.append(f"- **{o['label']}.** {o['content']}")
        body.append("")
    body += ["## 答案", "", q["answer"].strip() or "> 源文件无答案。", "",
             "## 解析", "", q["solution"].strip() or "> 源文件无解析。", ""]
    by_id = {f.get("figure_id"): f for f in paper.get("figures", [])}
    own = [by_id[i] for i in q.get("figures", []) if i in by_id]
    if own:
        body += ["## 图形引用", "",
                 "> 源文件图形（仓库 `img/` 下已存在，尚未导入 `09_Assets`）：", ""]
        for f in own:
            body.append(f"- `{f['path']}`（`{f['figure_id']}`）")
        body.append("")
    body += ["## 校核", "",
             "- [x] 由 LaTeX 源机转（非 OCR）",
             "- [ ] 人工核对题干与公式",
             "- [ ] 答案已核对",
             ""]
    path.write_text("\n".join(fm) + "\n".join(body), encoding="utf-8")


def write_document_md(path: pathlib.Path, paper: dict, meta: dict) -> None:
    qs = paper["questions"]
    single = sum(1 for q in qs if q["question_type"] == "single_choice")
    multi = sum(1 for q in qs if q["question_type"] == "multi_choice")
    fill = sum(1 for q in qs if q["question_type"] == "fill_blank")
    sol = sum(1 for q in qs if q["question_type"] == "solution")
    with_ans = sum(1 for q in qs if q["answer"])
    fm = [
        "---",
        f'document_id: {paper["document_id"]}',
        f'title: "{paper["title"]}"',
        "document_type: gaokao",
        "subject: 数学",
        "stage: 高中",
        f'year: {paper["year"]}',
        f'region: "{meta["region_cn"]}"',
        f'paper_type: "{paper["title"]}"',
        f'paper_kind: "{ {"sci": "理科", "arts": "文科"}.get(meta["kind"], "") }"',
        "score_total: null",
        "page_count: null",
        f"source_tex: {paper['source_tex'].replace(chr(92), '/')}",
        "language: zh-CN",
        "ocr_status: native_text",
        "processing_status: needs_review",
        f'rights_note: "{paper["upstream"]} / {paper["license"]}"',
        "human_edited: false",
        "---",
        "",
    ]
    body = [f"# {paper['title']}", "",
            "> 返回 [[真题总览]] ｜ 数据由 LaTeX 源机转，未经人工逐题核对", "",
            "## 结构", "",
            "| 题型 | 题量 |", "| --- | --- |",
            f"| 单项选择 | {single} |", f"| 多项选择 | {multi} |",
            f"| 填空 | {fill} |", f"| 解答 | {sol} |", "",
            f"含答案的题目：{with_ans} / {len(qs)}", "",
            "## 题目清单", ""]
    for q in qs:
        body.append(f"- [[{meta['label']}-q{int(q['question_number']):02d}]]")
    body += ["", "## 来源与许可", "",
             f"- 来源仓库：`{UPSTREAM}`",
             f"- 许可：{LICENSE}（署名 + 相同方式共享）",
             f"- 源文件：`{paper['source_tex']}`",
             "",
             "## 备注", "",
             "- 公式取自 LaTeX 源，未经 OCR，无损",
             "- 图形在源仓库 `img/` 目录（已取得），逐题引用见各题卡 `figures`",
             ""]
    path.write_text("\n".join(fm) + "\n".join(body), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", default=r"D:\Chilon\var\_tex_clone\repo\content")
    ap.add_argument("--year", type=int, default=2012)
    ap.add_argument("--only", default="")
    ap.add_argument("--vault", default=r"C:\Users\Viver\Desktop\高中数学")
    ap.add_argument("--out", default="")
    ap.add_argument("--write", action="store_true", help="写入 vault")
    ap.add_argument("--preserve", default="", help="逗号分隔的文件名主干，只导出 JSON 不写 Markdown")
    ap.add_argument("--report", default="")
    args = ap.parse_args()

    root = pathlib.Path(args.content) / str(args.year)
    files = sorted(root.glob("*.tex"))
    if args.only:
        files = [f for f in files if f.stem == args.only]
    if not files:
        print("no .tex found", file=sys.stderr)
        return 2

    preserve = {x.strip() for x in args.preserve.split(",") if x.strip()}
    vault = pathlib.Path(args.vault)
    papers = []
    written = 0
    for f in files:
        p = parse_paper(f)
        papers.append(p)
        meta = paper_meta(p)
        print(f"{f.stem:28s} {p['title']:30s} 题={p['count']:3d} 图={len(p['figures']):2d} 未知={len(p['unknown'])}")

        if not args.write:
            continue
        json_dir = vault / "02_Processed" / "OCR_JSON" / p["document_id"]
        json_dir.mkdir(parents=True, exist_ok=True)
        bundle = {
            "schema_version": "v1.2-2026-11-05",
            "document_id": p["document_id"],
            "generated_by": "tools/tex2kb.py from LaTeX source (no OCR)",
            "license": p["license"],
            "upstream": p["upstream"],
            "source_tex": p["source_tex"].replace("\\", "/"),
            "questions": [schema_question(q, p) for q in p["questions"]],
            "sub_questions": [],
            "figures": p["figures"],
        }
        fname = "tex.json" if f.stem in preserve else "questions.json"
        (json_dir / fname).write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

        if f.stem in preserve:
            print(f"    ↳ 保留手抄题卡，仅导出 {fname}")
            continue

        out_dir = vault / "04_Exams" / "Gaokao" / str(p["year"]) / meta["folder"]
        out_dir.mkdir(parents=True, exist_ok=True)
        write_document_md(out_dir / f"{meta['label']}.md", p, meta)
        for q in p["questions"]:
            write_question_md(out_dir / f"{meta['label']}-q{int(q['question_number']):02d}.md", q, meta["label"], p)
        written += len(p["questions"])

    unknown = sorted({u for p in papers for u in p["unknown"]})
    print("\n试卷:", len(papers), "｜ 题数:", sum(p["count"] for p in papers), "｜ 写入题卡:", written)
    print("未识别命令:", unknown if unknown else "无")

    if args.report:
        pathlib.Path(args.report).write_text(
            json.dumps({"year": args.year, "papers": len(papers),
                        "questions": sum(p["count"] for p in papers),
                        "written": written, "unknown": unknown,
                        "per_paper": [{"id": p["document_id"], "count": p["count"],
                                       "answers": sum(1 for q in p["questions"] if q["answer"])}
                                      for p in papers]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
