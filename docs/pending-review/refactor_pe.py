#!/usr/bin/env python3
"""Refactor PresentationEditor.vue to reduce complexity of 7 functions."""
import re, sys

PATH = "apps/user-web/src/components/PresentationEditor.vue"

with open(PATH, "r", encoding="utf-8") as f:
    src = f.read()

# ── Helper functions block (inserted before </script>) ──────────────
HELPERS = r'''
// ---------------------------------------------------------------------------
// Helpers — 抽出的辅助函数，用于降低主函数圈复杂度
// ---------------------------------------------------------------------------

const boxShadowPresets: Record<string, string> = {
  soft: '0 8px 24px rgba(15,23,42,0.10)',
  subtle: '0 4px 14px rgba(15,23,42,0.08)',
  medium: '0 10px 28px rgba(15,23,42,0.14)',
  strong: '0 16px 40px rgba(15,23,42,0.18)',
}

// 判断容器是否有可见的样式（背景 / 边框 / 阴影）
function hasVisibleContainerStyle(style: any): boolean {
  const bg = style.background || style.background_color || ''
  const hasBg = bg && !isTransparent(bg)
  const hasBorder = hasVisibleBorder(style)
  const hasShadow = hasBoxShadowStyle(style)
  return !!(hasBg || hasBorder || hasShadow)
}

// 解析边框颜色字符串
function resolveBorderColor(style: any): string {
  return style.border_color || style.border || ''
}

// 判断是否有可见边框
function hasVisibleBorder(style: any): boolean {
  const color = resolveBorderColor(style)
  if (color && !isTransparent(color)) return true
  return !!style.border_left || !!style.border_right || !!style.border_top || !!style.border_bottom
}

// 判断是否有 box-shadow 样式
function hasBoxShadowStyle(style: any): boolean {
  const v = style.box_shadow
  return !!v && v !== 'none'
}

// 将 box-shadow CSS 字符串解析为 Fabric Shadow 对象
function parseBoxShadowStyle(val: any): fabric.Shadow | undefined {
  const raw = String(val || '')
  const resolved = boxShadowPresets[raw.toLowerCase()] || raw
  const m = resolved.match(/(-?\d+)(?:px)?\s+(-?\d+)(?:px)?\s+(\d+)(?:px)?\s+(rgba?\([^)]+\)|#[0-9a-fA-F]{3,8})/)
  if (!m) return undefined
  return new fabric.Shadow({
    offsetX: parseInt(m[1]),
    offsetY: parseInt(m[2]),
    blur: parseInt(m[3]),
    color: m[4],
  })
}

// 将 Fabric fill 序列化回 CSS 字符串
function serializeFabricFill(fill: any): string {
  if (!fill) return 'transparent'
  if (typeof fill === 'string') return fill
  if (fill.type !== 'linear' || !fill.colorStops || fill.colorStops.length < 2) return 'transparent'
  const coords = fill.coords || {}
  const dx = (coords.x2 ?? 1) - (coords.x1 ?? 0)
  const dy = (coords.y2 ?? 0) - (coords.y1 ?? 0)
  const angle = Math.round((Math.atan2(dy, dx) * 180 / Math.PI + 90 + 360) % 360)
  const stops = fill.colorStops
    .map((s: any) => `${s.color} ${Math.round(s.offset * 100)}%`)
    .join(', ')
  return `linear-gradient(${angle}deg, ${stops})`
}

// 构建扁平的 block id → { block, parentRect, parentBlock } 映射
function buildFlatBlockMap(pageBlocks: any[]) {
  const blockMap = new Map<string, any>()
  const flatMap = new Map<string, { block: any; parentRect: { x: number; y: number; w: number; h: number }; parentBlock: any | null }>()
  const childIds = new Set<string>()
  for (const b of pageBlocks) {
    if (b.id) blockMap.set(b.id, b)
  }
  function collect(blocks: any[], parentBlock: any | null, parentRect: { x: number; y: number; w: number; h: number }) {
    for (const b of blocks) {
      if (!b || !b.id) continue
      if (parentBlock !== null) childIds.add(b.id)
      flatMap.set(b.id, { block: b, parentRect, parentBlock })
      if (b.children?.length) {
        const geom = resolveBlockGeometry(b, parentRect)
        collect(b.children, b, { x: geom.bx, y: geom.by, w: geom.bw, h: geom.bh })
      }
    }
  }
  collect(pageBlocks, null, { x: 0, y: 0, w: 1, h: 1 })
  return { blockMap, flatMap, childIds }
}

// 获取 block 的坐标空间
function getCoordinateSpace(block: any, entry?: any): string {
  return (block.coordinate_space || (entry && entry.parentBlock ? 'parent' : 'page')).toLowerCase()
}

// 将像素坐标写回 block（归一化到 0-1）
function writeBlockXY(block: any, entry: any, absPxLeft: number, absPxTop: number) {
  const space = getCoordinateSpace(block, entry)
  const nx = absPxLeft / CANVAS_W
  const ny = absPxTop / CANVAS_H
  if (space === 'parent' && entry.parentRect.w > 0 && entry.parentRect.h > 0) {
    block.x = (nx - entry.parentRect.x) / entry.parentRect.w
    block.y = (ny - entry.parentRect.y) / entry.parentRect.h
  } else {
    block.x = nx
    block.y = ny
  }
}

// 将像素尺寸写回 block（归一化到 0-1）
function writeBlockSize(block: any, entry: any, absPxW: number, absPxH: number) {
  const space = getCoordinateSpace(block, entry)
  const nw = absPxW / CANVAS_W
  const nh = absPxH / CANVAS_H
  if (space === 'parent' && entry.parentRect.w > 0 && entry.parentRect.h > 0) {
    block.w = nw / entry.parentRect.w
    block.h = nh / entry.parentRect.h
  } else {
    block.w = nw
    block.h = nh
  }
}

// 处理已有 block 的写回（line / text_box / 其他）
function writeExistingBlock(block: any, entry: any | undefined, blockType: string, obj: any) {
  if (blockType === 'line') return writeLineEndpoints(block, entry, obj)
  if (blockType === 'text_box' && obj instanceof fabric.Textbox) {
    writeTextBoxGeometry(block, entry, obj)
    saveTextBoxStyle(block, obj)
    return
  }
  writeGenericGeometry(block, entry, obj)
  saveShapeStyle(block, obj)
}

// 写入 line 端点
function writeLineEndpoints(block: any, entry: any | undefined, line: fabric.Line) {
  const endpoints = linePageEndpoints(line)
  if (!entry) {
    block.x = endpoints.start.x / CANVAS_W
    block.y = endpoints.start.y / CANVAS_H
    block.x2 = endpoints.end.x / CANVAS_W
    block.y2 = endpoints.end.y / CANVAS_H
    return
  }
  writeBlockXY(block, entry, endpoints.start.x, endpoints.start.y)
  const endX = endpoints.end.x / CANVAS_W
  const endY = endpoints.end.y / CANVAS_H
  const space = getCoordinateSpace(block, entry)
  if (space === 'parent' && entry.parentRect.w > 0 && entry.parentRect.h > 0) {
    block.x2 = (endX - entry.parentRect.x) / entry.parentRect.w
    block.y2 = (endY - entry.parentRect.y) / entry.parentRect.h
  } else {
    block.x2 = endX
    block.y2 = endY
  }
}

// 写入 text_box 几何
function writeTextBoxGeometry(block: any, entry: any | undefined, obj: fabric.Textbox) {
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
}

// 保存 text_box 样式
function saveTextBoxStyle(block: any, obj: fabric.Textbox) {
  block.content = obj.text || ''
  if (!block.style) block.style = {}
  block.style.font_size = obj.fontSize
  block.style.font_weight = obj.fontWeight === 'bold' ? 'bold' : undefined
  block.style.color = obj.fill as string
  block.style.text_align = obj.textAlign
  if (obj.opacity != null && obj.opacity < 1) block.style.opacity = obj.opacity
}

// 写入通用几何（非 line / text_box）
function writeGenericGeometry(block: any, entry: any | undefined, obj: any) {
  if (entry) {
    writeBlockXY(block, entry, obj.left || 0, obj.top || 0)
  } else {
    block.x = (obj.left || 0) / CANVAS_W
    block.y = (obj.top || 0) / CANVAS_H
  }
  const sx = obj.scaleX || 1
  const sy = obj.scaleY || 1
  if (Math.abs(sx - 1) > 0.001 || Math.abs(sy - 1) > 0.001) {
    const absW = (obj as any).width * sx
    const absH = (obj as any).height * sy
    if (entry) writeBlockSize(block, entry, absW, absH)
    else { block.w = absW / CANVAS_W; block.h = absH / CANVAS_H }
  }
}

// 保存 shape 样式
function saveShapeStyle(block: any, obj: any) {
  if (!block.style) block.style = {}
  block.style.background = serializeFabricFill((obj as any).fill)
  const stroke = (obj as any).stroke
  if (stroke && stroke !== 'transparent') block.style.border_color = stroke
  if (obj.opacity != null && obj.opacity < 1) block.style.opacity = obj.opacity
  if ((obj as any).rx) block.style.border_radius = (obj as any).rx
}

// 判断是否为 shape 类型
function isShapeType(t: string): boolean {
  return t === 'rectangle' || t === 'circle' || t === 'group'
}

// 创建新元素 block
function makeNewElementBlock(blockId: string, blockType: string, obj: any): any {
  return {
    id: blockId,
    type: blockType || 'text_box',
    coordinate_space: 'page',
    x: (obj.left || 0) / CANVAS_W,
    y: (obj.top || 0) / CANVAS_H,
    w: ((obj as any).width * (obj.scaleX || 1)) / CANVAS_W,
    h: ((obj as any).height * (obj.scaleY || 1)) / CANVAS_H,
    style: {},
    content: '',
    z_index: 5,
  }
}

// 保存新元素样式
function saveNewElementStyle(block: any, blockType: string, obj: any) {
  if (blockType === 'text_box' && obj instanceof fabric.Textbox) {
    block.content = obj.text || ''
    block.style.font_size = obj.fontSize
    block.style.font_weight = obj.fontWeight === 'bold' ? 'bold' : undefined
    block.style.color = obj.fill as string
    block.style.text_align = obj.textAlign
    if (obj.opacity != null && obj.opacity < 1) block.style.opacity = obj.opacity
    return
  }
  if (!isShapeType(blockType)) return
  block.style.background = serializeFabricFill((obj as any).fill)
  if ((obj as any).stroke && (obj as any).stroke !== 'transparent') block.style.border_color = (obj as any).stroke
  if (obj.opacity != null && obj.opacity < 1) block.style.opacity = obj.opacity
  block.style.border_radius = (obj as any).rx || 0
}

// 过滤掉已删除的顶层 block
function filterActiveCanvasBlocks(blocks: any[], canvasBlockIds: Set<string>): any[] {
  return blocks.filter((b: any) => canvasBlockIds.has(b.id) || b.children?.length)
}

// 同步文本工具栏
function syncToolbarText(obj: fabric.Textbox) {
  toolFontSize.value = obj.fontSize || 18
  toolColor.value = (obj.fill as string) || '#222222'
  toolBold.value = obj.fontWeight === 'bold'
  toolAlign.value = obj.textAlign || 'left'
}

// 同步图形工具栏
function syncToolbarShape(obj: any) {
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
}

// 判断是否为 Undo 快捷键
function isUndoShortcut(ctrlCmd: boolean, key: string, shift: boolean): boolean {
  return ctrlCmd && key === 'z' && !shift
}

// 判断是否为 Redo 快捷键
function isRedoShortcut(ctrlCmd: boolean, key: string, shift: boolean): boolean {
  return (ctrlCmd && key === 'z' && shift) || (ctrlCmd && key === 'y')
}

// 判断是否为 Delete 键
function isDeleteKey(key: string): boolean {
  return key === 'Delete' || key === 'Backspace'
}

// 判断是否为方向键
function isArrowKey(key: string): boolean {
  return key === 'ArrowLeft' || key === 'ArrowRight' || key === 'ArrowUp' || key === 'ArrowDown'
}

// 执行 Undo
function handleUndo(): void { undo() }

// 执行 Redo
function handleRedo(): void { redo() }

// 执行 Delete
function handleDelete(_e: KeyboardEvent): void {
  _e.preventDefault()
  saveUndoState()
  deleteSelected()
}

// 使用方向键移动选中对象
function handleArrowMove(active: fabric.FabricObject, key: string, step: number) {
  if (key === 'ArrowLeft') active.set('left', (active.left || 0) - step)
  else if (key === 'ArrowRight') active.set('left', (active.left || 0) + step)
  else if (key === 'ArrowUp') active.set('top', (active.top || 0) - step)
  else if (key === 'ArrowDown') active.set('top', (active.top || 0) + step)
  active.setCoords()
  fc?.renderAll()
}

// 计算目标对象的矩形
function computeTargetRect(target: fabric.FabricObject) {
  const tl = target.left || 0
  const tt = target.top || 0
  const tw = (target.width || 0) * (target.scaleX || 1)
  const th = (target.height || 0) * (target.scaleY || 1)
  return {
    tl, tt, tw, th,
    cx: tl + tw / 2,
    cy: tt + th / 2,
    right: tl + tw,
    bottom: tt + th,
  }
}

// 计算更新后的矩形
function computeUpdatedRect(target: fabric.FabricObject, tw: number, th: number) {
  const ul = target.left || 0
  const ut = target.top || 0
  return {
    ul, ut, tw, th,
    cx: ul + tw / 2,
    cy: ut + th / 2,
    right: ul + tw,
    bottom: ut + th,
  }
}

// 吸附到画布中心
function snapToCanvasCenter(target: fabric.FabricObject, tw: number, th: number, tCx: number, tCy: number) {
  const cCx = CANVAS_W / 2
  const cCy = CANVAS_H / 2
  let snappedX = false
  let snappedY = false
  if (Math.abs(tCx - cCx) < SNAP_THRESHOLD) {
    target.set('left', cCx - tw / 2)
    addGuideLine(cCx, 0, cCx, CANVAS_H)
    snappedX = true
  }
  if (Math.abs(tCy - cCy) < SNAP_THRESHOLD) {
    target.set('top', cCy - th / 2)
    addGuideLine(0, cCy, CANVAS_W, cCy)
    snappedY = true
  }
  return { snappedX, snappedY }
}

// 收集对齐/间距对齐的同层对象
function collectAlignmentPeers(fc: fabric.Canvas, target: fabric.FabricObject) {
  const canvasArea = CANVAS_W * CANVAS_H
  const others: { left: number; top: number; right: number; bottom: number; cx: number; cy: number }[] = []
  for (const obj of fc.getObjects()) {
    if (obj === target) continue
    if ((obj as any)._isGuide) continue
    if ((obj as any)._blockType === 'text_bg') continue
    if (!obj.selectable) continue
    const ol = obj.left || 0
    const ot = obj.top || 0
    const ow = (obj.width || 0) * (obj.scaleX || 1)
    const oh = (obj.height || 0) * (obj.scaleY || 1)
    if (ow < 1 || oh < 1) continue
    if (ow * oh >= canvasArea * 0.8) continue
    others.push({ left: ol, top: ot, right: ol + ow, bottom: ot + oh, cx: ol + ow / 2, cy: ot + oh / 2 })
  }
  return others
}

// 水平方向边吸附
function trySnapX(target: fabric.FabricObject, o: any, updatedLeft: number, updatedRight: number, updatedCx: number, tw: number): boolean {
  if (Math.abs(updatedLeft - o.left) < SNAP_THRESHOLD) {
    target.set('left', o.left)
    addGuideLine(o.left, 0, o.left, CANVAS_H)
    return true
  }
  if (Math.abs(updatedRight - o.right) < SNAP_THRESHOLD) {
    target.set('left', o.right - tw)
    addGuideLine(o.right, 0, o.right, CANVAS_H)
    return true
  }
  if (Math.abs(updatedLeft - o.right) < SNAP_THRESHOLD) {
    target.set('left', o.right)
    addGuideLine(o.right, 0, o.right, CANVAS_H)
    return true
  }
  if (Math.abs(updatedRight - o.left) < SNAP_THRESHOLD) {
    target.set('left', o.left - tw)
    addGuideLine(o.left, 0, o.left, CANVAS_H)
    return true
  }
  if (Math.abs(updatedCx - o.cx) < SNAP_THRESHOLD) {
    target.set('left', o.cx - tw / 2)
    addGuideLine(o.cx, 0, o.cx, CANVAS_H)
    return true
  }
  return false
}

// 垂直方向边吸附
function trySnapY(target: fabric.FabricObject, o: any, updatedTop: number, updatedBottom: number, updatedCy: number, th: number): boolean {
  if (Math.abs(updatedTop - o.top) < SNAP_THRESHOLD) {
    target.set('top', o.top)
    addGuideLine(0, o.top, CANVAS_W, o.top)
    return true
  }
  if (Math.abs(updatedBottom - o.bottom) < SNAP_THRESHOLD) {
    target.set('top', o.bottom - th)
    addGuideLine(0, o.bottom, CANVAS_W, o.bottom)
    return true
  }
  if (Math.abs(updatedTop - o.bottom) < SNAP_THRESHOLD) {
    target.set('top', o.bottom)
    addGuideLine(0, o.bottom, CANVAS_W, o.bottom)
    return true
  }
  if (Math.abs(updatedBottom - o.top) < SNAP_THRESHOLD) {
    target.set('top', o.top - th)
    addGuideLine(0, o.top, CANVAS_W, o.top)
    return true
  }
  if (Math.abs(updatedCy - o.cy) < SNAP_THRESHOLD) {
    target.set('top', o.cy - th / 2)
    addGuideLine(0, o.cy, CANVAS_W, o.cy)
    return true
  }
  return false
}

// 获取水平间距候选对（左右各一）
function findSpacingPeersX(others: any[], spacingPeers: any[], curCx: number, curTop: number, curBottom: number) {
  const yOverlap = (o: any) => o.bottom > curTop + 5 && o.top < curBottom - 5
  const toLeft = spacingPeers.filter((o: any) => o.cx < curCx && yOverlap(o)).sort((a: any, b: any) => b.right - a.right)
  const toRight = spacingPeers.filter((o: any) => o.cx > curCx && yOverlap(o)).sort((a: any, b: any) => a.left - b.left)
  return { toLeft, toRight }
}

// 获取垂直间距候选对（上下各一）
function findSpacingPeersY(others: any[], spacingPeers: any[], curLeft: number, curRight: number) {
  const xOverlap = (o: any) => o.right > curLeft + 5 && o.left < curRight - 5
  const above = spacingPeers.filter((o: any) => o.cy < curLeft && xOverlap(o)).sort((a: any, b: any) => b.bottom - a.bottom)
  const below = spacingPeers.filter((o: any) => o.cy > curRight && xOverlap(o)).sort((a: any, b: any) => a.top - b.top)
  return { above, below }
}

// 水平等距吸附（两侧邻居）
function tryApplySpacingXBetween(
  target: fabric.FabricObject, tw: number, th: number,
  nearL: any, nearR: any, curLeft: number, curRight: number, curTop: number,
): boolean {
  const gapL = curLeft - nearL.right
  const gapR = nearR.left - curRight
  if (gapL <= 2 || gapR <= 2 || Math.abs(gapL - gapR) >= SNAP_THRESHOLD) return false
  const avgGap = (nearL.right + nearR.left - tw) / 2
  target.set('left', avgGap)
  const markY = Math.max(nearL.top, curTop, nearR.top) +
    Math.min(nearL.bottom - nearL.top, th, nearR.bottom - nearR.top) / 2
  const snapLeft = avgGap
  const snapRight = avgGap + tw
  addGuideLine(nearL.right, markY, snapLeft, markY)
  addGuideLine(nearL.right, markY - 6, nearL.right, markY + 6)
  addGuideLine(snapLeft, markY - 6, snapLeft, markY + 6)
  addGuideLine(snapRight, markY, nearR.left, markY)
  addGuideLine(snapRight, markY - 6, snapRight, markY + 6)
  addGuideLine(nearR.left, markY - 6, nearR.left, markY + 6)
  return true
}

// 水平等距吸附（左侧两个邻居 — 末尾位置）
function tryApplySpacingXEndLeft(
  target: fabric.FabricObject, tw: number, th: number,
  a: any, b: any, curLeft: number, curTop: number,
): boolean {
  const existingGap = b.left - a.right
  const myGap = curLeft - b.right
  if (existingGap <= 2 || Math.abs(myGap - existingGap) >= SNAP_THRESHOLD) return false
  target.set('left', b.right + existingGap)
  const markY = Math.max(a.top, b.top, curTop) + Math.min(a.bottom - a.top, b.bottom - b.top, th) / 2
  addGuideLine(a.right, markY, b.left, markY)
  addGuideLine(a.right, markY - 6, a.right, markY + 6)
  addGuideLine(b.left, markY - 6, b.left, markY + 6)
  addGuideLine(b.right, markY, b.right + existingGap, markY)
  addGuideLine(b.right, markY - 6, b.right, markY + 6)
  addGuideLine(b.right + existingGap, markY - 6, b.right + existingGap, markY + 6)
  return true
}

// 水平等距吸附（右侧两个邻居 — 起始位置）
function tryApplySpacingXStartRight(
  target: fabric.FabricObject, tw: number, th: number,
  a: any, b: any, curRight: number, curTop: number,
): boolean {
  const existingGap = b.left - a.right
  const myGap = a.left - curRight
  if (existingGap <= 2 || Math.abs(myGap - existingGap) >= SNAP_THRESHOLD) return false
  target.set('left', a.left - existingGap - tw)
  const markY = Math.max(a.top, b.top, curTop) + Math.min(a.bottom - a.top, b.bottom - b.top, th) / 2
  addGuideLine(a.right, markY, b.left, markY)
  addGuideLine(a.right, markY - 6, a.right, markY + 6)
  addGuideLine(b.left, markY - 6, b.left, markY + 6)
  const snapRight = a.left - existingGap
  addGuideLine(snapRight, markY, a.left, markY)
  addGuideLine(snapRight, markY - 6, snapRight, markY + 6)
  addGuideLine(a.left, markY - 6, a.left, markY + 6)
  return true
}

// 垂直等距吸附（两侧邻居）
function tryApplySpacingYBetween(
  target: fabric.FabricObject, tw: number, th: number,
  nearA: any, nearB: any, curTop: number, curBottom: number, curLeft: number,
): boolean {
  const gapA = curTop - nearA.bottom
  const gapB = nearB.top - curBottom
  if (gapA <= 2 || gapB <= 2 || Math.abs(gapA - gapB) >= SNAP_THRESHOLD) return false
  const avgTop = (nearA.bottom + nearB.top - th) / 2
  target.set('top', avgTop)
  const markX = Math.max(nearA.left, curLeft, nearB.left) +
    Math.min(nearA.right - nearA.left, tw, nearB.right - nearB.left) / 2
  const snapTop = avgTop
  const snapBottom = avgTop + th
  addGuideLine(markX, nearA.bottom, markX, snapTop)
  addGuideLine(markX - 6, nearA.bottom, markX + 6, nearA.bottom)
  addGuideLine(markX - 6, snapTop, markX + 6, snapTop)
  addGuideLine(markX, snapBottom, markX, nearB.top)
  addGuideLine(markX - 6, snapBottom, markX + 6, snapBottom)
  addGuideLine(markX - 6, nearB.top, markX + 6, nearB.top)
  return true
}

// 垂直等距吸附（上方两个邻居 — 末尾位置）
function tryApplySpacingYEndAbove(
  target: fabric.FabricObject, tw: number, th: number,
  a: any, b: any, curTop: number, curLeft: number,
): boolean {
  const existingGap = b.top - a.bottom
  const myGap = curTop - b.bottom
  if (existingGap <= 2 || Math.abs(myGap - existingGap) >= SNAP_THRESHOLD) return false
  target.set('top', b.bottom + existingGap)
  const markX = Math.max(a.left, b.left, curLeft) + Math.min(a.right - a.left, b.right - b.left, tw) / 2
  addGuideLine(markX, a.bottom, markX, b.top)
  addGuideLine(markX - 6, a.bottom, markX + 6, a.bottom)
  addGuideLine(markX - 6, b.top, markX + 6, b.top)
  addGuideLine(markX, b.bottom, markX, b.bottom + existingGap)
  addGuideLine(markX - 6, b.bottom, markX + 6, b.bottom)
  addGuideLine(markX - 6, b.bottom + existingGap, markX + 6, b.bottom + existingGap)
  return true
}

// 垂直等距吸附（下方两个邻居 — 起始位置）
function tryApplySpacingYStartBelow(
  target: fabric.FabricObject, tw: number, th: number,
  a: any, b: any, curBottom: number, curLeft: number,
): boolean {
  const existingGap = b.top - a.bottom
  const myGap = a.top - curBottom
  if (existingGap <= 2 || Math.abs(myGap - existingGap) >= SNAP_THRESHOLD) return false
  target.set('top', a.top - existingGap - th)
  const markX = Math.max(a.left, b.left, curLeft) + Math.min(a.right - a.left, b.right - b.left, tw) / 2
  addGuideLine(markX, a.bottom, markX, b.top)
  addGuideLine(markX - 6, a.bottom, markX + 6, a.bottom)
  addGuideLine(markX - 6, b.top, markX + 6, b.top)
  const snapBottom = a.top - existingGap
  addGuideLine(markX, snapBottom, markX, a.top)
  addGuideLine(markX - 6, snapBottom, markX + 6, snapBottom)
  addGuideLine(markX - 6, a.top, markX + 6, a.top)
  return true
}

// 全屏页渲染：设置 StaticCanvas 尺寸
function setupFsCanvasCanvas(el: HTMLCanvasElement): fabric.StaticCanvas {
  const vw = window.innerWidth
  const vh = window.innerHeight
  const scale = Math.min(vw / CANVAS_W, vh / CANVAS_H)
  const dpr = window.devicePixelRatio || 1
  const canvas = new fabric.StaticCanvas(el, {
    width: CANVAS_W,
    height: CANVAS_H,
    enableRetinaScaling: false,
  })
  canvas.setDimensions({ width: Math.floor(CANVAS_W * scale), height: Math.floor(CANVAS_H * scale) }, { cssOnly: true } as any)
  canvas.setDimensions({ width: Math.floor(CANVAS_W * scale * dpr), height: Math.floor(CANVAS_H * scale * dpr) }, { backstoreOnly: true } as any)
  canvas.setZoom(scale * dpr)
  return canvas
}
'''

