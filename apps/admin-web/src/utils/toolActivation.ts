import type { ExternalToolItem, ToolPayload } from '@/api/tools';
import { t } from '@/composables/i18n';

export const MCP_ENABLED_TOOL_LIMIT = 50;

type ToolLike = Pick<ExternalToolItem, 'type' | 'status' | 'config' | 'discoveredTools' | 'name'>;

export function enabledMcpToolNames(config: Record<string, any> | undefined): string[] {
  const values = Array.isArray(config?.enabledToolNames) ? config?.enabledToolNames : [];
  return Array.from(new Set(values.map((item: unknown) => String(item || '').trim()).filter(Boolean)));
}

export function mcpActivationError(tool: ToolLike | ToolPayload): string {
  if (tool.type !== 'mcp' || tool.status !== 'active') return '';
  const names = enabledMcpToolNames(tool.config);
  if (names.length === 0) {
    return t('请选择MCP工具', { count: MCP_ENABLED_TOOL_LIMIT });
  }
  if (names.length > MCP_ENABLED_TOOL_LIMIT) {
    return t('MCP工具超限', { selected: names.length, count: MCP_ENABLED_TOOL_LIMIT });
  }
  return '';
}

export function nextMcpToolSelection(current: string[], name: string, checked: boolean): { names: string[]; error: string } {
  const normalized = String(name || '').trim();
  const currentNames = Array.from(new Set(current.map((item) => String(item || '').trim()).filter(Boolean)));
  if (!normalized) return { names: currentNames, error: '' };
  if (!checked) {
    return { names: currentNames.filter((item) => item !== normalized), error: '' };
  }
  if (currentNames.includes(normalized)) return { names: currentNames, error: '' };
  if (currentNames.length >= MCP_ENABLED_TOOL_LIMIT) {
    return { names: currentNames, error: t('MCP工具最多', { count: MCP_ENABLED_TOOL_LIMIT }) };
  }
  return { names: [...currentNames, normalized], error: '' };
}

export function toolStatusConfirmText(tool: ToolLike, enabled: boolean): string {
  const name = tool.name || t('未命名工具');
  if (enabled) {
    return t('确认启用工具', { name });
  }
  return t('确认禁用工具', { name });
}
