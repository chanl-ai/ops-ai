// Proves uploaded bytes outlive a files-service redeploy: `put` uploads random bytes through the origin and prints
// the file id and their sha256; `get <id> <sha256>` reads the file back and checks the digest. Run put, redeploy
// the staging files service (<app-prefix>-files), then get.
//   OPS_SMOKE_EMAIL=... OPS_SMOKE_PASSWORD=... node deploy/fly/staging/bytes_survive.mjs <origin> put
//   OPS_SMOKE_EMAIL=... OPS_SMOKE_PASSWORD=... node deploy/fly/staging/bytes_survive.mjs <origin> get <id> <sha256>
import { createHash, randomBytes } from 'node:crypto';

const [origin, verb, id, want] = [process.argv[2]?.replace(/\/$/, ''), process.argv[3], process.argv[4], process.argv[5]];
const data = async (r) => {
  const body = await r.json().catch(() => ({}));
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
const session = await data(
  await fetch(`${origin}/api/platform/v1/auth/sign-in`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: process.env.OPS_SMOKE_EMAIL, password: process.env.OPS_SMOKE_PASSWORD }),
  }),
);
const as = { Authorization: `Bearer ${session.token}`, 'X-Team-Id': session.principal.teamId, 'Content-Type': 'application/json' };
const sha = (b) => createHash('sha256').update(b).digest('hex');

if (verb === 'put') {
  // Text, since files-service refuses bytes whose type it cannot recognise.
  const bytes = Buffer.from(`bytes that must survive a redeploy ${randomBytes(2048).toString('hex')}\n`);
  const ticket = await data(
    await fetch(`${origin}/api/files/v1/files/uploads`, {
      method: 'POST',
      headers: as,
      body: JSON.stringify({ name: `survives-${sha(bytes).slice(0, 8)}.txt`, size: bytes.length, mime: 'text/plain', purpose: 'case_attachment' }),
    }),
  );
  const put = await fetch(new URL(ticket.uploadUrl, origin), {
    method: 'PUT',
    headers: { Authorization: as.Authorization, 'X-Team-Id': as['X-Team-Id'], 'Content-Type': 'text/plain', ...ticket.headers },
    body: bytes,
  });
  const done = await data(await fetch(`${origin}/api/files/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers: as }));
  console.log(`put ${put.status}: ${done.file.id} ${sha(bytes)}`);
} else {
  const r = await fetch(`${origin}/api/files/v1/files/${id}/content`, { headers: as });
  const got = Buffer.from(await r.arrayBuffer());
  const ok = r.status === 200 && sha(got) === want;
  console.log(`${ok ? 'PASS' : 'FAIL'} the bytes read back after the redeploy: ${r.status}, ${got.length} bytes, sha256 ${sha(got)}`);
  process.exit(ok ? 0 : 1);
}