# ── New function bodies ──────────────────────────────────────────────

NEW_RENDER_BLOCK_CONTAINER = r'''function renderBlockContainer(
  blockId: string, style: any,
  left: number, top: number, width: number, height: number,
): boolean {
  if (!fc) return false
  if (!hasVisibleContainerStyle(style)) return false
  const bgVal = style.background || style.background_color || ''
  const hasBg = bgVal && !isTransparent(bgVal)
  const { stroke, strokeWidth } = resolveStroke(style)
  const opacity = style.opacity != null ? parseFloat(style.opacity) : 1.0
  const shadow = hasBoxShadowStyle(style) ? parseBoxShadowStyle(style.box_shadow) : undefined
  const rect = new fabric.Rect({
    left, top, width, height,
    fill: hasBg ? resolveBackground(bgVal, width, height) : '#ffffff',
    stroke, strokeWidth,
    rx: parseFloat(style.border_radius) || 0,
    ry: parseFloat(style.border_radius) || 0,
    opacity: isNaN(opacity) ? 1 : opacity,
    shadow: shadow || null,
    selectable: false, evented: false,
  })
  ;(rect as any)._blockId = blockId + '_container'
  ;(rect as any)._blockType = 'container'
  fc.add(rect)
  drawSideBorders(style, left, top, width, height)
  return true
}'''

