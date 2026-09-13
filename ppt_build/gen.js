const pptxgen = require("pptxgenjs");
const path = require("path");

const ICON = (n) => path.join(__dirname, "icons", n + ".png");

// ---- palette ----
const BG = "0F2233", PANEL = "173449", PANEL2 = "1D3E58", INSET = "0B1B2A";
const TEAL = "2EC4B6", AMBER = "FFB454", CORAL = "FF6B81";
const TEXT = "F2F7FA", BODY = "C7D5E2", MUTED = "8AA0B4", FAINT = "5E7488";
const ARROW = "44607C", CORAL_DIM = "F0909F";
const CN = "Microsoft YaHei", MONO = "Consolas";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5
const W = 13.33;

// ---- helpers ----
function card(slide, x, y, w, h, fill = PANEL, radius = 0.09) {
  slide.addShape("roundRect", { x, y, w, h, fill: { color: fill }, rectRadius: radius, line: { type: "none" } });
}
function circleIcon(slide, cx, cy, d, fillColor, iconName, iconScale = 0.55) {
  slide.addShape("ellipse", { x: cx, y: cy, w: d, h: d, fill: { color: fillColor }, line: { type: "none" } });
  const s = d * iconScale, off = (d - s) / 2;
  slide.addImage({ path: ICON(iconName), x: cx + off, y: cy + off, w: s, h: s });
}
function arrow(slide, x1, y1, x2, y2, color = ARROW, width = 1.75) {
  const opts = { line: { color, width, endArrowType: "triangle" } };
  if (x2 < x1) opts.flipH = true;
  if (y2 < y1) opts.flipV = true;
  slide.addShape("line", { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1), ...opts });
}
function header(slide, kicker, title, pageNo) {
  slide.background = { color: BG };
  slide.addText(kicker, { x: 0.6, y: 0.38, w: 8, h: 0.3, fontFace: CN, fontSize: 11, bold: true, color: TEAL, charSpacing: 3, margin: 0 });
  slide.addText(title, { x: 0.6, y: 0.66, w: 12.1, h: 0.62, fontFace: CN, fontSize: 27, bold: true, color: TEXT, margin: 0 });
  slide.addText([
    { text: "xiaoyi 离线 RAG 知识库", options: { color: FAINT } },
  ], { x: 0.6, y: 7.13, w: 6, h: 0.26, fontFace: CN, fontSize: 8.5, margin: 0 });
  slide.addText(pageNo, { x: 11.6, y: 7.13, w: 1.13, h: 0.26, fontFace: MONO, fontSize: 9, bold: true, color: MUTED, align: "right", margin: 0 });
}

