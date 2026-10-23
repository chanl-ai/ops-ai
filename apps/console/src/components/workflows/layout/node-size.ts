import type { EngineNode, EngineNodeType } from '@/lib/types/engine';

import { inPorts, outPorts, repeatsOver, stepTitle } from '../definition-editor/graph.ts';

/** A step as the layout sees it: its box and the height of each port's handle, measured from the box's top. */
export interface NodeBox {
  id: string;
  width: number;
  height: number;
  inPorts: { name: string; y: number }[];
  outPorts: { name: string; y: number }[];
}

// The pixel sizes DefinitionNode draws (definition-node.tsx). The layout places steps and orders ports by these, so a
// change to the node's padding, rows or badges changes them too; the uc-486 check compares each step's measured height
// with `data-layout-height` within 2 px.
export const NODE_WIDTH = 288;
/**
 * The longest title drawn on one line. A longer one gets two lines (and a third and beyond are cut, with the full text
 * on hover). Counted in characters, so the height needs no DOM and the seed bake lays out as the browser does; 22
 * characters of the title font fit the title column whatever the letters.
 */
export const ONE_LINE_TITLE = 22;
export const titleLines = (title: string) => (title.length > ONE_LINE_TITLE ? 2 : 1);
const BORDER = 1;
const TRIGGER_BORDER = 2;
const HEADER_PAD = 20;
const ICON = 32;
const TITLE_LINE = 24;
const SMALL_LINE = 20;
const TRIGGER_ROW = 32;
const PORT_RULE = 1;
const PORT_PAD = 16;
const PORT_ROW = 20;
const PORT_GAP = 4;

/**
 * The size of a step and where its port handles sit, computed without a DOM so the editor, the run canvas, Tidy up
 * and the seed bake script all lay a definition out the same way. Only the title wraps, to the number of lines
 * `titleLines` gives, so the browser draws the height computed here.
 */
export function definitionNodeSize(node: EngineNode, type: EngineNodeType | undefined, nodes: EngineNode[]): NodeBox {
  const trigger = type?.group === 'trigger';
  const border = trigger || !type ? TRIGGER_BORDER : BORDER;
  const text = titleLines(stepTitle(node, type)) * TITLE_LINE + SMALL_LINE + (repeatsOver(node.parameters, nodes) ? SMALL_LINE : 0);
  const top = border + HEADER_PAD + Math.max(ICON, text) + (trigger ? TRIGGER_ROW : 0);
  const ins = type ? inPorts(type) : [];
  const outs = type ? outPorts(type, node.parameters) : [];
  const rows = Math.max(ins.length, outs.length);
  const portsTop = top + PORT_RULE + PORT_PAD / 2;
  const at = (i: number) => portsTop + i * (PORT_ROW + PORT_GAP) + PORT_ROW / 2;
  const portBlock = rows ? PORT_RULE + PORT_PAD + rows * PORT_ROW + (rows - 1) * PORT_GAP : 0;
  return {
    id: node.id,
    width: NODE_WIDTH,
    height: top + portBlock + border,
    inPorts: ins.map((p, i) => ({ name: p.name, y: at(i) })),
    outPorts: outs.map((p, i) => ({ name: p.name, y: at(i) })),
  };
}