NEW_ADD_BLOCK_TO_CANVAS = r'''function addBlockToCanvas(
  block: any,
  parentRect: { x: number; y: number; w: number; h: number },
) {
  if (!fc) return
  const type = (block.type || 'text_box').toLowerCase()
  const { bx, by, bw, bh, left, top, width, height } = resolveBlockGeometry(block, parentRect)
  const style = canonicalPresentationStyle(block.style, type)
  const bgVal = style.background || style.background_color || ''
  const { stroke, strokeWidth } = resolveStroke(style)
  const opacity = Number.isFinite(parseFloat(style.opacity)) ? parseFloat(style.opacity) : 1

  const addTextObject = (
    content: string,
    boxLeft: number,
    boxTop: number,
    boxWidth: number,
    boxHeight: number,
    textStyle: any,
    attachBlockIdentity = true,
  ) => {
    if (!fc || !content) return
    const insets = resolveTextInsets(textStyle.padding)
    const textWidth = Math.max(1, boxWidth - insets.left - insets.right)
    const fontSize = parseFloat(textStyle.font_size) || 18
    const lineHeight = parseFloat(textStyle.line_height) || 1.2
    const tb = new fabric.Textbox(content.replace(/\\n/g, '\n'), {
      left: boxLeft + insets.left,
      top: boxTop + insets.top,
      width: textWidth,
      fontSize,
      fontWeight: resolveFontWeight(textStyle.font_weight),
      fontStyle: textStyle.font_style === 'italic' ? 'italic' : 'normal',
      fill: textStyle.color || '#222222',
      textAlign: (textStyle.text_align || 'left') as any,
      fontFamily: textStyle.font_family || "'PingFang SC', 'Microsoft YaHei', sans-serif",
      lineHeight,
      splitByGrapheme: true,
      selectable: attachBlockIdentity,
      editable: attachBlockIdentity,
      opacity,
    })
    tb.set({
      top: resolveAlignedTextTop(
        boxTop,
        boxHeight,
        Number(tb.height || fontSize * lineHeight),
        insets,
        textStyle.vertical_align,
      ),
    })
    if (attachBlockIdentity) {
      ;(tb as any)._blockId = block.id
      ;(tb as any)._blockType = type
      ;(tb as any)._layoutBox = {
        left: boxLeft,
        top: boxTop,
        width: boxWidth,
        height: boxHeight,
        textLeft: Number(tb.left || 0),
        textTop: Number(tb.top || 0),
        textWidth: Number(tb.width || textWidth),
      }
    } else {
      ;(tb as any)._isGuide = true
      ;(tb as any)._blockType = 'container-label'
    }
    fc.add(tb)
  }

  const handlers: Record<string, () => void> = {
    rectangle: () => addRectangleToCanvas(fc, block, style, left, top, width, height, stroke, strokeWidth, opacity, bgVal, bx, by, bw, bh, type),
    circle: () => addCircleToCanvas(fc, block, style, left, top, width, height, stroke, strokeWidth, opacity, bgVal, type, addTextObject),
    text_box: () => addTextBoxToCanvas(fc, block, style, left, top, width, height, addTextObject),
    line: () => addLineToCanvas(fc, block, style, left, top, width, height, opacity, bx, by, type, parentRect),
    icon: () => addIconToCanvas(fc, block, style, left, top, width, height, type),
    chart: () => addChartToCanvas(fc, block, style, left, top, width, height, type),
    image: () => addImageToCanvas(fc, block, style, left, top, width, height, type),
  }
  const h = handlers[type]
  if (h) h()
}'''

