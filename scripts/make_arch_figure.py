# ponytail: hand-rolled SVG, no diagram lib. Re-run when §2 changes.
"""Sinh hình kiến trúc tổng thể (§2) ra reports/architecture.svg + .png."""
import pathlib
import subprocess

OUT = pathlib.Path("reports")
OUT.mkdir(exist_ok=True)

A = ("#F3E8FD", "#5B2C87")
B = ("#E8F0FE", "#1A3D7C")
C = ("#EDEDED", "#333333")
INFRA = ("#FFF4E5", "#8A5A00")
FONT = "Segoe UI, DejaVu Sans, Arial, sans-serif"
W, H = 560, 340

p = [
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W * 2}" height="{H * 2}" font-family="{FONT}">',
    '<defs>'
    '<marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
    '<path d="M0,0 L10,5 L0,10 z" fill="#111"/></marker>'
    '<marker id="aro" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
    '<path d="M0,0 L10,5 L0,10 z" fill="#C2410C"/></marker>'
    '</defs>',
    f'<rect width="{W}" height="{H}" fill="#fff"/>',
]


def box(x, y, w, h, title, subs, color, dash=False):
    f, s = color
    d = ' stroke-dasharray="4 3"' if dash else ""
    p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{f}" '
             f'stroke="{s}" stroke-width="1.4"{d}/>')
    base = y + (h - (len(subs) + 1) * 12) / 2 + 9
    p.append(f'<text x="{x + w / 2}" y="{base}" text-anchor="middle" font-size="11.5" '
             f'font-weight="600" fill="#111">{title}</text>')
    for i, sub in enumerate(subs):
        p.append(f'<text x="{x + w / 2}" y="{base + 12 * (i + 1)}" text-anchor="middle" '
                 f'font-size="8.8" fill="#333">{sub}</text>')


def line(pts, dashed=False, color="#111", marker="ar"):
    d = " ".join(("M" if i == 0 else "L") + f"{px},{py}" for i, (px, py) in enumerate(pts))
    da = ' stroke-dasharray="5 3"' if dashed else ""
    m = f' marker-end="url(#{marker})"' if marker else ""
    p.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.3"{da}{m}/>')


def label(x, y, t, size=8.8, anchor="middle", color="#111", rot=False):
    r = f' transform="rotate(-90 {x} {y})"' if rot else ""
    p.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" '
             f'fill="{color}"{r}>{t}</text>')


# --- ranh giới tiến trình (vẽ trước để nằm dưới) ---
line([(15, 128), (545, 128)], dashed=True, color="#888", marker=None)

# --- hộp ---
box(40, 10, 150, 34, "CLI / eval (C)", ["câu hỏi người dùng"], C)
box(350, 10, 180, 34, "client2.py (C)", ["host MCP thứ hai"], C)
box(40, 62, 270, 42, "Agent loop — agent/loop.py", ["MAX_STEPS = 8 · native tool-calling"], B)
box(345, 62, 185, 42, "LLM — agent/llm.py", ["retry · timeout · 1 nơi gọi"], B)
box(65, 154, 375, 40, "MCP server — mcp_server/server.py",
    ["5 tool (3 đọc · 2 ghi: freeze_account, flag_suspicious_tx)"], B)
box(65, 214, 375, 34, "tools/impl.py (B)", ['trả dataclass hoặc "Error: ..."'], B)
box(65, 268, 175, 46, "rag/search.py (A)", ["dense + hybrid BM25", "data/docs/DOC0001–9"], A)
box(265, 268, 175, 46, "SQLite — tools/state.py", ["accounts · transactions · flags"], INFRA)

# --- mũi tên ---
line([(115, 44), (115, 62)])                      # câu hỏi → agent
line([(310, 83), (345, 83)])                      # agent → LLM
line([(130, 104), (130, 154)])                    # agent → MCP (JSON-RPC)
line([(530, 27), (545, 27), (545, 174), (440, 174)])  # client2 → MCP
line([(252, 194), (252, 214)])                    # MCP → impl
line([(152, 248), (152, 268)])                    # impl → rag
line([(352, 248), (352, 268)])                    # impl → state
line([(65, 174), (25, 174), (25, 83), (40, 83)],   # verify: ghi → đọc lại
     dashed=True, color="#C2410C", marker="aro")

# --- nhãn ---
p.append('<rect x="150" y="120" width="380" height="16" fill="#fff"/>')
label(340, 132, "ranh giới tiến trình · MCP stdio: stdout = JSON-RPC, stderr = log")
label(136, 149, "list_tools() → call_tool() · JSON-RPC", anchor="start")
label(19, 150, "ghi → đọc lại (verify)", color="#C2410C", rot=True)

p.append("</svg>")
svg = OUT / "architecture.svg"
svg.write_text("\n".join(p), encoding="utf-8")

subprocess.run(["rsvg-convert", "-w", "1680", "-o", str(OUT / "architecture.png"), str(svg)],
               check=True)
print("wrote", svg, "and", OUT / "architecture.png")
