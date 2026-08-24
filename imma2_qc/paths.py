"""数据目录配置：各处理阶段的输入/输出目录，持久化到用户主目录。

exe 与源码运行共用 ~/.imma2_qc/settings.json，升级程序不丢配置。
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

SETTINGS_FILE = Path.home() / ".imma2_qc" / "settings.json"


@dataclass
class PathsConfig:
    raw_dir: str = ""        # 原始 IMMA1 报文目录（IMMA1_R*_YYYY-MM）
    extract_dir: str = ""    # 第1步 数据提取输出（IMMA1_YYYY-MM_VI1.csv）
    clean_dir: str = ""      # 第2步 规整清洗输出（也是航速填补与质控的输入）
    qc_output_dir: str = ""  # 第4步 质控导出目录
    gshhg_dir: str = ""      # 可选：GSHHG 海岸线目录

    FIELDS_CN: ClassVar[dict[str, str]] = {
        "raw_dir": "原始 IMMA1 数据",
        "extract_dir": "提取输出目录",
        "clean_dir": "规整清洗目录",
        "qc_output_dir": "质控导出目录",
        "gshhg_dir": "GSHHG 海岸线（可选）",
    }


def load_paths() -> PathsConfig:
    if not SETTINGS_FILE.exists():
        return PathsConfig()
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return PathsConfig()
    known = {f.name for f in dataclasses.fields(PathsConfig)}
    return PathsConfig(**{k: v for k, v in data.items() if k in known})


def save_paths(cfg: PathsConfig) -> Path:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(dataclasses.asdict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8")
    return SETTINGS_FILE