NEW_CANVAS_TO_BLUEPRINT = r'''function canvasToBlueprint(): any {
  if (!fc) return getWorkingBlueprint()
  const bp = JSON.parse(JSON.stringify(getWorkingBlueprint()))
  const page = bp.pages[currentPageIndex.value]
  if (!page) return bp

  const { blockMap, flatMap } = buildFlatBlockMap(page.blocks)
  const objects = fc.getObjects()
  const canvasBlockIds = new Set<string>()

  for (const obj of objects) {
    if ((obj as any)._isGuide) continue
    const blockId = (obj as any)._blockId as string
    const blockType = (obj as any)._blockType as string
    if (!blockId || blockType === 'text_bg' || blockType === 'container') continue
    if (blockType === 'icon') { canvasBlockIds.add(blockId); continue }
    canvasBlockIds.add(blockId)

    const entry = flatMap.get(blockId)
    const block = entry?.block || blockMap.get(blockId)
    if (block) {
      if (blockType === 'line') {
        writeLineEndpoints(block, entry, obj as fabric.Line)
      } else if (blockType === 'text_box' && obj instanceof fabric.Textbox) {
        writeTextBoxGeometry(block, entry, obj)
        saveTextBoxStyle(block, obj)
      } else {
        writeGenericGeometry(block, entry, obj)
        saveShapeStyle(block, obj)
      }
    } else {
      const newBlock = makeNewElementBlock(blockId, blockType, obj)
      saveNewElementStyle(newBlock, blockType, obj)
      page.blocks.push(newBlock)
    }
  }

  page.blocks = filterActiveCanvasBlocks(page.blocks, canvasBlockIds)
  workingBlueprint.value = bp
  return bp
}'''

