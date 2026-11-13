"""Standalone HTML, with no remote assets and escaped untrusted text."""
import html
import json


CSS = """
:root{color-scheme:light;--ink:#172c38;--muted:#677983;--border:#dce5e8;--bg:#f4f7f8;--accent:#176b70}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
header{background:#142f3b;color:#fff;padding:35px max(24px,calc((100vw - 1160px)/2));border-bottom:5px solid #69d0bc}
.brand{font-size:13px;letter-spacing:3px;color:#96dfd1}h1{font-size:clamp(25px,4vw,38px);line-height:1.25;margin:14px 0}header p{color:#b6cbd3;margin:0}
main{max-width:1208px;margin:auto;padding:28px 24px 60px}.banner{border:1px solid #e5c4c0;background:#fff2ef;color:#8d3d31;padding:15px 20px;border-radius:10px;margin-bottom:22px}.banner.good{background:#ecf8f3;border-color:#bdded1;color:#225b47}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px}.metric{background:#fff;border:1px solid var(--border);border-radius:10px;padding:17px 20px}.metric strong{display:block;font-size:30px;line-height:1.5}.metric span,.meta{color:var(--muted);font-size:12px}.red{color:#a74335}.green{color:#217257}
.toolbar{display:flex;gap:12px;margin:24px 0 18px;flex-wrap:wrap}input,select{font:inherit;border:1px solid #bacdd2;border-radius:7px;padding:10px 12px;background:#fff;color:var(--ink)}input{flex:1;min-width:180px}select{min-width:170px}:focus-visible{outline:3px solid #64baa9;outline-offset:3px}
.case{background:#fff;border:1px solid var(--border);border-radius:12px;overflow:hidden;margin:15px 0}.case-heading{padding:18px 20px;display:flex;align-items:center;gap:12px;border-bottom:1px solid var(--border);flex-wrap:wrap}.case h2{font-size:17px;margin:0;overflow-wrap:anywhere}.badge{font-size:11px;border-radius:30px;padding:4px 10px;background:#edf1f3;color:#5c6d76}.badge.regression,.badge.fail{background:#ffe7e1;color:#983c2e}.badge.improvement,.badge.pass{background:#ddf3e8;color:#23694c}.badge.error{background:#fff0cb;color:#805b09}
.input{padding:14px 20px;background:#f8fafb;font-size:13px;border-bottom:1px solid var(--border)}.input b{display:block;font-size:10px;letter-spacing:1px;color:var(--muted);margin-bottom:4px}
.outputs{display:grid;grid-template-columns:1fr 1fr}.output{padding:18px 20px;min-width:0}.output+.output{border-left:1px solid var(--border)}.output-heading{display:flex;align-items:center;justify-content:space-between;gap:10px;font-size:12px;color:var(--muted)}pre{font:13px/1.75 ui-monospace,Consolas,"Microsoft YaHei",monospace;white-space:pre-wrap;overflow-wrap:anywhere;margin:14px 0 8px;max-height:310px;overflow:auto}details{font-size:12px;margin-top:12px}summary{cursor:pointer;color:var(--accent)}ul{padding-left:20px}li{padding:3px 0;overflow-wrap:anywhere}code{font:12px ui-monospace,Consolas,monospace}.empty{padding:30px;text-align:center;color:var(--muted)}footer{margin-top:30px;font-size:12px;color:var(--muted)}.legend{display:flex;flex-wrap:wrap;gap:10px 25px}.legend code{font-size:11px}noscript{display:block;padding:12px}.sr{position:absolute;clip:rect(0,0,0,0)}[hidden]{display:none!important}
@media(max-width:650px){header{padding:25px 18px}main{padding:20px 14px 40px}.metrics{grid-template-columns:repeat(2,1fr);gap:10px}.metric{padding:14px}.outputs{grid-template-columns:1fr}.output+.output{border-left:0;border-top:1px solid var(--border)}.case-heading{padding:14px}.output,.input{padding:14px}.toolbar{gap:8px}input,select{width:100%}header p{font-size:13px}}
"""

SCRIPT = """
'use strict';
const search = document.getElementById('search');
const filter = document.getElementById('filter');
function update() {
  let shown = 0;
  const query = search.value.toLocaleLowerCase();
  for (const card of document.querySelectorAll('.case')) {
    const visible = (filter.value === 'all' || card.dataset.change === filter.value) && card.textContent.toLocaleLowerCase().includes(query);
    card.hidden = !visible;
    if (visible) shown++;
  }
  document.getElementById('visible-count').textContent = String(shown);
  document.getElementById('empty').hidden = shown > 0;
}
search.addEventListener('input', update);
filter.addEventListener('change', update);
update();
"""


def escape(value):
    return html.escape(str(value), quote=True)


