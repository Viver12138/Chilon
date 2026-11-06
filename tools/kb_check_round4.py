# -*- coding: utf-8 -*-
"""第四轮抽检（模块层）回收脚本：读回填 xlsx → 对比 02_Processed\\Annotations → 出数据报告。

用法（python 用 PATH 里的 python，带 openpyxl）：
    python D:\\Chilon\\tools\\kb_check_round4.py "C:\\...\\抽检_第四轮_真人填写_2026-11-06_已填.xlsx"
    python D:\\Chilon\\tools\\kb_check_round4.py <xlsx> --check        # 只看是否已填，不写报告
    python D:\\Chilon\\tools\\kb_check_round4.py <xlsx> --dry-run      # 只打印将写路径与摘要
    python D:\\Chilon\\tools\\kb_check_round4.py <xlsx> --out D:\\some\\dir --label "自测（合成数据，非真人）"

设计约束
- 只判模块层：17 个模块 id（也容忍模块中文名 / 误填的考点 kp_id）
- 报告默认写到 11_Spotcheck\\第四轮_真人\\，文件名一律以「回收_」开头；
  从不写/改任何非「回收_」前缀的文件，因此不会覆盖人工结论。
- 未填满或全部空白时不生成报告（退出码 2 = 等待真实教师填写）。
- 自测数据必须用 --label 标明；文件名/路径含 selftest 时自动标注。

退出码：0 成功；2 无有效填写（等待真人填写）；3 输入/格式问题。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import re
import sys
import unicodedata

from openpyxl import load_workbook

V = pathlib.Path(r'C:\Users\Viver\Desktop\高中数学')
ANN_DIR = V / '02_Processed' / 'Annotations'
VOCAB = V / '10_Indexes' / '知识点词表.md'
DEFAULT_OUT = V / '11_Spotcheck' / '第四轮_真人'
DEFAULT_XLSX = DEFAULT_OUT / '抽检_第四轮_真人填写_2026-11-06.xlsx'
SAMPLE = V / '11_Spotcheck' / 'sample_100_round3.json'

TYPE_CN = {'single_choice': '单选', 'multi_choice': '多选', 'fill_blank': '填空', 'solution': '解答'}
NO_ATTR_RAW = {'无', '无归属', '无法归类', '无模块', '不确定', '不清楚', '?', '？', '—', '-', '/', 'none', 'n/a'}
KP_RE = re.compile(r'(kp_\d\d_\d\d_[a-z_]+)')
QID_RE = re.compile(r'^gk_\d{4}_.+_q\d+$')


# ---------------------------------------------------------------- 词表 / 标注
def load_vocab():
    """返回 (modules[(id,name,era)], kp_title{id:名称}, mod_num{两位:模块id}, name2id{名称:模块id})。"""
    lines = VOCAB.read_text(encoding='utf-8').splitlines()
    modules = []
    for line in lines:
        m = re.match(r'^##\s*(\d+)\.\s*(.+?)[（(].*?`(kp_\d\d_[a-z_]+)`', line)
        if m:
            head = line[:line.find('`')] if '`' in line else line
            era = '旧课标' if '旧课标' in head else ''
            modules.append((m.group(3), re.sub(r'^旧课标[，,]\s*', '', m.group(2)).strip(), era))
    titles = {}
    for line in lines:
        m = re.match(r'\|\s*`(kp_\d\d_\d\d_[a-z_]+)`\s*\|\s*([^|]+)\|', line)
        if m:
            titles[m.group(1)] = m.group(2).strip()
    mod_num = {mid.split('_')[1]: mid for mid, _, _ in modules}
    name2id = {name: mid for mid, name, _ in modules}
    # 常见别名，方便老师手输
    name2id.update({
        '集合与逻辑': 'kp_01_set_logic', '函数与导数': '',  # 占位不生效
        '三角函数': 'kp_04_trig', '解三角形': 'kp_04_trig',
        '立体几何与空间向量': 'kp_08_solid', '解析几何与圆锥曲线': 'kp_09_analytic',
        '概率统计': 'kp_10_prob_stat', '概率与统计': 'kp_10_prob_stat',
        '算法': 'kp_14_algorithm', '程序框图': 'kp_14_algorithm',
        '平面几何': 'kp_15_plane_geometry', '几何证明选讲': 'kp_15_plane_geometry',
        '极限': 'kp_16_limit', '矩阵': 'kp_17_matrix', '矩阵与变换': 'kp_17_matrix',
        '定积分': 'kp_18_integral',
    })
    name2id.pop('函数与导数', None)
    return modules, titles, mod_num, name2id


def load_annotations():
    ann = {}
    for j in sorted(ANN_DIR.glob('gk_*.json')):
        b = json.loads(j.read_text(encoding='utf-8'))
        for it in b.get('items', []):
            if it.get('question_id'):
                ann[it['question_id']] = it.get('annotation') or {}
    return ann


# ---------------------------------------------------------------- 归一化
def norm(s) -> str:
    """全角→半角、去空白/反引号，便于匹配手输内容。"""
    if s is None:
        return ''
    t = unicodedata.normalize('NFKC', str(s)).strip()
    t = t.replace('`', '').replace('\u3000', ' ')
    t = re.sub(r'\s+', ' ', t)
    return t.strip()


def module_of_kp(kp: str, mod_num: dict) -> str:
    if not kp or not kp.startswith('kp_'):
        return ''
    return mod_num.get(kp.split('_')[1], '')


def resolve_judgement(raw, mod_num, name2id):
    """把老师填的值解析成 ('module', id) / ('noattr', '') / ('blank', '') / ('invalid', 原文)。"""
    t = norm(raw)
    if not t:
        return 'blank', ''
    low = t.lower().replace('（', '(').replace('）', ')')
    if low in NO_ATTR_RAW or t in NO_ATTR_RAW:
        return 'noattr', ''
    if re.fullmatch(r'kp_\d\d_[a-z_]+', low):          # 模块 id
        return ('module', low) if low in mod_num.values() else ('invalid', t)
    if KP_RE.fullmatch(low):                            # 误填了具体考点 id → 提升到模块
        mid = module_of_kp(low, mod_num)
        return ('module', mid) if mid else ('invalid', t)
    # 模块中文名（允许去掉「模块」「（旧课标）」等后缀）
    cand = re.sub(r'[（(].*?[）)]', '', t)
    if cand in NO_ATTR_RAW:
        return 'noattr', ''
    for key in (t, cand):
        key2 = key.replace('模块', '').strip()
        if key2 in name2id:
            return 'module', name2id[key2]
    # 中文名 + 模型 id 混写，如「解析几何 kp_09_analytic」
    m = KP_RE.search(low)
    if m:
        mid = module_of_kp(m.group(1), mod_num)
        if mid:
            return 'module', mid
    return 'invalid', t


def type_cn(t: str) -> str:
    t = norm(t)
    return TYPE_CN.get(t, t or '—')


# ---------------------------------------------------------------- 读回填件
SHEET_CANDIDATES = ('抽检清单', '抽检', '清单', '盲评')


def read_filled(path: pathlib.Path):
    try:
        wb = load_workbook(path, data_only=True, read_only=True)
    except PermissionError:
        raise SystemExit(f'[错误] 文件被占用或无权读取：{path}\n请先在 Excel 里保存并关闭再运行。')
    except Exception as e:  # noqa: BLE001 - 给出可操作提示
        raise SystemExit(f'[错误] 无法打开工作簿：{path}\n{e}')

    ws = None
    for cand in SHEET_CANDIDATES:
        if cand in wb.sheetnames:
            ws = wb[cand]
            break
    if ws is None:  # 退而求其次：找带 qid 表头的表
        for name in wb.sheetnames:
            s = wb[name]
            head = [norm(c.value) for c in next(s.iter_rows(min_row=1, max_row=1))]
            if any(h.lower() == 'qid' for h in head):
                ws = s
                break
    if ws is None:
        raise SystemExit('[错误] 没找到「抽检清单」表（也找不到含 qid 表头的表），请确认文件是本轮材料。')

    rows = list(ws.iter_rows(values_only=True))
    hdr_i = None
    for i, row in enumerate(rows[:6]):
        hs = [norm(v).lower() for v in row]
        if 'qid' in hs:
            hdr_i = i
            break
    if hdr_i is None:
        raise SystemExit('[错误] 「抽检清单」表缺少 qid 列。')
    hdr = [norm(v) for v in rows[hdr_i]]

    def col(*names, contains=None):
        for i, h in enumerate(hdr):
            hl = h.lower()
            if hl in names or (contains and contains in hl):
                return i
        return None

    c_qid = col('qid')
    c_mod = next((i for i, h in enumerate(hdr) if '模块' in h), None)
    c_year = col('年份')
    c_type = col('类型', '题型')
    c_note = col('备注')
    c_stem = col('题干')
    if c_qid is None or c_mod is None:
        raise SystemExit('[错误] 表头里找不到 qid 或「模块」列，请确认填的是「模块」列（不是考点列）。')

    out = []
    for r in rows[hdr_i + 1:]:
        if not r or c_qid >= len(r):
            continue
        qid = norm(r[c_qid] if c_qid < len(r) else None)
        if not qid:
            continue
        def get(i):
            return r[i] if i is not None and i < len(r) else None
        out.append({
            'qid': qid,
            'module_raw': get(c_mod),
            'year': norm(get(c_year)),
            'type': type_cn(get(c_type)),
            'note': norm(get(c_note)),
            'stem': norm(get(c_stem)),
        })
    wb.close()
    if not out:
        raise SystemExit('[错误] 「抽检清单」表没有任何数据行。')
    return out, ws.title


# ---------------------------------------------------------------- 统计
def analyse(filled, ann, modules, titles, mod_num, name2id):
    order = [m[0] for m in modules]
    mod_name = {m[0]: m[1] for m in modules}
    ai_mod = {q: module_of_kp((a or {}).get('kp_primary') or '', mod_num) for q, a in ann.items()}
    ai_kp = {q: (a or {}).get('kp_primary') or '' for q, a in ann.items()}

    recs = []
    n_blank = n_invalid = n_judged = 0
    invalid, blank = [], []
    for i, row in enumerate(filled):
        kind, val = resolve_judgement(row['module_raw'], mod_num, name2id)
        row = dict(row)
        row['seq'] = i + 1
        row['kind'] = kind
        if kind == 'blank':
            n_blank += 1
            blank.append(row)
        elif kind == 'invalid':
            n_invalid += 1
            invalid.append(row)
        else:
            n_judged += 1
            teacher_mod = val if kind == 'module' else ''
            ai = ai_mod.get(row['qid'], '')
            row.update(teacher_mod=teacher_mod, ai_mod=ai, ai_kp=ai_kp.get(row['qid'], ''),
                       match=(teacher_mod == ai))
            recs.append(row)

    n = len(recs)
    n_match = sum(1 for r in recs if r['match'])
    rate = (n_match / n * 100) if n else 0.0

    # --- 错位诊断：第 i 行填的值与第 i+s 行的 AI 标注比 ---
    shifts = {}
    for s in range(-2, 3):
        ok = tot = 0
        for i, row in enumerate(filled):
            j = i + s
            if 0 <= j < len(filled):
                kind, val = resolve_judgement(filled[i]['module_raw'], mod_num, name2id)
                if kind == 'blank' or kind == 'invalid':
                    continue
                tm = val if kind == 'module' else ''
                tot += 1
                if tm == ai_mod.get(filled[j]['qid'], ''):
                    ok += 1
        shifts[s] = (ok, tot, (ok / tot * 100) if tot else 0.0)
    warn_shift = None
    for s in (-1, 1, -2, 2):
        ok, tot, pct = shifts[s]
        if tot and pct >= 20 and pct >= rate + 15:
            warn_shift = s
            break

    # --- 按年份 / 题型 ---
    def group(key):
        d = {}
        for r in recs:
            k = r[key] or '—'
            g = d.setdefault(k, [0, 0])
            g[0] += 1
            g[1] += 1 if r['match'] else 0
        return [(k, *v) for k, v in sorted(d.items())]

    by_year = [(k, n_, ok, ok / n_ * 100) for k, n_, ok in group('year')]
    by_type = [(k, n_, ok, ok / n_ * 100) for k, n_, ok in group('type')]

    # --- 模块分布对照 ---
    mod_dist = []
    for mid in order:
        ai_n = sum(1 for r in recs if r['ai_mod'] == mid)
        t_n = sum(1 for r in recs if r['teacher_mod'] == mid)
        both = sum(1 for r in recs if r['ai_mod'] == mid and r['teacher_mod'] == mid)
        mod_dist.append((mid, mod_name[mid], ai_n, t_n, both))

    # --- 分歧清单 ---
    diffs = []
    for r in recs:
        if r['match']:
            continue
        if not r['teacher_mod']:
            kind = '教师判「无法归类」'
        elif not r['ai_mod']:
            kind = 'AI 标注无归属'
        else:
            kind = '模块不一致'
        diffs.append((r['seq'], r['qid'], r['year'], r['type'],
                      mod_name.get(r['teacher_mod'], '无归属'), mod_name.get(r['ai_mod'], '无归属'),
                      titles.get(r['ai_kp'], r['ai_kp'] or '—'), kind, r['note']))

    return {
        'n_rows': len(filled), 'n_judged': n_judged, 'n_match': n_match, 'rate': rate,
        'n_blank': n_blank, 'n_invalid': n_invalid,
        'by_year': by_year, 'by_type': by_type, 'shifts': shifts, 'warn_shift': warn_shift,
        'mod_dist': mod_dist, 'diffs': diffs, 'invalid': invalid, 'blank': blank,
        'recs': recs,
    }


# ---------------------------------------------------------------- 写报告
def unique_path(dirpath: pathlib.Path, stem: str, ext: str) -> pathlib.Path:
    p = dirpath / f'{stem}{ext}'
    k = 2
    while p.exists():
        p = dirpath / f'{stem}-{k}{ext}'
        k += 1
    return p


def build_md(st, meta):
    label = meta['label']
    self_test = '自测' in label or 'selftest' in meta['xlsx'].name.lower()
    L = ['---', 'type: data', f"title: 第四轮抽检回收 {meta['stamp']}", f"updated: {meta['date']}", '---', '',
         f"# 第四轮抽检（模块层）· 回收报告", '',
         f"> 来源：`{meta['xlsx'].name}`（工作表「{meta['sheet']}」）  ",
         f"> 生成：{meta['stamp']}　｜　标注源：`02_Processed/Annotations`　｜　标签：**{label}**  ",
         f"> 口径：只比模块层（17 模块），不比考点；一致率 = 模块相同 / 有效判定。", '']
    if self_test:
        L += ['> [!warning] 自测数据，不是真人填写', '> 本报告由合成填写件跑通流程得到，**不得**用作验收结论；'
              '真实结论须等教师填写件回收后重跑。', '']
    L += ['## 0. 填写有效性', '', '| 指标 | 数量 |', '| --- | --- |',
          f"| 题目总数 | {st['n_rows']} |",
          f"| 有效判定（模块 / 无法归类） | {st['n_judged']} |",
          f"| 空白未填 | {st['n_blank']} |",
          f"| 无效值（不在 17 模块内） | {st['n_invalid']} |",
          f"| 完成率 | {st['n_judged'] / st['n_rows'] * 100:.1f}% |", '']

    L += ['## 1. 总体模块一致率', '', '| 指标 | 结果 | 目标 |', '| --- | --- | --- |',
          f"| **模块一致率** | **{st['rate']:.1f}%**（{st['n_match']}/{st['n_judged']}） | ≥90% |",
          '| 有效判定 | %d/%d | %d |' % (st['n_judged'], st['n_rows'], st['n_rows']), '']
    if st['n_invalid']:
        L += ['无效值（请核对后重填，不计入一致率）：', '']
        for r in st['invalid']:
            L.append(f"- 第 {r['seq']} 题 `{r['qid']}`：`{r['module_raw']}`")
        L.append('')

    L += ['## 2. 按年份', '', '| 年份 | 有效 | 一致 | 一致率 |', '| --- | --- | --- | --- |']
    for y, n, ok, pct in st['by_year']:
        L.append(f'| {y} | {n} | {ok} | {pct:.1f}% |')
    L += ['', '## 3. 按题型', '', '| 题型 | 有效 | 一致 | 一致率 |', '| --- | --- | --- | --- |']
    for t, n, ok, pct in st['by_type']:
        L.append(f'| {t} | {n} | {ok} | {pct:.1f}% |')

    L += ['', '## 4. 错位诊断（±1 / ±2）', '',
          '若某偏移的一致率反而明显高于 0 偏移，说明填答可能整体错位一行，需重填。', '',
          '| 偏移 | 一致 | 有效 | 一致率 |', '| --- | --- | --- | --- |']
    for s in sorted(st['shifts']):
        ok, tot, pct = st['shifts'][s]
        mark = ' ← 基准' if s == 0 else ''
        L.append(f'| {s:+d}{mark} | {ok} | {tot} | {pct:.1f}% |')
    if st['warn_shift'] is not None:
        s = st['warn_shift']
        ok, tot, pct = st['shifts'][s]
        L += ['', f"> [!danger] 疑似整列粘贴错位（偏移 {s:+d} 时一致率 {pct:.1f}%）",
              '> 请核对前 3 行与末尾 1 行的 qid/题干对应关系，确认是逐行填写还是整列粘贴。']
    else:
        L += ['', '偏移 ±1/±2 未出现异常升高，未见整体错位迹象。']

    L += ['', '## 5. 模块分布对照', '',
          '| 模块 | 名称 | AI 标注题数 | 教师判定题数 | 双方一致 |', '| --- | --- | --- | --- | --- |']
    for mid, name, ai_n, t_n, both in st['mod_dist']:
        L.append(f'| `{mid}` | {name} | {ai_n} | {t_n} | {both} |')

    L += ['', '## 6. 分歧清单', '']
    if st['diffs']:
        L += [f'共 {len(st["diffs"])} 条。', '',
              '| 序号 | qid | 年份 | 题型 | 教师模块 | AI 模块 | AI 考点（参考） | 类型 | 备注 |',
              '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
        for seq, qid, year, typ, tm, am, kp, kind, note in st['diffs']:
            L.append(f'| {seq} | `{qid}` | {year} | {typ} | {tm} | {am} | {kp} | {kind} | {note} |')
    else:
        L += ['无分歧：全部有效判定与 AI 模块层标注一致。']

    if st['blank']:
        L += ['', '## 7. 未填清单', '', '| 序号 | qid | 年份 | 题型 |', '| --- | --- | --- | --- |']
        for r in st['blank']:
            L.append(f"| {r['seq']} | `{r['qid']}` | {r['year']} | {r['type']} |")

    L += ['', '---', '', '## 口径与使用说明', '',
          '- 一致率只算模块层；「教师判无法归类」与「AI 标注无归属」都算有效判定，但不等于一致。',
          '- 本报告是数据报告，不是人工结论；人工结论请另写（脚本不会覆盖任何非「回收_」前缀文件）。',
          '- 交叉核对：可将本报告与第三轮 AI 模拟复核结果对比，但第三轮「教师已填」是 AI 角色扮演，不作真人依据。', '']
    return '\n'.join(L) + '\n'


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description='第四轮抽检（模块层）回收与一致率报告')
    ap.add_argument('xlsx', nargs='?', default=str(DEFAULT_XLSX), help='回填后的 xlsx 绝对路径')
    ap.add_argument('--out', default=str(DEFAULT_OUT), help='报告输出目录（默认 11_Spotcheck\\第四轮_真人）')
    ap.add_argument('--label', default=None, help='数据来源标签，如「真人填写」「自测（合成数据，非真人）」')
    ap.add_argument('--check', action='store_true', help='只检查是否已填，不写报告；已填退出 0，未填退出 2')
    ap.add_argument('--dry-run', action='store_true', help='只打印摘要与将写路径，不落盘')
    args = ap.parse_args(argv)

    xlsx = pathlib.Path(args.xlsx)
    if not xlsx.exists():
        print(f'[错误] 找不到填写件：{xlsx}')
        print('空白件路径：', DEFAULT_XLSX)
        return 3

    label = args.label
    if not label:
        low = str(xlsx).lower()
        label = '自测（合成数据，非真人）' if ('selftest' in low or '自测' in low) else '真人填写'

    modules, titles, mod_num, name2id = load_vocab()
    if len(modules) != 17:
        print(f'[警告] 词表解析出 {len(modules)} 个模块（应为 17），请检查 10_Indexes\\知识点词表.md')
    ann = load_annotations()
    filled, sheet = read_filled(xlsx)

    # 与样本序列交叉检查（有就提示，不阻断）
    if SAMPLE.exists():
        try:
            qids = json.loads(SAMPLE.read_text(encoding='utf-8')).get('qids', [])
            got = {r['qid'] for r in filled}
            missing = [q for q in qids if q not in got]
            extra = [q for q in got if q not in qids]
            if missing:
                print(f'[提示] 样本 100 题中有 {len(missing)} 题不在填写件里：{missing[:3]} …')
            if extra:
                print(f'[提示] 填写件里有 {len(extra)} 个 qid 不在第三轮样本中：{extra[:3]} …')
        except Exception:
            pass

    st = analyse(filled, ann, modules, titles, mod_num, name2id)
    if st['n_judged'] == 0:
        print(f'尚无有效填写（0/{st["n_rows"]}；空白 {st["n_blank"]}，无效 {st["n_invalid"]}）。')
        print('→ 等待真实教师填写；脚本未写任何报告。')
        return 2

    stamp = _dt.datetime.now().strftime('%Y-%m-%d %H:%M')
    tag = '自测' if '自测' in label or 'selftest' in str(xlsx).lower() else ('真人' if '真人' in label else '未标注')
    stem = f'回收_第四轮_模块层_{_dt.datetime.now():%Y%m%d-%H%M%S}_{tag}'
    outdir = pathlib.Path(args.out)
    md_path = outdir / f'{stem}.md'
    json_path = outdir / f'{stem}.json'

    print(f'数据源：{xlsx}')
    print(f'标签：{label}　工作表：{sheet}　题目：{st["n_rows"]}')
    print(f'有效判定 {st["n_judged"]}｜空白 {st["n_blank"]}｜无效 {st["n_invalid"]}')
    print(f'模块一致率：{st["rate"]:.1f}% ({st["n_match"]}/{st["n_judged"]})｜分歧 {len(st["diffs"])}')
    print('错位诊断：' + '｜'.join(
        f'{s:+d}={st["shifts"][s][2]:.1f}%' for s in sorted(st['shifts'])))
    if st['warn_shift'] is not None:
        print(f'[警告] 疑似整列错位：偏移 {st["warn_shift"]:+d} 一致率异常升高，请核对填写方式。')
    if args.check:
        print('已填写：%d/%d（--check 模式，未写报告）' % (st['n_judged'], st['n_rows']))
        return 0

    meta = {'xlsx': xlsx, 'sheet': sheet, 'label': label,
            'stamp': stamp, 'date': _dt.date.today().isoformat()}
    if args.dry_run:
        print(f'[dry-run] 将写：{md_path}')
        print(f'[dry-run] 将写：{json_path}')
        return 0

    outdir.mkdir(parents=True, exist_ok=True)
    md_path = unique_path(outdir, stem, '.md')
    json_path = unique_path(outdir, stem, '.json')
    md_path.write_text(build_md(st, meta), encoding='utf-8')

    data = {
        'meta': {**meta, 'xlsx': str(xlsx), 'md': str(md_path), 'sample': str(SAMPLE),
                 'seed': 20261108, 'scope': 'module-level only'},
        'stats': {k: st[k] for k in ('n_rows', 'n_judged', 'n_match', 'rate', 'n_blank', 'n_invalid')},
        'by_year': st['by_year'], 'by_type': st['by_type'],
        'shifts': {str(k): v for k, v in st['shifts'].items()},
        'warn_shift': st['warn_shift'],
        'module_dist': st['mod_dist'],
        'disagreements': st['diffs'],
        'invalid': [(r['seq'], r['qid'], str(r['module_raw'])) for r in st['invalid']],
        'blank': [(r['seq'], r['qid']) for r in st['blank']],
    }
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'已写报告：{md_path}')
    print(f'已写数据：{json_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