NEW_SYNC_TOOLBAR = r'''function syncToolbarFromSelection() {
  const obj = fc?.getActiveObject()
  selectedObj.value = obj || null
  selectedIsText.value = obj instanceof fabric.Textbox
  selectedIsShape.value = !!(obj && !selectedIsText.value && !(obj as any)._isGuide)
  if (obj instanceof fabric.Textbox) {
    syncToolbarText(obj)
  } else if (selectedIsShape.value && obj) {
    syncToolbarShape(obj)
  }
}'''

NEW_ON_KEYDOWN = r'''function onKeyDown(e: KeyboardEvent) {
  if (!fc || isFullscreen.value) return
  const active = fc.getActiveObject()
  if (active instanceof fabric.Textbox && active.isEditing) return

  const isCtrlOrCmd = e.ctrlKey || e.metaKey
  const step = e.shiftKey ? 10 : 1

  if (isUndoShortcut(isCtrlOrCmd, e.key, e.shiftKey)) {
    e.preventDefault()
    handleUndo()
    return
  }
  if (isRedoShortcut(isCtrlOrCmd, e.key, e.shiftKey)) {
    e.preventDefault()
    handleRedo()
    return
  }
  if (isDeleteKey(e.key)) {
    handleDelete(e)
    return
  }
  if (!active) return
  if (isArrowKey(e.key)) {
    e.preventDefault()
    saveUndoState()
    handleArrowMove(active, e.key, step)
  }
}'''

