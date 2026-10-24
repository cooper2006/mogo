#!/usr/bin/env python3
"""Second pass: fix remaining 3 complexity violations."""

PATH = "apps/user-web/src/components/PresentationEditor.vue"

with open(PATH, "r", encoding="utf-8") as f:
    src = f.read()

# ── Fix 1: onObjectMoving — extract spacing logic ──────────────────
# Replace the spacing section with a call to applySpacingSnaps
OLD_SPACING = r'''  let spacingSnappedX = false
  let spacingSnappedY = false
  if (toLeft.length > 0 && toRight.length > 0) {
    spacingSnappedX = tryApplySpacingXBetween(target, r.tw, r.th, toLeft[0], toRight[0], cur.left, cur.right, cur.top)
  }
  if (!spacingSnappedX && toLeft.length >= 2) {
    spacingSnappedX = tryApplySpacingXEndLeft(target, r.tw, r.th, toLeft[1], toLeft[0], cur.left, cur.top)
  }
  if (!spacingSnappedX && toRight.length >= 2) {
    spacingSnappedX = tryApplySpacingXStartRight(target, r.tw, r.th, toRight[0], toRight[1], cur.right, cur.top)
  }
  if (above.length > 0 && below.length > 0) {
    spacingSnappedY = tryApplySpacingYBetween(target, r.tw, r.th, above[0], below[0], cur.top, cur.bottom, cur.left)
  }
  if (!spacingSnappedY && above.length >= 2) {
    spacingSnappedY = tryApplySpacingYEndAbove(target, r.tw, r.th, above[1], above[0], cur.top, cur.left)
  }
  if (!spacingSnappedY && below.length >= 2) {
    spacingSnappedY = tryApplySpacingYStartBelow(target, r.tw, r.th, below[0], below[1], cur.bottom, cur.left)
  }'''

NEW_SPACING = r'''  applySpacingSnaps(target, r, cur, toLeft, toRight, above, below)'''

src = src.replace(OLD_SPACING, NEW_SPACING)

# Add applySpacingSnaps helper before </script>
APPLY_SPACING_SNAPS = r'''
// 应用间距吸附逻辑
function applySpacingSnaps(
  target: fabric.FabricObject, r: any, cur: any,
  toLeft: any[], toRight: any[], above: any[], below: any[],
) {
  let spacingSnappedX = false
  let spacingSnappedY = false
  if (toLeft.length > 0 && toRight.length > 0) {
    spacingSnappedX = tryApplySpacingXBetween(target, r.tw, r.th, toLeft[0], toRight[0], cur.left, cur.right, cur.top)
  }
  if (!spacingSnappedX && toLeft.length >= 2) {
    spacingSnappedX = tryApplySpacingXEndLeft(target, r.tw, r.th, toLeft[1], toLeft[0], cur.left, cur.top)
  }
  if (!spacingSnappedX && toRight.length >= 2) {
    spacingSnappedX = tryApplySpacingXStartRight(target, r.tw, r.th, toRight[0], toRight[1], cur.right, cur.top)
  }
  if (above.length > 0 && below.length > 0) {
    spacingSnappedY = tryApplySpacingYBetween(target, r.tw, r.th, above[0], below[0], cur.top, cur.bottom, cur.left)
  }
  if (!spacingSnappedY && above.length >= 2) {
    spacingSnappedY = tryApplySpacingYEndAbove(target, r.tw, r.th, above[1], above[0], cur.top, cur.left)
  }
  if (!spacingSnappedY && below.length >= 2) {
    spacingSnappedY = tryApplySpacingYStartBelow(target, r.tw, r.th, below[0], below[1], cur.bottom, cur.left)
  }
}
'''

src = src.replace("</script>", APPLY_SPACING_SNAPS + "</script>")

# ── Fix 2: writeTextBoxGeometry — split into layout + height ──────
OLD_WRITE_TB = r'''function writeTextBoxGeometry(block: any, entry: any | undefined, obj: fabric.Textbox) {
  const layoutBox = (obj as any)._layoutBox
  const scaleX = obj.scaleX || 1
  const boxLeft = layoutBox
    ? layoutBox.left + (Number(obj.left || 0) - layoutBox.textLeft)
    : Number(obj.left || 0)
  const boxTop = layoutBox
    ? layoutBox.top + (Number(obj.top || 0) - layoutBox.textTop)
    : Number(obj.top || 0)
  const boxWidth = layoutBox
    ? Math.max(1, layoutBox.width + ((Number(obj.width || 0) * scaleX) - layoutBox.textWidth))
    : Number(obj.width || 0) * scaleX
  if (entry) {
    writeBlockXY(block, entry, boxLeft, boxTop)
    writeBlockSize(block, entry, boxWidth, layoutBox?.height || Number(obj.height || 0))
  } else {
    block.x = boxLeft / CANVAS_W
    block.y = boxTop / CANVAS_H
    block.w = boxWidth / CANVAS_W
  }
  const sy = obj.scaleY || 1
  if (Math.abs(sy - 1) > 0.001) {
    const absH = (obj as any).height * sy
    if (entry) {
      block.h = entry.parentRect.h > 0 ? (absH / CANVAS_H) / entry.parentRect.h : absH / CANVAS_H
    } else {
      block.h = absH / CANVAS_H
    }
  }
}'''

