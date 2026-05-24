from __future__ import annotations

import base64
from pathlib import Path
from textwrap import dedent

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"
FIGURE_DIR = REPORT_DIR / "figures"
OUTPUT_DIR = ROOT / "output" / "pdf"

SOURCE_MD = REPORT_DIR / "leader_brief_mvp.md"
EMBEDDED_MD = REPORT_DIR / "leader_brief_mvp_embedded.md"
OUTPUT_PDF = OUTPUT_DIR / "bioenzyme_immobilization_mvp_brief.pdf"

FONT_PATH = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")

GREEN = colors.HexColor("#20785E")
GREEN_DARK = colors.HexColor("#0E4C3B")
GREEN_MID = colors.HexColor("#2F9B78")
GREEN_LIGHT = colors.HexColor("#EAF5EF")
BLUE_DARK = colors.HexColor("#102A43")
GRAY = colors.HexColor("#5C6670")
LINE = colors.HexColor("#D8E7DF")


def embed_images_in_markdown() -> None:
    md = SOURCE_MD.read_text(encoding="utf-8")
    for image_name in (
        "gpt_image2_system_architecture.png",
        "gpt_image2_student_workflow.png",
    ):
        image_path = FIGURE_DIR / image_name
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        md = md.replace(f"figures/{image_name}", f"data:image/png;base64,{encoded}")
    EMBEDDED_MD.write_text(md, encoding="utf-8")


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("ArialUnicode", str(FONT_PATH)))


def text_width(text: str, font_size: float, font: str = "ArialUnicode") -> float:
    return pdfmetrics.stringWidth(text, font, font_size)


