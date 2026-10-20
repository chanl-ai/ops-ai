import Image from 'next/image';

import logoDark from '../../../../docs/media/logo-dark.svg';
import logoLight from '../../../../docs/media/logo-light.svg';

export const BRAND = 'Ops AI by Chanl AI';

/** The Ops AI mark from docs/media, one file per theme, with the brand line. */
export function Brand() {
  return (
    <span className="ops-brand">
      <Image src={logoLight} alt="" width={22} height={22} className="ops-logo-light" priority />
      <Image src={logoDark} alt="" width={22} height={22} className="ops-logo-dark" priority />
      <span className="ops-brand-text">
        <span className="ops-brand-name">Ops AI</span>
        <span className="ops-brand-by">by Chanl AI</span>
      </span>
    </span>
  );
}
