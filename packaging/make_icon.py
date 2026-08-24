"""把源图片转换成程序图标。

用法：把图标图片保存为 packaging/icon_source.png（正方形，建议 ≥512px，
png/jpg 均可），然后运行：

    python packaging/make_icon.py

生成：
  packaging/icon.ico          exe 文件图标（16-256 多尺寸）
  imma2_qc/assets/icon.png    程序窗口/任务栏图标（256px）

之后重新执行 packaging/build_exe.bat 打包即可生效。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_CANDIDATES = [ROOT / "packaging" / "icon_source.png",
                     ROOT / "packaging" / "icon_source.jpg"]
ICO_PATH = ROOT / "packaging" / "icon.ico"
PNG_PATH = ROOT / "imma2_qc" / "assets" / "icon.png"
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
             (128, 128), (256, 256)]


def main(source: str | None = None) -> int:
    try:
        from PIL import Image
    except ImportError:
        print("需要 Pillow：python -m pip install pillow")
        return 1

    src = Path(source) if source else next(
        (p for p in SOURCE_CANDIDATES if p.exists()), None)
    if src is None or not src.exists():
        print("未找到源图片。请把图标保存为 packaging/icon_source.png 后重试，"
              "或指定路径：python packaging/make_icon.py <图片路径>")
        return 1

    img = Image.open(src).convert("RGBA")
    side = min(img.size)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side))

    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(ICO_PATH, format="ICO", sizes=ICO_SIZES)
    PNG_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.resize((256, 256), Image.LANCZOS).save(PNG_PATH, format="PNG")
    print(f"已生成 {ICO_PATH}")
    print(f"已生成 {PNG_PATH}")
    print("重新运行 packaging\\build_exe.bat 打包即可生效")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
