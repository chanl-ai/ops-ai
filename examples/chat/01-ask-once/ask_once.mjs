import { OpsAI } from '@chanl-ai/ops-ai';

const ops = new OpsAI();
let agent;
for await (const row of ops.agents.list()) {
  if (row.status === 'published') {
    agent = row;
    break;
  }
}
const reply = await ops.agents.chat(agent.id, 'What documents open a business account?');
console.log(reply.reply);
