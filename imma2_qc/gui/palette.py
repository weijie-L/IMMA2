"""界面配色与标记形状。

配色经 dataviz 校验器（light 模式、all-pairs）验证：
#2a78d6 / #d03b3b / #c98500 / #4a3aa7 全部通过；
#898781 为刻意弱化的“人工删除”灰色；#c98500 对比度 2.99:1，
以图例 + 三角形标记 + 底部记录表格作为补偿。
状态之间同时用标记形状区分，不单靠颜色。
"""

SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
COAST = "#c3c2b7"
TRACK_LINE = "#9ec5f4"
SELECT_EDGE = "#fab219"

# status -> (颜色, matplotlib marker, 点大小, zorder)
STATUS_STYLE = {
    "kept":        ("#2a78d6", "o", 14, 3),
    "review":      ("#c98500", "^", 30, 4),
    "auto_del":    ("#d03b3b", "x", 34, 5),
    "manual_del":  ("#898781", "x", 34, 5),
    "manual_keep": ("#4a3aa7", "o", 30, 5),
}