// ============================================================ SLIDE 1
{
  const s = pres.addSlide();
  header(s, "RAG 知识库 · 入库篇", "从 Markdown 到可检索的知识块", "01 / 03");

  // ---- Card A: RAG 是什么
  card(s, 0.6, 1.55, 3.7, 2.42);
  circleIcon(s, 0.82, 1.78, 0.44, TEAL, "book");
  s.addText("RAG 是什么", { x: 1.38, y: 1.8, w: 2.6, h: 0.4, fontFace: CN, fontSize: 13.5, bold: true, color: TEXT, margin: 0 });
  s.addText("检索增强生成：回答前先查本地知识库，把带出处的证据注入大模型上下文，而不是靠模型凭空编造。", {
    x: 0.85, y: 2.36, w: 3.25, h: 0.95, fontFace: CN, fontSize: 10, color: BODY, lineSpacingMultiple: 1.25, margin: 0,
  });
  s.addText("40 份 md → 397 块 · 索引 1.4 MB", { x: 0.85, y: 3.38, w: 3.25, h: 0.3, fontFace: CN, fontSize: 11, bold: true, color: TEAL, margin: 0 });
  s.addText("检索纯本地进程内 · 不联网", { x: 0.85, y: 3.66, w: 3.25, h: 0.24, fontFace: CN, fontSize: 8.5, color: MUTED, margin: 0 });

  // ---- Card B: 切块四步
  card(s, 4.5, 1.55, 8.23, 2.42);
  circleIcon(s, 4.72, 1.78, 0.44, TEAL, "layer");
  s.addText("Markdown 切块四步", { x: 5.28, y: 1.8, w: 4, h: 0.4, fontFace: CN, fontSize: 13.5, bold: true, color: TEXT, margin: 0 });

  const steps = [
    ["按标题分节", "h1–h4 逐级切分小节，标题全路径存入 section_path"],
    ["递归切分", "单块 ≤ 500 字：段落→换行→句号→逐字"],
    ["句级重叠", "overlap = 100：上一块结尾完整句接到下一块开头"],
    ["表格切分", "超过 10 行按行切，每块重贴表头"],
  ];
  steps.forEach((st, i) => {
    const x = 4.7 + i * 1.98;
    card(s, x, 2.32, 1.9, 1.48, PANEL2, 0.06);
    s.addShape("ellipse", { x: x + 0.13, y: 2.45, w: 0.26, h: 0.26, fill: { color: TEAL }, line: { type: "none" } });
    s.addText(String(i + 1), { x: x + 0.13, y: 2.45, w: 0.26, h: 0.26, fontFace: MONO, fontSize: 10, bold: true, color: "08251F", align: "center", valign: "middle", margin: 0 });
    s.addText(st[0], { x: x + 0.47, y: 2.44, w: 1.36, h: 0.3, fontFace: CN, fontSize: 10.5, bold: true, color: TEXT, margin: 0 });
    s.addText(st[1], { x: x + 0.13, y: 2.82, w: 1.64, h: 0.9, fontFace: CN, fontSize: 8, color: MUTED, lineSpacingMultiple: 1.2, margin: 0 });
  });

  // ---- Row 2 label
  s.addText("切块长什么样 —— 索引里的真实数据", { x: 0.6, y: 4.14, w: 8, h: 0.32, fontFace: CN, fontSize: 13, bold: true, color: TEXT, margin: 0 });

  // ---- chunk card 1
  const chunks = [
    {
      x: 0.6, cat: "小艺慧记：会议纪要与实时转写", q: "3. 会中摘要与总结",
      a: "发言内容达 200 字可按段落生成摘要（支持自动/手动刷新）；可生成关注发言人的发言总结；支持划重点、备注、截图。",
      p: "小艺慧记：会议纪要与实时转写 / 二、核心功能 / 3. 会中摘要与总结",
      f: "12-功能详解-小艺慧记会议纪要.md",
    },
    {
      x: 4.95, cat: "小艺慧记：会议纪要与实时转写", q: "会后处理",
      a: "一键导出 Word 文档；内容也可保存至备忘录的「小艺慧记」文件夹查看。",
      p: "小艺慧记：会议纪要与实时转写 / 三、使用方法 / 会后处理",
      f: "12-功能详解-小艺慧记会议纪要.md",
    },
  ];
  for (const c of chunks) {
    card(s, c.x, 4.52, 4.15, 2.42);
    s.addImage({ path: ICON("file"), x: c.x + 0.22, y: 4.72, w: 0.22, h: 0.22 });
    s.addText([
      { text: "category  ", options: { fontFace: MONO, fontSize: 8.5, bold: true, color: TEAL } },
      { text: c.cat, options: { fontFace: CN, fontSize: 9.5, bold: true, color: TEXT } },
    ], { x: c.x + 0.52, y: 4.66, w: 3.5, h: 0.34, valign: "middle", margin: 0 });
    s.addText([
      { text: "questions  ", options: { fontFace: MONO, fontSize: 8.5, bold: true, color: TEAL } },
      { text: c.q, options: { fontFace: CN, fontSize: 10.5, bold: true, color: TEXT } },
    ], { x: c.x + 0.52, y: 5.0, w: 3.5, h: 0.34, valign: "middle", margin: 0 });
    s.addText(c.a, { x: c.x + 0.25, y: 5.42, w: 3.68, h: 0.98, fontFace: CN, fontSize: 9, color: BODY, lineSpacingMultiple: 1.22, margin: 0 });
    s.addText([
      { text: c.p, options: { color: MUTED, breakLine: true } },
      { text: c.f, options: { color: MUTED } },
    ], { x: c.x + 0.25, y: 6.44, w: 3.68, h: 0.42, fontFace: CN, fontSize: 7.5, lineSpacingMultiple: 1.15, margin: 0 });
  }

  // ---- advantage card
  card(s, 9.3, 4.52, 3.43, 2.42, PANEL2);
  s.addImage({ path: ICON("check"), x: 9.55, y: 4.7, w: 0.26, h: 0.26 });
  s.addText("对比普通切块的优势", { x: 9.92, y: 4.66, w: 2.7, h: 0.34, fontFace: CN, fontSize: 12, bold: true, color: TEXT, valign: "middle", margin: 0 });
  s.addShape("roundRect", { x: 9.55, y: 5.1, w: 2.93, h: 0.66, fill: { color: INSET }, rectRadius: 0.05, line: { type: "none" } });
  s.addText([
    { text: "embed( category +", options: { breakLine: true } },
    { text: "       questions + answer )", options: {} },
  ], { x: 9.72, y: 5.14, w: 2.7, h: 0.58, fontFace: MONO, fontSize: 9.5, color: TEAL, valign: "middle", margin: 0 });
  s.addText([
    { text: "问句式标题贴近用户问法，召回更准", options: { bullet: true, breakLine: true } },
    { text: "category 支持筛选与目录路由", options: { bullet: true, breakLine: true } },
    { text: "section_path 让引用定位到小节", options: { bullet: true } },
  ], { x: 9.55, y: 5.92, w: 2.98, h: 0.95, fontFace: CN, fontSize: 9, color: BODY, paraSpaceAfter: 5, margin: 0 });
}