NEW_ON_OBJECT_MOVING = r'''function onObjectMoving(e: any) {
  if (!fc) return
  const target = e.target as fabric.FabricObject
  if (!target || (target as any)._isGuide) return

  clearGuides()

  const r = computeTargetRect(target)
  const c = snapToCanvasCenter(target, r.tw, r.th, r.cx, r.cy)
  const others = collectAlignmentPeers(fc, target)

  const up = computeUpdatedRect(target, r.tw, r.th)
  for (const o of others) {
    if (!c.snappedX) c.snappedX = trySnapX(target, o, up.ul, up.right, up.cx, r.tw)
    if (!c.snappedY) c.snappedY = trySnapY(target, o, up.ut, up.bottom, up.cy, r.th)
    if (c.snappedX && c.snappedY) break
  }

  const cur = computeCurrentRect(target)
  const { toLeft, toRight } = findSpacingPeersX(others, others, cur.cx, cur.top, cur.bottom)
  const { above, below } = findSpacingPeersY(others, others, cur.left, cur.right)

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

  target.setCoords()
  fc.renderAll()
}'''

# Add computeCurrentRect to helpers
COMPUTE_CURRENT_RECT = r'''
// 计算当前矩形（用于间距计算）
function computeCurrentRect(target: fabric.FabricObject) {
  const cl = target.left || 0
  const ct = target.top || 0
  const tw = (target.width || 0) * (target.scaleX || 1)
  const th = (target.height || 0) * (target.scaleY || 1)
  return {
    left: cl, top: ct, right: cl + tw, bottom: ct + th,
    cx: cl + tw / 2, cy: ct + th / 2,
    tw, th,
  }
}
'''

NEW_RENDER_FS_PAGE = r'''function renderFsPage(idx: number) {
  if (!fsCanvasEl.value) return
  if (fsFc) { fsFc.dispose(); fsFc = null }

  fsFc = setupFsCanvasCanvas(fsCanvasEl.value)

  const bp = getWorkingBlueprint()
  const page = bp.pages?.[idx]
  if (!page) return

  const pageBg = page.style?.background || page.style?.background_color || bp.theme?.page_background || '#ffffff'
  const bgParsed = parseLinearGradient(pageBg)
  if (bgParsed) {
    fsFc.add(new fabric.Rect({
      left: 0, top: 0, width: CANVAS_W, height: CANVAS_H,
      fill: makeFabricGradient(pageBg, CANVAS_W, CANVAS_H),
      selectable: false, evented: false,
    }))
  } else {
    fsFc.backgroundColor = isTransparent(pageBg) ? '#ffffff' : pageBg
  }

  const origFc = fc
  fc = fsFc as any
  const blocks = [...(page.blocks || [])].sort((a: any, b: any) => (a.z_index || 0) - (b.z_index || 0))
  for (const block of blocks) {
    addBlockToCanvas(block, { x: 0, y: 0, w: 1, h: 1 })
  }
  fc = origFc
  fsFc.renderAll()
}'''

