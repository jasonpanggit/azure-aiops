-- Explicit administrator bootstrap AFTER schema.sql. Roles only, no memberships.
IF DATABASE_PRINCIPAL_ID(N'publication_broker') IS NULL CREATE ROLE publication_broker AUTHORIZATION dbo;
IF DATABASE_PRINCIPAL_ID(N'publication_verifier') IS NULL CREATE ROLE publication_verifier AUTHORIZATION dbo;
IF DATABASE_PRINCIPAL_ID(N'publication_authority') IS NULL CREATE ROLE publication_authority AUTHORIZATION dbo;
IF DATABASE_PRINCIPAL_ID(N'publication_reader') IS NULL CREATE ROLE publication_reader AUTHORIZATION dbo;
IF DATABASE_PRINCIPAL_ID(N'publication_setup') IS NULL CREATE ROLE publication_setup AUTHORIZATION dbo;
GO
DENY SELECT, INSERT, UPDATE, DELETE ON SCHEMA::publication TO publication_broker;
DENY SELECT, INSERT, UPDATE, DELETE ON SCHEMA::publication TO publication_verifier;
DENY SELECT, INSERT, UPDATE, DELETE ON SCHEMA::publication TO publication_authority;
DENY SELECT, INSERT, UPDATE, DELETE ON SCHEMA::publication TO publication_reader;
GRANT EXECUTE ON OBJECT::publication.ProvisionTarget TO publication_setup;
GRANT EXECUTE ON OBJECT::publication.Acquire TO publication_broker;
GRANT EXECUTE ON OBJECT::publication.BeginAttempt TO publication_broker;
GRANT EXECUTE ON OBJECT::publication.CommitAttempt TO publication_broker;
GRANT EXECUTE ON OBJECT::publication.RecoverOutcome TO publication_broker;
GRANT EXECUTE ON OBJECT::publication.SealAttempt TO publication_verifier;
GRANT EXECUTE ON OBJECT::publication.RecordGrant TO publication_authority;
GRANT EXECUTE ON OBJECT::publication.[Revoke] TO publication_authority;
GRANT EXECUTE ON OBJECT::publication.ReadControl TO publication_broker;
GRANT EXECUTE ON OBJECT::publication.ReadAttempt TO publication_broker;
GRANT EXECUTE ON OBJECT::publication.ReadControl TO publication_reader;
GRANT EXECUTE ON OBJECT::publication.ReadAttempt TO publication_reader;
-- No users, managed-identity memberships, storage roles or runtime direct DML.
GO