def render_output(case, label):
    status_labels = {"pass": "通过 PASS", "fail": "未通过 FAIL", "error": "执行错误 ERROR"}
    status = case["status"]
    checks = []
    for check in case["checks"]:
        rule = escape(json.dumps(check["rule"], ensure_ascii=False))
        marker = "✓" if check["passed"] else "✕"
        checks.append('<li><span>{}</span> <code>{}</code></li>'.format(marker, rule))
    body = '<pre>{}</pre>'.format(escape(case.get("error") or case["output"]))
    if checks:
        body += '<details><summary>查看断言 · {} / {} 通过</summary><ul>{}</ul></details>'.format(
            sum(c["passed"] for c in case["checks"]), len(checks), "".join(checks))
    return '<section class="output"><div class="output-heading"><span>{}</span><span class="badge {}">{}</span></div>{}</section>'.format(
        escape(label), status, status_labels[status], body)


def render_comparison(comparison):
    s = comparison["summary"]
    labels = {"regression": "退步 REGRESSION", "improvement": "改善 IMPROVEMENT", "unchanged": "不变 UNCHANGED", "error": "执行错误 ERROR"}
    cards = []
    for case in comparison["cases"]:
        kind = case["change"]
        cards.append('''<article class="case" data-change="{kind}">
<div class="case-heading"><span class="badge {kind}">{change}</span><h2>{id}</h2></div>
<div class="input"><b>测试输入 / INPUT</b>{input}</div><div class="outputs">{before}{after}</div></article>'''.format(
            kind=kind, change=labels[kind], id=escape(case["id"]), input=escape(case["before"]["input"]),
            before=render_output(case["before"], comparison["baseline_label"]), after=render_output(case["after"], comparison["candidate_label"])))
    failing = s["regression"] or s["error"]
    verdict = "需要检查：{} 条退步，{} 条执行错误。".format(s["regression"], s["error"]) if failing else "未检测到新增退步；请同时关注未通过的既有用例。"
    providers = [comparison["baseline_provider"], comparison["candidate_provider"]]
    replay = any(p.get("type") == "recorded" for p in providers)
    note = "离线回放 · 输出来自预录文件，不是模型实时生成，也不能据此证明提示词质量。" if replay else "真实 API 测试 · 断言用于检查已定义的规则，不代表完整语义质量。"
    metrics = [("基线通过 / BASELINE", s["baseline_pass"], ""), ("候选通过 / CANDIDATE", s["candidate_pass"], ""),
               ("新增退步 / REGRESSIONS", s["regression"], "red"), ("改善 / IMPROVEMENTS", s["improvement"], "green")]
    metric_html = "".join('<div class="metric"><span>{}</span><strong class="{}">{}<small style="font-size:14px;color:#677983"> / {}</small></strong></div>'.format(label, cls, value, s["total"]) for label, value, cls in metrics)
    return '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>PromptDelta · 提示词回归报告</title><style>{css}</style></head>
<body><header><div class="brand">PROMPTDELTA / REGRESSION REPORT</div><h1>提示词改了，回答退步了吗？</h1><p>{suite} · {baseline} → {candidate}</p></header>
<main><div class="banner {good}">{verdict}</div><section class="metrics" aria-label="测试汇总">{metrics}</section>
<p class="meta">{note}</p><div class="legend meta"><span>基线模型：{old_model}</span><span>候选模型：{new_model}</span><span>执行错误：{errors}</span></div>
<div class="toolbar"><label class="sr" for="search">搜索用例、输入或输出</label><input id="search" placeholder="搜索用例、输入或输出…" type="search">
<label class="sr" for="filter">筛选变化</label><select id="filter"><option value="all">全部变化</option><option value="regression">只看退步</option><option value="improvement">只看改善</option><option value="unchanged">只看不变</option><option value="error">只看执行错误</option></select></div>
<div class="meta" role="status">显示 <span id="visible-count">{total}</span> / {total} 条用例</div><noscript>JavaScript 已禁用，下面仍可查看全部结果。</noscript>
{cards}<p id="empty" class="empty" hidden>没有符合条件的用例。</p>
<footer>PromptDelta · 本报告在本地生成，无外部脚本、字体或统计请求。输入和输出可能包含业务信息，分享前请检查。</footer></main><script>{script}</script></body></html>'''.format(
        css=CSS, script=SCRIPT, suite=escape(comparison["suite_name"]), baseline=escape(comparison["baseline_label"]),
        candidate=escape(comparison["candidate_label"]), good="" if failing else "good", verdict=verdict,
        metrics=metric_html, note=note, old_model=escape(providers[0].get("model", "unknown")),
        new_model=escape(providers[1].get("model", "unknown")), errors=s["error"], total=s["total"], cards="".join(cards))
