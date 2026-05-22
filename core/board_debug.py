import cv2


def get_color_for_label(label):
    """
    根据识别结果返回颜色，OpenCV 使用 BGR。
    """
    if label == "empty":
        return (180, 180, 180)

    if label == "unknown":
        return (0, 0, 255)

    if label == "invalid_frame":
        return (0, 165, 255)

    return (0, 255, 0)


def _clip_text(text, max_len=22):
    text = str(text)
    if len(text) > max_len:
        return text[:max_len]
    return text


def _draw_text_line(vis, text, x, y, color, font_scale=0.30):
    cv2.putText(
        vis,
        _clip_text(text),
        (x, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale,
        color,
        1,
        cv2.LINE_AA,
    )


def draw_board_results(frame, cell_results, show_confidence=True):
    """
    调试显示格式：

    M = memory label，最终给策略使用的棋盘记忆
    L = live label，当前这一帧分类器识别结果
    R = raw label，KNN 原始最近类别
    E = empty_streak / required_frames
    V = empty visual check，当前格子是否像干净空地
    """
    vis = frame.copy()

    for cell in cell_results:
        x, y, w, h = cell["bbox"]

        memory_label = cell.get("memory_label", cell.get("label", "unknown"))
        live_label = cell.get("live_label", "unknown")
        live_raw_label = cell.get(
            "live_raw_label",
            cell.get("raw_label", live_label),
        )

        confidence = float(cell.get("confidence", 0.0))
        empty_streak = int(cell.get("empty_streak", 0))
        empty_required = int(cell.get("empty_required_frames", 0))
        empty_candidate = bool(cell.get("empty_candidate", False))

        frame_valid = bool(cell.get("frame_valid", True))
        frame_status = cell.get("frame_status", "ok")

        empty_visual_ok = cell.get("empty_visual_ok", None)
        empty_visual_reason = cell.get("empty_visual_reason", "")

        memory_color = get_color_for_label(memory_label)
        live_color = get_color_for_label(live_label)

        if empty_candidate:
            border_color = (0, 255, 255)
            thickness = 2
        else:
            border_color = memory_color
            thickness = 1

        cv2.rectangle(
            vis,
            (x, y),
            (x + w, y + h),
            border_color,
            thickness,
        )

        if not show_confidence:
            cv2.rectangle(
                vis,
                (x, y),
                (x + w, y + 18),
                (0, 0, 0),
                -1,
            )
            _draw_text_line(
                vis,
                f"{memory_label}",
                x + 3,
                y + 13,
                memory_color,
                font_scale=0.36,
            )
            continue

        if not frame_valid:
            lines = [
                f"M:{memory_label}",
                f"F:{frame_status}",
            ]
        else:
            if empty_required > 0:
                empty_text = f"E:{empty_streak}/{empty_required}"
            else:
                empty_text = f"E:{empty_streak}"

            if empty_visual_ok is None:
                visual_text = "V:na"
            else:
                visual_text = "V:ok" if empty_visual_ok else "V:no"

            if empty_visual_reason:
                visual_text += f" {empty_visual_reason}"

            lines = [
                f"M:{memory_label}",
                f"L:{live_label} {confidence:.2f}",
                f"R:{live_raw_label}",
                empty_text,
                visual_text,
            ]

        line_height = 12
        bg_height = min(h, 4 + line_height * len(lines))

        cv2.rectangle(
            vis,
            (x, y),
            (x + w, y + bg_height),
            (0, 0, 0),
            -1,
        )

        for i, line in enumerate(lines):
            line_y = y + 10 + i * line_height

            if line.startswith("M:"):
                color = memory_color
            elif line.startswith("L:"):
                color = live_color
            elif line.startswith("E:"):
                color = (0, 255, 255) if empty_candidate else (220, 220, 220)
            elif line.startswith("V:ok"):
                color = (0, 255, 0)
            elif line.startswith("V:no"):
                color = (0, 0, 255)
            else:
                color = (220, 220, 220)

            _draw_text_line(
                vis,
                line,
                x + 3,
                line_y,
                color,
                font_scale=0.28,
            )

    return vis
