import * as React from 'react';

/**
 * One entry of an ItemGroup, which is a list (role="list"): a list's children must be list items for a screen reader
 * to read it as one, and an Item rendered as a link keeps its link role inside this wrapper.
 */
export function ListItem(props: React.ComponentProps<'div'>) {
  return <div role="listitem" {...props} />;
}
