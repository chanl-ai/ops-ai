import { BookOpen, Briefcase, Heart, MessageCircle, Scale, Shield, Smile, Star, Sun, Zap, type LucideIcon } from 'lucide-react';

/** The icons a preset may carry, by the name the setting stores; a name not listed here draws no icon. */
export const PRESET_ICONS: Record<string, LucideIcon> = {
  smile: Smile,
  sun: Sun,
  scale: Scale,
  briefcase: Briefcase,
  zap: Zap,
  message: MessageCircle,
  heart: Heart,
  shield: Shield,
  star: Star,
  book: BookOpen,
};