NEW_WRITE_TB = r'''function writeTextBoxGeometry(block: any, entry: any | undefined, obj: fabric.Textbox) {
  const layoutBox = (obj as any)._layoutBox
  const scaleX = obj.scaleX || 1
  const { boxLeft, boxTop, boxWidth } = computeTextBoxLayout(layoutBox, obj, scaleX)
  if (entry) {
    writeBlockXY(block, entry, boxLeft, boxTop)
    writeBlockSize(block, entry, boxWidth, layoutBox?.height || Number(obj.height || 0))
  } else {
    block.x = boxLeft / CANVAS_W
    block.y = boxTop / CANVAS_H
    block.w = boxWidth / CANVAS_W
  }
  saveTextBoxHeight(block, entry, obj)
}

// 计算 text_box 的布局坐标
function computeTextBoxLayout(layoutBox: any, obj: fabric.Textbox, scaleX: number) {
  const boxLeft = layoutBox
    ? layoutBox.left + (Number(obj.left || 0) - layoutBox.textLeft)
    : Number(obj.left || 0)
  const boxTop = layoutBox
    ? layoutBox.top + (Number(obj.top || 0) - layoutBox.textTop)
    : Number(obj.top || 0)
  const boxWidth = layoutBox
    ? Math.max(1, layoutBox.width + ((Number(obj.width || 0) * scaleX) - layoutBox.textWidth))
    : Number(obj.width || 0) * scaleX
  return { boxLeft, boxTop, boxWidth }
}

// 保存 text_box 高度（仅在用户缩放时写入）
function saveTextBoxHeight(block: any, entry: any | undefined, obj: fabric.Textbox) {
  const sy = obj.scaleY || 1
  if (Math.abs(sy - 1) > 0.001) {
    const absH = (obj as any).height * sy
    if (entry) {
      block.h = entry.parentRect.h > 0 ? (absH / CANVAS_H) / entry.parentRect.h : absH / CANVAS_H
    } else {
      block.h = absH / CANVAS_H
    }
  }
}'''

src = src.replace(OLD_WRITE_TB, NEW_WRITE_TB)

# ── Fix 3: syncToolbarShape — split into gradient/solid/stroke ────
OLD_SYNC_SHAPE = r'''function syncToolbarShape(obj: any) {
  const fill = (obj as any).fill
  if (fill && typeof fill === 'object' && fill.type === 'linear') {
    toolFillMode.value = 'gradient'
    const stops = fill.colorStops || []
    toolGradientFrom.value = stops[0]?.color || '#3b82f6'
    toolGradientTo.value = stops[stops.length - 1]?.color || '#8b5cf6'
    const coords = fill.coords || {}
    const dx = (coords.x2 ?? 1) - (coords.x1 ?? 0)
    const dy = (coords.y2 ?? 0) - (coords.y1 ?? 0)
    toolGradientAngle.value = Math.round((Math.atan2(dy, dx) * 180 / Math.PI + 90 + 360) % 360)
  } else {
    toolFillMode.value = 'solid'
    toolFillColor.value = (typeof fill === 'string' && fill !== 'transparent') ? fill : '#ffffff'
  }
  const stroke = (obj as any).stroke
  toolStrokeColor.value = (typeof stroke === 'string' && stroke !== 'transparent') ? stroke : '#000000'
  toolOpacity.value = Math.round((obj.opacity ?? 1) * 100)
  toolCornerRadius.value = (obj as any).rx || 0
}'''

NEW_SYNC_SHAPE = r'''function syncToolbarShape(obj: any) {
  const fill = (obj as any).fill
  if (isLinearGradient(fill)) {
    syncToolbarGradientFill(fill)
  } else {
    syncToolbarSolidFill(fill)
  }
  syncToolbarStrokeProperties(obj)
}

// 判断 fill 是否为线性渐变
function isLinearGradient(fill: any): boolean {
  return !!fill && typeof fill === 'object' && fill.type === 'linear'
}

// 同步渐变填充属性到工具栏
function syncToolbarGradientFill(fill: any) {
  toolFillMode.value = 'gradient'
  const stops = fill.colorStops || []
  toolGradientFrom.value = stops[0]?.color || '#3b82f6'
  toolGradientTo.value = stops[stops.length - 1]?.color || '#8b5cf6'
  const coords = fill.coords || {}
  const dx = (coords.x2 ?? 1) - (coords.x1 ?? 0)
  const dy = (coords.y2 ?? 0) - (coords.y1 ?? 0)
  toolGradientAngle.value = Math.round((Math.atan2(dy, dx) * 180 / Math.PI + 90 + 360) % 360)
}

// 同步纯色填充属性到工具栏
function syncToolbarSolidFill(fill: any) {
  toolFillMode.value = 'solid'
  toolFillColor.value = (typeof fill === 'string' && fill !== 'transparent') ? fill : '#ffffff'
}

// 同步描边/透明度/圆角属性到工具栏
function syncToolbarStrokeProperties(obj: any) {
  const stroke = (obj as any).stroke
  toolStrokeColor.value = (typeof stroke === 'string' && stroke !== 'transparent') ? stroke : '#000000'
  toolOpacity.value = Math.round((obj.opacity ?? 1) * 100)
  toolCornerRadius.value = (obj as any).rx || 0
}'''

src = src.replace(OLD_SYNC_SHAPE, NEW_SYNC_SHAPE)

with open(PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("Second pass complete.")