// ============================================================ SLIDE 2
{
  const s = pres.addSlide();
  header(s, "RAG 知识库 · 检索篇", "双路召回：bge 语义 + BM25 字面，RRF 一锤定音", "02 / 03");

  // query pill
  s.addShape("roundRect", { x: 4.32, y: 1.52, w: 4.7, h: 0.52, fill: { color: PANEL2 }, rectRadius: 0.26, line: { type: "none" } });
  circleIcon(s, 4.5, 1.64, 0.28, TEAL, "search", 0.6);
  s.addText("「小艺慧记的纪要怎么导出 Word？」", { x: 4.92, y: 1.52, w: 4.0, h: 0.52, fontFace: CN, fontSize: 11, bold: true, color: TEXT, valign: "middle", margin: 0 });

  // branch arrows
  arrow(s, 6.67, 2.04, 3.58, 2.62, TEAL);
  arrow(s, 6.67, 2.04, 9.76, 2.62, AMBER);

  // left: bge
  card(s, 0.6, 2.62, 5.95, 2.72);
  circleIcon(s, 0.82, 2.84, 0.42, TEAL, "brain");
  s.addText("bge-m3 向量检索", { x: 1.36, y: 2.86, w: 3.4, h: 0.38, fontFace: CN, fontSize: 14, bold: true, color: TEAL, valign: "middle", margin: 0 });
  s.addShape("roundRect", { x: 5.35, y: 2.9, w: 0.98, h: 0.32, fill: { color: "1B4A4F" }, rectRadius: 0.16, line: { type: "none" } });
  s.addText("语义相似", { x: 5.35, y: 2.9, w: 0.98, h: 0.32, fontFace: CN, fontSize: 8.5, bold: true, color: TEAL, align: "center", valign: "middle", margin: 0 });
  s.addText([
    { text: "模型：BAAI/bge-m3 · 1024 维 · OpenAI 兼容端点", options: { bullet: true, breakLine: true } },
    { text: "嵌入内容：category + questions + answer 整块编码", options: { bullet: true, breakLine: true } },
    { text: "强项：意思相近就能召回 ——「导出」≈「另存为」", options: { bullet: true, breakLine: true } },
    { text: "速度：397 块全库余弦 ≈ 15 ms（纯本地内存）", options: { bullet: true } },
  ], { x: 0.88, y: 3.44, w: 5.45, h: 1.75, fontFace: CN, fontSize: 10, color: BODY, paraSpaceAfter: 7, margin: 0 });

  // right: BM25
  card(s, 6.78, 2.62, 5.95, 2.72);
  circleIcon(s, 7.0, 2.84, 0.42, AMBER, "hash");
  s.addText("BM25 关键词检索", { x: 7.54, y: 2.86, w: 3.4, h: 0.38, fontFace: CN, fontSize: 14, bold: true, color: AMBER, valign: "middle", margin: 0 });
  s.addShape("roundRect", { x: 11.53, y: 2.9, w: 0.98, h: 0.32, fill: { color: "55431F" }, rectRadius: 0.16, line: { type: "none" } });
  s.addText("字面匹配", { x: 11.53, y: 2.9, w: 0.98, h: 0.32, fontFace: CN, fontSize: 8.5, bold: true, color: AMBER, align: "center", valign: "middle", margin: 0 });
  s.addText([
    { text: "分词：中文二元组「小艺/艺慧/慧记」+ 英文数字整词", options: { bullet: true, breakLine: true } },
    { text: "索引：倒排表 1.1 万词 · 参数 k1=1.5，b=0.75", options: { bullet: true, breakLine: true } },
    { text: "强项：型号、专有名词精确命中，稀有词 IDF 加权", options: { bullet: true, breakLine: true } },
    { text: "速度：只遍历含查询词的倒排链 ≈ 0.3 ms", options: { bullet: true } },
  ], { x: 7.06, y: 3.44, w: 5.45, h: 1.75, fontFace: CN, fontSize: 10, color: BODY, paraSpaceAfter: 7, margin: 0 });

  // converge arrows
  arrow(s, 3.58, 5.34, 6.2, 5.92, ARROW);
  arrow(s, 9.76, 5.34, 7.14, 5.92, ARROW);

  // RRF card
  card(s, 2.67, 5.92, 8.0, 1.08, PANEL2);
  circleIcon(s, 2.89, 6.14, 0.4, "2A4A63", "branch");
  s.addText("RRF 融合 · 只看排名，不比分数", { x: 3.41, y: 6.02, w: 4.2, h: 0.34, fontFace: CN, fontSize: 12.5, bold: true, color: TEXT, valign: "middle", margin: 0 });
  s.addText("两路都靠前的块排到最前 · k = 60", { x: 3.41, y: 6.4, w: 4.2, h: 0.26, fontFace: CN, fontSize: 9, color: MUTED, margin: 0 });
  s.addText("score(d) = Σ 1/(60 + rank)", { x: 7.75, y: 6.02, w: 2.65, h: 0.34, fontFace: MONO, fontSize: 11, bold: true, color: TEAL, align: "right", valign: "middle", margin: 0 });
  s.addText("k 越小头部权重越大", { x: 7.75, y: 6.4, w: 2.65, h: 0.26, fontFace: CN, fontSize: 8.5, color: FAINT, align: "right", margin: 0 });
}

