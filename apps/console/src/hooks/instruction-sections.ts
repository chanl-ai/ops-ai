import { MENU_KINDS, SECTION_TITLES } from '@/lib/brief-sections';

export interface InstructionSectionItem {
  /** The tag stored on a brief's section and read by evals. */
  id: string;
  title: string;
}

const DEFAULT_LIST: InstructionSectionItem[] = MENU_KINDS.map((id) => ({ id, title: SECTION_TITLES[id] }));

/** The sections the Add section menu offers. Today the built-in list; it becomes a workspace setting. */
export const useInstructionSections = (): InstructionSectionItem[] => DEFAULT_LIST;
