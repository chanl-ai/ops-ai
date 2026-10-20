"""The only modules in platform-service that touch the database (the drivers-only-in-stores import contract):
tables, the tenant transaction that row-level security reads, and repositories that declare the guarantees they rely
on."""