// ============================================================ SLIDE 3
{
  const s = pres.addSlide();
  header(s, "RAG 知识库 · 精排篇", "从两路 TopN 到最终注入的 5 条证据", "03 / 03");

  // stage 1a / 1b stacked
  card(s, 0.6, 1.62, 2.7, 1.12);
  s.addText("向量召回", { x: 0.85, y: 1.76, w: 2.2, h: 0.28, fontFace: CN, fontSize: 10, color: MUTED, margin: 0 });
  s.addText("Top N = 10", { x: 0.85, y: 2.06, w: 2.2, h: 0.44, fontFace: MONO, fontSize: 17, bold: true, color: TEAL, margin: 0 });
  card(s, 0.6, 2.9, 2.7, 1.12);
  s.addText("BM25 召回", { x: 0.85, y: 3.04, w: 2.2, h: 0.28, fontFace: CN, fontSize: 10, color: MUTED, margin: 0 });
  s.addText("Top N = 10", { x: 0.85, y: 3.34, w: 2.2, h: 0.44, fontFace: MONO, fontSize: 17, bold: true, color: AMBER, margin: 0 });

  arrow(s, 3.3, 2.18, 3.78, 2.55);
  arrow(s, 3.3, 3.46, 3.78, 3.09);

  // RRF pool
  card(s, 3.82, 2.0, 2.85, 1.62, PANEL2);
  s.addText("RRF 融合候选池", { x: 4.07, y: 2.16, w: 2.4, h: 0.28, fontFace: CN, fontSize: 10, color: MUTED, margin: 0 });
  s.addText("Top M = 10", { x: 4.07, y: 2.46, w: 2.4, h: 0.44, fontFace: MONO, fontSize: 17, bold: true, color: TEXT, margin: 0 });
  s.addText("排名相加 · k = 60", { x: 4.07, y: 3.02, w: 2.4, h: 0.26, fontFace: CN, fontSize: 8.5, color: FAINT, margin: 0 });

  arrow(s, 6.67, 2.81, 7.05, 2.81);

  // rerank stage
  card(s, 7.1, 2.0, 2.85, 1.62);
  s.addShape("roundRect", { x: 7.1, y: 2.0, w: 2.85, h: 1.62, fill: { type: "none" }, rectRadius: 0.09, line: { color: CORAL, width: 1.5 } });
  s.addText("bge-reranker 精排", { x: 7.35, y: 2.16, w: 2.4, h: 0.28, fontFace: CN, fontSize: 10, bold: true, color: CORAL, margin: 0 });
  s.addText("Top 5", { x: 7.35, y: 2.46, w: 2.4, h: 0.44, fontFace: MONO, fontSize: 19, bold: true, color: TEXT, margin: 0 });
  s.addText("低于 0.3 → 证据不足", { x: 7.35, y: 3.02, w: 2.4, h: 0.26, fontFace: CN, fontSize: 8.5, color: CORAL_DIM, margin: 0 });

  arrow(s, 9.95, 2.81, 10.33, 2.81);

  // output
  card(s, 10.38, 2.0, 2.35, 1.62);
  s.addImage({ path: ICON("quote"), x: 10.62, y: 2.18, w: 0.26, h: 0.26 });
  s.addText("证据注入", { x: 10.98, y: 2.16, w: 1.6, h: 0.28, fontFace: CN, fontSize: 10, color: MUTED, margin: 0 });
  s.addText("≤ 5 条", { x: 10.62, y: 2.5, w: 1.9, h: 0.44, fontFace: MONO, fontSize: 17, bold: true, color: TEXT, margin: 0 });
  s.addText("小节路径 · 来源 · 相关度", { x: 10.62, y: 3.02, w: 2.0, h: 0.26, fontFace: CN, fontSize: 8.5, color: FAINT, margin: 0 });

  // deep dive card
  card(s, 0.6, 4.1, 12.13, 2.78);
  circleIcon(s, 0.85, 4.34, 0.46, CORAL, "filter");
  s.addText("为什么还需要 bge-reranker-v2-m3 精排？", { x: 1.44, y: 4.36, w: 8, h: 0.42, fontFace: CN, fontSize: 13.5, bold: true, color: TEXT, valign: "middle", margin: 0 });
  s.addText([
    { text: "联合编码打分：query 与候选块一起送入模型，比「各自编码再算距离」更懂是否对题", options: { bullet: true, breakLine: true } },
    { text: "独立 /rerank 端点：非 OpenAI 协议，429/5xx 自动指数退避重试", options: { bullet: true } },
  ], { x: 0.9, y: 5.02, w: 5.65, h: 1.7, fontFace: CN, fontSize: 10, color: BODY, paraSpaceAfter: 10, lineSpacingMultiple: 1.2, margin: 0 });
  s.addText([
    { text: "阈值 0.3 把关：最高分不过线 → 判「证据不足」，宁缺毋滥不硬答", options: { bullet: true, breakLine: true } },
    { text: "产出可溯源：每条证据带小节路径、来源文件与相关度，注入后综合作答", options: { bullet: true } },
  ], { x: 6.9, y: 5.02, w: 5.6, h: 1.7, fontFace: CN, fontSize: 10, color: BODY, paraSpaceAfter: 10, lineSpacingMultiple: 1.2, margin: 0 });
}

pres.writeFile({ fileName: path.join(__dirname, "rag_intro.pptx") }).then(() => console.log("written"));
