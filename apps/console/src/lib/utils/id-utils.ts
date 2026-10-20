/**
 * ID Utility Functions
 *
 * Centralized utilities for handling MongoDB ObjectId and ID conversions.
 * This eliminates duplicate ID extraction logic across the codebase.
 */

import { logger } from './logger';

/**
 * Extract a string ID from various ID formats
 *
 * Handles:
 * - String IDs: "507f1f77bcf86cd799439011"
 * - MongoDB ObjectIds: ObjectId("507f1f77bcf86cd799439011")
 * - Populated objects: { _id: "...", id: "...", ... }
 * - Mixed types from Mongoose populate()
 *
 * @param item - The item to extract ID from
 * @returns Normalized string ID or empty string if extraction fails
 */
export function extractId(item: any): string {
  try {
    // Already a string
    if (typeof item === 'string') {
      return item;
    }

    // Object with _id or id field (populated document)
    if (typeof item === 'object' && item !== null) {
      const id = item._id?.toString() || item.id?.toString() || item.toString();
      return id;
    }

    // Fallback: try toString()
    return item?.toString() || '';
  } catch (error) {
    logger.error('Failed to extract ID:', error, item);
    return '';
  }
}

/**
 * Extract string IDs from an array of mixed ID formats
 *
 * @param items - Array of items that may be strings, ObjectIds, or populated objects
 * @returns Array of normalized string IDs (empty strings filtered out)
 */
export function extractIds(items: any[]): string[] {
  if (!Array.isArray(items)) {
    logger.warn('extractIds called with non-array:', items);
    return [];
  }

  return items.map(extractId).filter(Boolean); // Remove empty strings
}

/**
 * Check if two ID arrays are equivalent
 * Useful for preventing unnecessary re-renders when comparing ID arrays
 *
 * @param arr1 - First array of IDs (any format)
 * @param arr2 - Second array of IDs (any format)
 * @returns true if arrays contain the same IDs in the same order
 */
export function areIdArraysEqual(arr1: any[], arr2: any[]): boolean {
  if (!Array.isArray(arr1) || !Array.isArray(arr2)) {
    return false;
  }

  if (arr1.length !== arr2.length) {
    return false;
  }

  const ids1 = extractIds(arr1);
  const ids2 = extractIds(arr2);

  return ids1.every((id, index) => id === ids2[index]);
}

/**
 * Format a MongoDB ObjectId as a short ID with # prefix
 * Shows only the last 6 characters for UI display
 *
 * @param id - Full MongoDB ObjectId string
 * @returns Formatted short ID (e.g., "#439011")
 */
export function formatShortId(id: string): string {
  if (!id || typeof id !== 'string') {
    return '-';
  }

  // MongoDB ObjectIds are 24 characters - take last 6
  const shortId = id.slice(-6);
  return `#${shortId}`;
}

/**
 * Generate a unique ID for client-side use
 * This is for mock data and temporary IDs before server assignment
 *
 * @returns A unique string ID
 */
export function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
}