def wrap_text(text: str, max_width: float, font_size: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for part in text.split("\n"):
        for char in part:
            candidate = current + char
            if text_width(candidate, font_size) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = char
        if current:
            lines.append(current)
            current = ""
    return lines


def draw_wrapped(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    max_width: float,
    font_size: float,
    leading: float | None = None,
    color=BLUE_DARK,
) -> float:
    c.setFont("ArialUnicode", font_size)
    c.setFillColor(color)
    lead = leading or font_size * 1.45
    for line in wrap_text(text, max_width, font_size):
        c.drawString(x, y, line)
        y -= lead
    return y


def draw_title(c: canvas.Canvas, title: str, subtitle: str, page_no: int) -> None:
    width, height = landscape(A4)
    c.setFillColor(GREEN_DARK)
    c.rect(0, height - 58, width, 58, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("ArialUnicode", 22)
    c.drawString(36, height - 37, title)
    c.setFont("ArialUnicode", 9.5)
    c.drawRightString(width - 36, height - 21, "生物酶固定化智能推荐系统")
    c.drawRightString(width - 36, height - 39, "MVP 阶段汇报")
    c.setFillColor(GREEN)
    c.rect(36, height - 80, width - 72, 3, stroke=0, fill=1)
    c.setFont("ArialUnicode", 10.5)
    c.setFillColor(GRAY)
    c.drawString(36, height - 99, subtitle)
    c.setFont("ArialUnicode", 8.5)
    c.drawRightString(width - 36, 22, f"{page_no} / 2")


def section_heading(c: canvas.Canvas, text: str, x: float, y: float) -> None:
    c.setFillColor(GREEN)
    c.roundRect(x, y - 18, 118, 24, 4, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("ArialUnicode", 11.5)
    c.drawCentredString(x + 59, y - 11, text)


def draw_card(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    c.setFillColor(colors.white)
    c.setStrokeColor(LINE)
    c.roundRect(x, y, w, h, 8, stroke=1, fill=1)


def bullet_list(
    c: canvas.Canvas,
    items: list[str],
    x: float,
    y: float,
    max_width: float,
    font_size: float = 9.5,
    color=BLUE_DARK,
) -> float:
    for item in items:
        c.setFillColor(GREEN_MID)
        c.circle(x + 3, y + 3, 2.2, stroke=0, fill=1)
        y = draw_wrapped(c, item, x + 12, y, max_width - 12, font_size, color=color)
        y -= 4
    return y


def draw_metric_grid(c: canvas.Canvas, x: float, y: float) -> None:
    metrics = [
        ("PDF", "14 页"),
        ("content blocks", "131 个"),
        ("RAG chunks", "36 个"),
        ("tables", "2 张"),
        ("evidence", "81 条"),
        ("review queue", "24 条"),
    ]
    cell_w = 76
    cell_h = 42
    for i, (label, value) in enumerate(metrics):
        row = i // 3
        col = i % 3
        cx = x + col * (cell_w + 8)
        cy = y - row * (cell_h + 8)
        c.setFillColor(GREEN_LIGHT)
        c.setStrokeColor(LINE)
        c.roundRect(cx, cy - cell_h, cell_w, cell_h, 6, stroke=1, fill=1)
        c.setFillColor(GREEN_DARK)
        c.setFont("ArialUnicode", 13)
        c.drawCentredString(cx + cell_w / 2, cy - 17, value)
        c.setFillColor(GRAY)
        c.setFont("ArialUnicode", 7.5)
        c.drawCentredString(cx + cell_w / 2, cy - 32, label)


def draw_pipeline(c: canvas.Canvas, x: float, y: float) -> None:
    steps = [
        ("PDF", "MinerU 解析"),
        ("Artifact", "md/json/table/image"),
        ("RAG", "chunk/table/candidate"),
        ("Evidence", "结构化事实"),
        ("Review", "学生复核"),
    ]
    box_w = 88
    box_h = 42
    for i, (top, bottom) in enumerate(steps):
        bx = x + i * (box_w + 17)
        c.setFillColor(GREEN if i % 2 == 0 else GREEN_MID)
        c.roundRect(bx, y - box_h, box_w, box_h, 8, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("ArialUnicode", 11)
        c.drawCentredString(bx + box_w / 2, y - 17, top)
        c.setFont("ArialUnicode", 7.2)
        c.drawCentredString(bx + box_w / 2, y - 31, bottom)
        if i < len(steps) - 1:
            c.setStrokeColor(GREEN_DARK)
            c.setLineWidth(1)
            ax = bx + box_w + 3
            ay = y - box_h / 2
            c.line(ax, ay, ax + 10, ay)
            c.line(ax + 10, ay, ax + 5, ay + 4)
            c.line(ax + 10, ay, ax + 5, ay - 4)


def draw_image(c: canvas.Canvas, image_path: Path, x: float, y: float, max_w: float, max_h: float) -> None:
    with Image.open(image_path) as image:
        img_w, img_h = image.size
    scale = min(max_w / img_w, max_h / img_h)
    draw_w = img_w * scale
    draw_h = img_h * scale
    c.drawImage(ImageReader(str(image_path)), x + (max_w - draw_w) / 2, y + (max_h - draw_h) / 2, draw_w, draw_h)


def render_pdf() -> None:
    register_fonts()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(OUTPUT_PDF), pagesize=landscape(A4))
    width, height = landscape(A4)

    # Page 1
    draw_title(c, "生物酶固定化智能推荐系统 MVP", "已经打通：PDF 切片 - RAG 原料 - Evidence extraction - Review queue - 对话 demo", 1)
    section_heading(c, "项目目标", 36, height - 128)
    y = draw_wrapped(
        c,
        "建设面向脂肪酶固定化的专业推荐系统。用户输入酶名称和配方条件后，系统给出候选固定化剂、参数优化建议和可追溯论文证据。",
        36,
        height - 158,
        318,
        10.3,
    )
    section_heading(c, "已完成闭环", 36, y - 10)
    draw_pipeline(c, 36, y - 48)
    section_heading(c, "B10 单篇验证", 36, y - 118)
    draw_metric_grid(c, 36, y - 150)
    y2 = y - 270
    draw_wrapped(
        c,
        "关键事实：Burkholderia cepacia lipase，hierarchical mesoporous ZIF-8，adsorption，pH 7.5，25 degC，700 mg loading，biodiesel yield 93.4%，8 cycles。",
        36,
        y2,
        318,
        9.2,
        color=GRAY,
    )

    draw_card(c, 388, 74, 410, 390)
    c.setFillColor(GREEN_DARK)
    c.setFont("ArialUnicode", 12)
    c.drawString(408, 438, "系统能力架构图")
    c.setFillColor(GRAY)
    c.setFont("ArialUnicode", 8.5)
    c.drawString(408, 421, "图片本体已内嵌到 Markdown，PDF 中为同源图像渲染。")
    draw_image(c, FIGURE_DIR / "gpt_image2_system_architecture.png", 408, 96, 370, 310)
    c.showPage()

    # Page 2
    draw_title(c, "预期效果与学生协作", "把学生论文整理工作升级为 curated knowledge base 生产流程", 2)
    section_heading(c, "最终效果", 36, height - 128)
    bullet_list(
        c,
        [
            "固定化剂推荐：按 enzyme、carrier、application、metric 返回候选方案。",
            "配方优化：围绕 pH、temperature、enzyme loading、adsorption time、additives 和 reaction system 给出调整方向。",
            "证据可追溯：建议关联论文、页码、表格或原文片段，避免黑箱推荐。",
            "风险可控制：OCR 异常、异常百分比、表格错位进入 review queue，不直接参与排序。",
        ],
        36,
        height - 158,
        326,
        9.8,
    )
    section_heading(c, "学生协作", 36, height - 312)
    bullet_list(
        c,
        [
            "论文收集：按脂肪酶、载体类型、应用场景整理 PDF 与基础 metadata。",
            "证据校验：核对 enzyme、carrier、method、reaction condition 和 performance metric。",
            "知识库扩容：确认后的证据进入 curated knowledge base，持续增强推荐质量。",
        ],
        36,
        height - 342,
        326,
        9.8,
    )
    draw_card(c, 36, 68, 326, 76)
    c.setFillColor(GREEN_DARK)
    c.setFont("ArialUnicode", 11)
    c.drawString(54, 120, "下一阶段")
    draw_wrapped(
        c,
        "扩展到 10-30 篇脂肪酶固定化论文，形成 review queue 标注规范；随后接入向量数据库和 LLM 对话接口，完成可演示推荐 MVP。",
        54,
        100,
        286,
        8.8,
        color=GRAY,
    )

    draw_card(c, 388, 74, 410, 390)
    c.setFillColor(GREEN_DARK)
    c.setFont("ArialUnicode", 12)
    c.drawString(408, 438, "学生协作与知识库生产闭环")
    c.setFillColor(GRAY)
    c.setFont("ArialUnicode", 8.5)
    c.drawString(408, 421, "从 PDF 收集进入 evidence review，再沉淀为可检索知识库。")
    draw_image(c, FIGURE_DIR / "gpt_image2_student_workflow.png", 408, 96, 370, 310)

    c.save()


def main() -> None:
    if not SOURCE_MD.exists():
        raise FileNotFoundError(f"missing source markdown: {SOURCE_MD}")
    for image_name in (
        "gpt_image2_system_architecture.png",
        "gpt_image2_student_workflow.png",
    ):
        if not (FIGURE_DIR / image_name).exists():
            raise FileNotFoundError(f"missing figure: {FIGURE_DIR / image_name}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    embed_images_in_markdown()
    render_pdf()

    print(
        dedent(
            f"""
            embedded_md={EMBEDDED_MD}
            pdf={OUTPUT_PDF}
            """
        ).strip()
    )


if __name__ == "__main__":
    main()
