# Get help with Ops AI

Status: placeholder. The support contact is still to be named.

When something goes wrong in an install, the fastest route to an answer is to give the person helping you the facts
they would otherwise ask for one at a time. This page lists what to collect and where to send a report. A named support
contact, with hours, has not been published yet, and this page will say so until it has.

## What to send with a question

| Item | How to get it |
|---|---|
| The release version | The version `./install.sh status` prints on its first lines |
| The state of the install | The whole output of `./install.sh status` ([Monitor](../deploy/monitoring.md#check-the-install)) |
| The log lines of the service involved | `./install.sh logs <service>`, for example `./install.sh logs agents`, with any keys, tokens and passwords removed. Secret values are already masked in the logs |
| The install type and database | Script, Compose or Kubernetes, and PostgreSQL or SQL Server. Do not send `ops-ai.env`, because it holds your keys |
| What you did and what you expected | The steps, the time they ran and what you saw instead |

## Report a security problem

Report a vulnerability privately through GitHub. Open the repository's **Security** tab and choose **Report a
vulnerability**. Do not open a public issue, discussion or pull request for it. The maintainers acknowledge a report
within 3 business days, confirm or rule out the issue with a severity within 10 business days, and release a fix for a
critical or high issue within 30 days of confirmation.

## Where the source and documentation live

The Ops AI repository is at <https://github.com/chanl-ai/ops-ai>.
