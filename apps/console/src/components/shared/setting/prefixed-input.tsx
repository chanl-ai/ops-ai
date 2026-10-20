import * as React from 'react';

import { InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@/components/ui/input-group';

/** A field with a fixed prefix in front of it ("northfield.opsai.app/"): slugs and hostnames. */
export function PrefixedInput({ prefix, ...props }: { prefix: string } & React.ComponentProps<'input'>) {
  return (
    <InputGroup className="bg-card">
      <InputGroupAddon>
        <InputGroupText>{prefix}</InputGroupText>
      </InputGroupAddon>
      <InputGroupInput {...props} />
    </InputGroup>
  );
}