# ── addBlockToCanvas per-type handlers (additional helpers) ─────────
ADD_BLOCK_HANDLERS = r'''
// 将 rectangle/group 类型渲染到画布
function addRectangleToCanvas(
  fc: fabric.Canvas, block: any, style: any,
  left: number, top: number, width: number, height: number,
  stroke: string, strokeWidth: number, opacity: number,
  bgVal: string, bx: number, by: number, bw: number, bh: number, type: string,
) {
  const shapeShadow = hasBoxShadowStyle(style) ? parseBoxShadowStyle(style.box_shadow) : undefined
  const rect = new fabric.Rect({
    left, top, width, height,
    fill: resolveBackground(bgVal, width, height),
    stroke, strokeWidth,
    rx: parseFloat(style.border_radius) || 0,
    ry: parseFloat(style.border_radius) || 0,
    shadow: shapeShadow || null,
    opacity,
    selectable: true,
  })
  ;(rect as any)._blockId = block.id
  ;(rect as any)._blockType = type
  fc.add(rect)
  drawSideBorders(style, left, top, width, height)
  const childRect = { x: bx, y: by, w: bw, h: bh }
  for (const child of (block.children || [])) {
    addBlockToCanvas(child, childRect)
  }
}

// 将 circle 类型渲染到画布
function addCircleToCanvas(
  fc: fabric.Canvas, block: any, style: any,
  left: number, top: number, width: number, height: number,
  stroke: string, strokeWidth: number, opacity: number,
  bgVal: string, type: string,
  addTextObject: (content: string, boxLeft: number, boxTop: number, boxWidth: number, boxHeight: number, textStyle: any, attachBlockIdentity: boolean) => void,
) {
  const r = Math.min(width, height) / 2
  const circle = new fabric.Circle({
    left, top, radius: r,
    fill: resolveBackground(bgVal, r * 2, r * 2),
    stroke, strokeWidth,
    opacity,
    selectable: true,
  })
  ;(circle as any)._blockId = block.id
  ;(circle as any)._blockType = type
  fc.add(circle)
  addTextObject(block.content || '', left, top, r * 2, r * 2, {
    ...style,
    text_align: style.text_align || 'center',
    vertical_align: style.vertical_align || 'middle',
  }, false)
}

// 将 text_box 类型渲染到画布
function addTextBoxToCanvas(
  fc: fabric.Canvas, block: any, style: any,
  left: number, top: number, width: number, height: number,
  addTextObject: (content: string, boxLeft: number, boxTop: number, boxWidth: number, boxHeight: number, textStyle: any, attachBlockIdentity: boolean) => void,
) {
  renderBlockContainer(block.id, style, left, top, width, height)
  addTextObject(block.content || '', left, top, width, height, style)
}

// 将 line 类型渲染到画布
function addLineToCanvas(
  fc: fabric.Canvas, block: any, style: any,
  left: number, top: number, width: number, height: number,
  opacity: number, bx: number, by: number, type: string,
  parentRect: { x: number; y: number; w: number; h: number },
) {
  const coordSpace = (block.coordinate_space || 'page').toLowerCase()
  const endpointX = block.x2 ?? block.x ?? 0
  const endpointY = block.y2 ?? block.y ?? 0
  const x1 = bx * CANVAS_W
  const y1 = by * CANVAS_H
  const x2 = (coordSpace === 'parent' ? parentRect.x + endpointX * parentRect.w : endpointX) * CANVAS_W
  const y2 = (coordSpace === 'parent' ? parentRect.y + endpointY * parentRect.h : endpointY) * CANVAS_H
  const lineColor = style.color || style.background || '#000000'
  const lineWeight = parseFloat(style.line_weight) || 2
  const line = new fabric.Line([x1, y1, x2, y2], {
    stroke: isTransparent(lineColor) ? '#000' : lineColor,
    strokeWidth: lineWeight,
    opacity,
    selectable: true,
  })
  ;(line as any)._blockId = block.id
  ;(line as any)._blockType = type
  fc.add(line)
}

// 将 icon 类型渲染到画布
function addIconToCanvas(
  fc: fabric.Canvas, block: any, style: any,
  left: number, top: number, width: number, height: number, type: string,
) {
  renderBlockContainer(block.id, style, left, top, width, height)
  let iconName = (block.icon || block.content || 'sparkles').trim()
  iconName = iconName.replace(/^(tabler:|icon[-:])/i, '').trim() || 'sparkles'
  const iconColor = style.color || props.blueprint?.theme?.accent_color || '#3b82f6'
  const colorHex = iconColor.replace('#', '')
  const canvas = fc
  const ocW = Math.max(Math.round(width), 8) * 2
  const ocH = Math.max(Math.round(height), 8) * 2
  const svgUrl = `/askai-api/api/icons/${encodeURIComponent(iconName)}.svg?color=${colorHex}`
  const img = new Image()
  img.crossOrigin = 'anonymous'
  img.onload = () => {
    if (!canvas) return
    const oc = document.createElement('canvas')
    oc.width = ocW
    oc.height = ocH
    const ctx = oc.getContext('2d')!
    ctx.clearRect(0, 0, ocW, ocH)
    const iconSize = Math.min(ocW, ocH)
    const dx = (ocW - iconSize) / 2
    const dy = (ocH - iconSize) / 2
    ctx.drawImage(img, dx, dy, iconSize, iconSize)
    const fabricImg = new fabric.FabricImage(oc, {
      left,
      top,
      scaleX: width / ocW,
      scaleY: height / ocH,
      selectable: true,
      objectCaching: false,
    })
    ;(fabricImg as any)._blockId = block.id
    ;(fabricImg as any)._blockType = type
    canvas.add(fabricImg)
    canvas.renderAll()
  }
  img.onerror = () => addIconFallback(canvas!, block.id, type, left, top, width, height, iconName, iconColor)
  img.src = svgUrl
}

// 将 chart 类型渲染到画布
function addChartToCanvas(
  fc: fabric.Canvas, block: any, style: any,
  left: number, top: number, width: number, height: number, type: string,
) {
  renderBlockContainer(block.id, style, left, top, width, height)
  const chartType = block.chart_type || ''
  const chartData = block.chart_data || {}
  const chartTitle = chartData.title || block.content || t('ppt.chart_placeholder')
  const canvas = fc
  const pxW = Math.round(Math.max(width, 160))
  const pxH = Math.round(Math.max(height, 120))
  const theme = props.blueprint?.theme || {}
  const chartTheme = {
    accent_color: theme.accent_color || '#2563eb',
    title_color: theme.title_color || '#0f172a',
    body_color: theme.body_color || '#334155',
    muted_color: theme.muted_color || '#64748b',
    surface_background: theme.surface_background || '#ffffff',
    page_background: theme.page_background || '#ffffff',
  }
  if (chartType) {
    fetch('/askai-api/api/documents/render-chart-svg', {
      method: 'POST',
      headers: authenticatedJsonHeaders(),
      body: JSON.stringify({
        chart_type: chartType,
        chart_data: chartData,
        width: pxW,
        height: pxH,
        theme: chartTheme,
      }),
    })
      .then(r => r.ok ? r.text() : Promise.reject('chart render failed'))
      .then(svgStr => {
        if (!canvas) return
        const dataUrl = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svgStr)
        return fabric.FabricImage.fromURL(dataUrl).then((img: any) => {
          if (!canvas) return
          const imgW = img.width || pxW
          const imgH = img.height || pxH
          img.set({
            left, top,
            scaleX: width / imgW,
            scaleY: height / imgH,
            selectable: true,
          })
          ;(img as any)._blockId = block.id
          ;(img as any)._blockType = type
          canvas.add(img)
          canvas.renderAll()
        })
      })
      .catch(() => {
        addChartPlaceholder(canvas!, block.id, type, left, top, width, height, chartTitle)
      })
  } else {
    addChartPlaceholder(canvas!, block.id, type, left, top, width, height, chartTitle)
  }
}

// 将 image 类型渲染到画布
function addImageToCanvas(
  fc: fabric.Canvas, block: any, style: any,
  left: number, top: number, width: number, height: number, type: string,
) {
  renderBlockContainer(block.id, style, left, top, width, height)
  const src = String(block.content || '').trim()
  const isRealUrl = src.startsWith('http://') || src.startsWith('https://') || src.startsWith('/')
  if (isRealUrl) {
    const canvasRef = fc!
    const slot = new fabric.Rect({
      left, top, width, height,
      fill: '#e8ecf0',
      stroke: '#b0b8c4',
      strokeWidth: 1,
      strokeDashArray: [4, 4],
      rx: 8, ry: 8,
      selectable: false,
      evented: false,
    })
    ;(slot as any)._blockId = block.id + '_image_slot'
    ;(slot as any)._blockType = 'container'
    ;(slot as any)._isGuide = true
    canvasRef.add(slot)
    const nativeImg = new Image()
    const radiusPx = (() => {
      const r = parseFloat(String(style.border_radius ?? style.borderRadius ?? '')) || 12
      return Math.max(0, Math.min(r, Math.min(width, height) / 2))
    })()
    nativeImg.onload = () => {
      if (!canvasRef) return
      const iw = nativeImg.naturalWidth || nativeImg.width || 1
      const ih = nativeImg.naturalHeight || nativeImg.height || 1
      const dpr = 2
      const ocW = Math.max(Math.round(width), 8) * dpr
      const ocH = Math.max(Math.round(height), 8) * dpr
      const oc = document.createElement('canvas')
      oc.width = ocW
      oc.height = ocH
      const ctx = oc.getContext('2d')!
      const r = radiusPx * dpr
      ctx.beginPath()
      ctx.moveTo(r, 0)
      ctx.lineTo(ocW - r, 0)
      ctx.quadraticCurveTo(ocW, 0, ocW, r)
      ctx.lineTo(ocW, ocH - r)
      ctx.quadraticCurveTo(ocW, ocH, ocW - r, ocH)
      ctx.lineTo(r, ocH)
      ctx.quadraticCurveTo(0, ocH, 0, ocH - r)
      ctx.lineTo(0, r)
      ctx.quadraticCurveTo(0, 0, r, 0)
      ctx.closePath()
      ctx.clip()
      const scale = Math.max(ocW / iw, ocH / ih)
      const drawW = iw * scale
      const drawH = ih * scale
      const dx = (ocW - drawW) / 2
      const dy = (ocH - drawH) / 2
      ctx.drawImage(nativeImg, dx, dy, drawW, drawH)
      const fabricImg = new fabric.FabricImage(oc, {
        left, top,
        scaleX: width / ocW,
        scaleY: height / ocH,
        selectable: true,
        objectCaching: false,
      })
      ;(fabricImg as any)._blockId = block.id
      ;(fabricImg as any)._blockType = type
      const objs = canvasRef.getObjects()
      const slotIndex = objs.indexOf(slot as any)
      canvasRef.remove(slot)
      canvasRef.add(fabricImg)
      if (slotIndex >= 0 && typeof (canvasRef as any).moveObjectTo === 'function') {
        ;(canvasRef as any).moveObjectTo(fabricImg, slotIndex)
      } else if (slotIndex >= 0 && typeof (fabricImg as any).moveTo === 'function') {
        ;(fabricImg as any).moveTo(slotIndex)
      }
      canvasRef.renderAll()
    }
    nativeImg.onerror = () => {
      if (canvasRef) canvasRef.remove(slot)
      addImagePlaceholder(fc!, block, type, left, top, width, height)
    }
    nativeImg.src = src
  } else {
    addImagePlaceholder(fc!, block, type, left, top, width, height)
  }
}
'''

