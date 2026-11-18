#!/usr/bin/env bash
# Installs the ODBC Driver 18 for SQL Server the store opens its connections with.
# packages.microsoft.com answers with 429 under load; apt update/install are retried so a rate
# limit does not fail the whole job, and the script fails loudly once the attempts run out.
set -euo pipefail

# The runner image already lists Microsoft's repository (microsoft-prod.gpg); a second entry for the
# same source with another key file makes apt refuse to read its sources (exit 100), so ours is added
# only when the image lacks one.
if ! grep -rqs "packages.microsoft.com/ubuntu/24.04/prod" /etc/apt/sources.list /etc/apt/sources.list.d; then
  curl -fsSL --retry 5 --retry-all-errors --retry-delay 5 https://packages.microsoft.com/keys/microsoft.asc \
    | sudo gpg --dearmor --yes -o /usr/share/keyrings/microsoft.gpg
  echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/ubuntu/24.04/prod noble main" \
    | sudo tee /etc/apt/sources.list.d/mssql-release.list >/dev/null
fi

attempts=3
for attempt in $(seq "$attempts"); do
  if sudo apt-get -o Acquire::Retries=5 update -q \
    && sudo ACCEPT_EULA=Y apt-get -o Acquire::Retries=5 install -y msodbcsql18 unixodbc; then
    exit 0
  fi
  if [ "$attempt" -lt "$attempts" ]; then
    delay=$((attempt * 20))
    echo "::warning::SQL Server driver install failed (attempt $attempt of $attempts); retrying in ${delay}s"
    sleep "$delay"
  fi
done
echo "::error::SQL Server driver install failed after $attempts attempts"
exit 1
