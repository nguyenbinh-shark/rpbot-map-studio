"""Offline report index and machine-readable result manifest."""

from pathlib import Path
import html
from analysis import atomic_json


def write_report(output, result):
    output = Path(output)
    atomic_json(output / "manifest.json", result)
    esc = html.escape
    notes = [
        "Tốc độ/gia tốc từ chênh lệch pose là ước lượng giữa các node đã giữ lại. Tần suất node hoặc Statistics không phải FPS camera.",
        "Các bộ đếm bằng 0 được xuất như đã lưu; không suy diễn là matching hoàn hảo hoặc sai số vật lý bằng 0.",
        "Covariance và residual nội bộ pose/link không thay thế đánh giá với ground truth.",
        "Point cloud dùng RGB-D, calibration và pose đã có. App không tự tìm khép vòng hay chạy lại SLAM.",
        "Hình và trục dùng tiếng Anh để thuận tiện đưa vào báo cáo; số liệu gốc ở thư mục CSV.",
    ] + result["warnings"]
    style = """body{margin:0;background:#f2f5fa;color:#203047;font:15px system-ui}main{max-width:1250px;margin:auto;padding:28px}h1{font-size:30px;margin:0 0 12px}header,.notes{background:white;padding:22px;border-radius:12px;margin:12px 0}a{color:#145da0}nav{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(410px,1fr));gap:18px}.card{background:white;padding:12px;border-radius:10px;border:1px solid #dce4ef}.card img{width:100%;height:auto;display:block}.card h3{font-size:16px}.card p{font-size:12px;color:#536175}.badge{display:inline-block;background:#e8eef7;padding:6px 10px;margin:3px;border-radius:6px;font-size:13px}summary{cursor:pointer;font-weight:600}li{margin:9px 0}input{width:min(95%,650px);padding:12px;border:1px solid #aac;border-radius:8px}.hide{display:none}.path{overflow-wrap:anywhere;color:#556375}@media(max-width:600px){main{padding:12px}.grid{grid-template-columns:1fr}}"""
    badges = [
        f"{result['nodes_valid']} pose hợp lệ",
        f"{result['statistics_records']} bản ghi Statistics",
        f"{result['metric_count']} chỉ số",
        f"{result['figure_count']} hình",
        f"{result['pointcloud_vertices']:,} điểm 3D",
        "SQLite: OK"
        if result.get("integrity") == "ok"
        else result.get("input_format", "Input") + ": parsed",
    ]
    parts = [
        '<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RPBot Map Studio · báo cáo</title><style>'
        + style
        + "</style><main>",
        '<header><h1>RPBot Map Studio</h1><p class="path">' + esc(result["database"]) + "</p>",
        "".join('<span class="badge">' + esc(s) + "</span>" for s in badges),
        '<nav><a href="SLAM_report.pdf">PDF toàn bộ</a><a href="csv/">Dữ liệu CSV</a><a href="manifest.json">Thông tin nguồn</a><a href="#figures">Hình tổng hợp</a><a href="#metrics">Các chỉ số</a>',
    ]
    if (output / "view_map_3d.html").is_file():
        parts.append('<a href="view_map_3d.html">Xoay/zoom map 3D</a>')
    if (output / "map_2d.png").is_file():
        parts.append('<a href="map_2d.png">Map 2D</a>')
    if result["settings"].get("zip"):
        parts.append('<a href="RPBotMapStudio_report.zip">Gói ZIP</a>')
    parts.append(
        '</nav></header><details class="notes"><summary>Nguồn dữ liệu và cách diễn giải</summary><p>Pose: '
        + esc(result["pose_source"])
        + ". Map 2D: "
        + esc(result.get("map_source") or "không có dữ liệu")
        + ".</p><ul>"
        + "".join("<li>" + esc(n) + "</li>" for n in notes)
        + '</ul></details><h2 id="figures">Hình tổng hợp</h2><div class="grid">'
    )

    def card(f):
        return (
            '<article class="card"><h3>'
            + esc(f["title"])
            + '</h3><a href="'
            + f["file"]
            + '"><img loading="lazy" src="'
            + f["file"]
            + '" alt="'
            + esc(f["title"])
            + '"></a><p>'
            + esc(f.get("note", ""))
            + '</p><a href="'
            + f["file"]
            + '">PNG</a>'
            + (' · <a href="' + f["svg"] + '">SVG</a>' if f.get("svg") else "")
            + "</article>"
        )

    parts.extend(card(f) for f in result["figures"])
    parts.append('</div><h2 id="metrics">Các chỉ số có trong database</h2>')
    if result["metrics"]:
        parts.append(
            '<input id="search" type="search" placeholder="Lọc tên chỉ số: Timing, Memory, Loop…"><div class="grid">'
        )
        for f in result["metrics"]:
            h = card(f).replace(
                'class="card"', 'class="card metric" data-name="' + esc(f["title"].lower()) + '"', 1
            )
            if f.get("constant"):
                h = h.replace(
                    "<p></p>", "<p>Hằng số như đã ghi; không phải bằng chứng về sai số thực.</p>"
                )
            parts.append(h)
        parts.append(
            '</div><script>document.getElementById("search").addEventListener("input",e=>{const q=e.target.value.toLowerCase();document.querySelectorAll(".metric").forEach(c=>c.classList.toggle("hide",!c.dataset.name.includes(q)))})</script>'
        )
    else:
        parts.append(
            "<p>Chế độ Nhanh chỉ xuất hình tổng hợp, hoặc database không lưu Statistics. Các giá trị có sẵn vẫn nằm trong CSV.</p>"
        )
    parts.append(
        "<p>File nguồn được giữ nguyên. Mỗi phiên dùng một bản sao độc lập; xem source_manifest.json để kiểm tra checksum.</p></main></html>"
    )
    (output / "index.html").write_text("".join(parts), encoding="utf-8")
    readme = (
        "RPBot Map Studio — báo cáo phân tích\n\nMở index.html để xem, SLAM_report.pdf để đọc/in. Thư mục figures/ và metrics/ chứa PNG/SVG; csv/ chứa số liệu. Map 3D tương tác ở view_map_3d.html nếu có.\n\nNguồn: "
        + result["database"]
        + "\nPose: "
        + result["pose_source"]
        + "\nMap 2D: "
        + str(result.get("map_source"))
        + "\n\n"
        + "\n".join("- " + n for n in notes)
        + "\n"
    )
    (output / "README.txt").write_text(readme, encoding="utf-8")