# ── Perform replacements ────────────────────────────────────────────

def replace_between(src: str, start_marker: str, end_marker: str, new_text: str, label: str) -> str:
    """Replace content between start_marker and end_marker (exclusive)."""
    start_idx = src.find(start_marker)
    if start_idx == -1:
        raise ValueError(f"Could not find start marker for {label}")
    end_idx = src.find(end_marker, start_idx + len(start_marker))
    if end_idx == -1:
        raise ValueError(f"Could not find end marker for {label}")
    # New text includes everything from start_marker up to but not including end_marker
    return src[:start_idx] + new_text + src[end_idx:]

# 1. renderBlockContainer — replace from "function renderBlockContainer(" to the line before "// Draw single-side borders"
src = replace_between(
    src,
    "function renderBlockContainer(",
    "// Draw single-side borders",
    NEW_RENDER_BLOCK_CONTAINER + "\n\n",
    "renderBlockContainer",
)

# 2. addBlockToCanvas — replace from "function addBlockToCanvas(" to the line before "// ---------------------------------------------------------------------------\n// Fabric"
src = replace_between(
    src,
    "function addBlockToCanvas(",
    "// ---------------------------------------------------------------------------\n// Fabric → Blueprint (save back)",
    NEW_ADD_BLOCK_TO_CANVAS + "\n",
    "addBlockToCanvas",
)

# 3. canvasToBlueprint — replace from "function canvasToBlueprint():" to the line before "function findBlockById"
src = replace_between(
    src,
    "function canvasToBlueprint():",
    "function findBlockById(",
    NEW_CANVAS_TO_BLUEPRINT + "\n\n",
    "canvasToBlueprint",
)

# 4. syncToolbarFromSelection — replace from "function syncToolbarFromSelection()" to the line before "function onSelectionCreated"
src = replace_between(
    src,
    "function syncToolbarFromSelection() {",
    "function onSelectionCreated()",
    NEW_SYNC_TOOLBAR + "\n\n",
    "syncToolbarFromSelection",
)

# 5. onKeyDown — replace from "function onKeyDown(e: KeyboardEvent)" to the line before "// ---------------------------------------------------------------------------\n// Smart alignment guides"
src = replace_between(
    src,
    "function onKeyDown(e: KeyboardEvent) {",
    "// ---------------------------------------------------------------------------\n// Smart alignment guides",
    NEW_ON_KEYDOWN + "\n\n",
    "onKeyDown",
)

# 6. onObjectMoving — replace from "function onObjectMoving(e: any)" to the line before "function onObjectModified"
src = replace_between(
    src,
    "function onObjectMoving(e: any) {",
    "function onObjectModified()",
    NEW_ON_OBJECT_MOVING + "\n\n",
    "onObjectMoving",
)

# 7. renderFsPage — replace from "function renderFsPage(idx: number)" to the line before "function fsNext"
src = replace_between(
    src,
    "function renderFsPage(idx: number) {",
    "function fsNext()",
    NEW_RENDER_FS_PAGE + "\n\n",
    "renderFsPage",
)

# 8. Insert all helpers before </script>
helpers_block = HELPERS + COMPUTE_CURRENT_RECT + ADD_BLOCK_HANDLERS
src = src.replace("</script>", helpers_block + "\n</script>")

# Write back
with open(PATH, "w", encoding="utf-8") as f:
    f.write(src)

print("Refactoring complete. Lines:", len(src.split("\n")))
