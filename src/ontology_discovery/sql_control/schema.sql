-- Explicit administrator migration. Never executed on module import.
-- Azure SQL control DB only; not a Fabric Lakehouse analytics endpoint.
SET XACT_ABORT ON;
GO
IF SCHEMA_ID(N'publication') IS NULL EXEC(N'CREATE SCHEMA publication AUTHORIZATION dbo');
GO
IF OBJECT_ID(N'publication.SchemaVersion', N'U') IS NULL
BEGIN
    CREATE TABLE publication.SchemaVersion (Version int NOT NULL PRIMARY KEY);
    INSERT publication.SchemaVersion VALUES (1);
END;
IF (SELECT COUNT(*) FROM publication.SchemaVersion) <> 1
   OR NOT EXISTS (SELECT 1 FROM publication.SchemaVersion WHERE Version = 1)
    THROW 51000, 'publication_schema_version', 1;
GO
IF OBJECT_ID(N'publication.Target', N'U') IS NULL
BEGIN
    CREATE TABLE publication.Target (
        TargetId uniqueidentifier NOT NULL PRIMARY KEY,
        TargetJson nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL CHECK (ISJSON(TargetJson) = 1),
        AccountResourceId nvarchar(512) COLLATE Latin1_General_100_BIN2 NOT NULL,
        BlobEndpoint nvarchar(512) COLLATE Latin1_General_100_BIN2 NOT NULL,
        ContainerName nvarchar(63) COLLATE Latin1_General_100_BIN2 NOT NULL,
        RequiredRetainUntil datetime2(7) NOT NULL,
        OwnerId uniqueidentifier NULL,
        SessionId uniqueidentifier NULL,
        Epoch bigint NOT NULL DEFAULT 0 CHECK (Epoch >= 0),
        Revision bigint NOT NULL DEFAULT 0 CHECK (Revision >= 0),
        SessionDeadline datetime2(7) NULL,
        ActiveAttempt uniqueidentifier NULL,
        ActiveDigest binary(32) NULL
    );
    CREATE TABLE publication.Attempt (
        AttemptId uniqueidentifier NOT NULL PRIMARY KEY,
        TargetId uniqueidentifier NOT NULL REFERENCES publication.Target(TargetId),
        OwnerId uniqueidentifier NOT NULL,
        SessionId uniqueidentifier NOT NULL,
        Epoch bigint NOT NULL,
        CandidateJson nvarchar(max) COLLATE Latin1_General_100_BIN2 NOT NULL CHECK (ISJSON(CandidateJson) = 1),
        CatalogJson nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL CHECK (ISJSON(CatalogJson) = 1),
        CatalogDigest binary(32) NULL,
        InventoryJson nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL CHECK (ISJSON(InventoryJson) = 1),
        InventoryDigest binary(32) NULL,
        EvidenceJson nvarchar(max) COLLATE Latin1_General_100_BIN2 NULL CHECK (ISJSON(EvidenceJson) = 1),
        EvidenceDigest binary(32) NULL,
        VerifierPrincipal sysname NULL,
        RetainUntil datetime2(7) NULL,
        SealedAt datetime2(7) NULL
    );
    CREATE TABLE publication.AuthorityGrant (
        TargetId uniqueidentifier NOT NULL REFERENCES publication.Target(TargetId),
        SessionId uniqueidentifier NOT NULL,
        Epoch bigint NOT NULL,
        CatalogDigest binary(32) NOT NULL,
        Operation varchar(7) NOT NULL CHECK (Operation IN ('admit', 'restore')),
        AuthorityDigest binary(32) NOT NULL,
        EvidenceDigest binary(32) NOT NULL,
        ValidFrom datetime2(7) NOT NULL,
        ValidUntil datetime2(7) NOT NULL,
        Revoked bit NOT NULL DEFAULT 0,
        PRIMARY KEY (TargetId, SessionId, Epoch, CatalogDigest, Operation),
        CHECK (ValidUntil > ValidFrom)
    );
    CREATE TABLE publication.Operation (
        TargetId uniqueidentifier NOT NULL REFERENCES publication.Target(TargetId),
        RequestId uniqueidentifier NOT NULL,
        RequestDigest binary(32) NOT NULL,
        ResultJson nvarchar(max) NOT NULL CHECK (ISJSON(ResultJson) = 1),
        PRIMARY KEY (TargetId, RequestId)
    );
    CREATE TABLE publication.Revocation (
        TargetId uniqueidentifier NOT NULL REFERENCES publication.Target(TargetId),
        SessionId uniqueidentifier NOT NULL,
        Epoch bigint NOT NULL,
        CatalogDigest binary(32) NOT NULL,
        Operation varchar(7) NOT NULL CHECK (Operation IN ('admit','restore')),
        PRIMARY KEY (TargetId, SessionId, Epoch, CatalogDigest, Operation)
    );
    CREATE TABLE publication.Receipt (
        TargetId uniqueidentifier NOT NULL REFERENCES publication.Target(TargetId),
        Revision bigint NOT NULL,
        AttemptId uniqueidentifier NOT NULL REFERENCES publication.Attempt(AttemptId),
        CatalogDigest binary(32) NOT NULL,
        Operation varchar(7) NOT NULL,
        TransitionedAt datetime2(7) NOT NULL,
        PRIMARY KEY (TargetId, Revision)
    );
    CREATE TABLE publication.Audit (
        AuditId bigint IDENTITY PRIMARY KEY,
        TargetId uniqueidentifier NOT NULL,
        Kind varchar(24) NOT NULL,
        DetailJson nvarchar(max) NOT NULL CHECK (ISJSON(DetailJson) = 1),
        RecordedAt datetime2(7) NOT NULL DEFAULT SYSUTCDATETIME()
    );
END;
GO
CREATE OR ALTER PROCEDURE publication.ProvisionTarget
    @target_id uniqueidentifier, @target_json nvarchar(max),
    @account_resource_id nvarchar(512), @blob_endpoint nvarchar(512),
    @container_name nvarchar(63), @retain_until datetime2(7)
AS
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    IF @target_id IS NULL OR ISNULL(ISJSON(@target_json), 0) <> 1
       OR @retain_until IS NULL OR @retain_until <= SYSUTCDATETIME()
       OR ISNULL(@account_resource_id, N'') = N'' OR ISNULL(@blob_endpoint, N'') = N''
       OR ISNULL(@container_name, N'') = N'' OR LEFT(LTRIM(@target_json), 1) <> N'{'
        THROW 51001, 'publication_target_invalid', 1;
    IF (SELECT COUNT(*) FROM OPENJSON(@target_json)) <> 6
       OR EXISTS (
           SELECT 1 FROM OPENJSON(@target_json)
           WHERE [key] NOT IN ('tenant_id','subscription_id','connection_id',
                              'workspace_id','item_id','definition_fingerprint')
              OR [type] <> 1 OR [value] = N''
       )
       OR (SELECT COUNT(DISTINCT [key]) FROM OPENJSON(@target_json)) <> 6
        THROW 51001, 'publication_target_invalid', 1;
    -- Create-only: no quiet target/backend/retention rebinding.
    INSERT publication.Target (
        TargetId, TargetJson, AccountResourceId, BlobEndpoint, ContainerName, RequiredRetainUntil
    ) VALUES (
        @target_id, @target_json, @account_resource_id, @blob_endpoint, @container_name, @retain_until
    );
END;
GO
CREATE OR ALTER PROCEDURE publication.Acquire
    @target_id uniqueidentifier, @owner_id uniqueidentifier,
    @expected_revision bigint, @lease_seconds int
AS
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    IF @lease_seconds IS NULL OR @lease_seconds NOT BETWEEN 1 AND 300
       OR @owner_id IS NULL OR @expected_revision IS NULL OR @expected_revision < 0
        THROW 51002, 'publication_lease_invalid', 1;
    BEGIN TRY
        BEGIN TRANSACTION;
        DECLARE @revision bigint;
        SELECT @revision = Revision FROM publication.Target WITH (UPDLOCK, HOLDLOCK)
            WHERE TargetId = @target_id;
        IF @revision IS NULL OR @revision <> @expected_revision
            THROW 51003, 'publication_revision_conflict', 1;
        UPDATE publication.Target
            SET OwnerId = @owner_id, SessionId = NEWID(), Epoch = Epoch + 1,
                Revision = Revision + 1, SessionDeadline = DATEADD(second, @lease_seconds, SYSUTCDATETIME())
            WHERE TargetId = @target_id;
        DECLARE @result nvarchar(max) = (
            SELECT TargetId AS target_id, OwnerId AS owner_id, SessionId AS session_id,
                   Epoch AS epoch, Revision AS revision, SessionDeadline AS session_deadline,
                   ActiveAttempt AS active_attempt,
                   LOWER(CONVERT(varchar(64), ActiveDigest, 2)) AS active_digest
            FROM publication.Target WHERE TargetId = @target_id
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES
        );
        INSERT publication.Audit (TargetId, Kind, DetailJson)
            VALUES (@target_id, 'acquire', @result);
        COMMIT;
        SELECT @result AS result_json;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        THROW;
    END CATCH;
END;
GO
CREATE OR ALTER PROCEDURE publication.SealAttempt
    @target_id uniqueidentifier, @attempt_id uniqueidentifier,
    @catalog_json nvarchar(max), @catalog_digest varbinary(max),
    @inventory_json nvarchar(max), @evidence_json nvarchar(max)
AS
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    IF @catalog_digest IS NULL OR DATALENGTH(@catalog_digest) <> 32
       OR ISNULL(ISJSON(@catalog_json), 0) <> 1
       OR ISNULL(ISJSON(@inventory_json), 0) <> 1 OR ISNULL(ISJSON(@evidence_json), 0) <> 1
       OR LEFT(LTRIM(@inventory_json), 1) <> N'['
       OR HASHBYTES('SHA2_256', CONVERT(varchar(max),
           @catalog_json COLLATE Latin1_General_100_BIN2_UTF8)) <> @catalog_digest
        THROW 51008, 'publication_seal_invalid', 1;
    IF (SELECT COUNT(*) FROM OPENJSON(@catalog_json)) <> 4
       OR (SELECT COUNT(DISTINCT [key]) FROM OPENJSON(@catalog_json)) <> 4
       OR EXISTS (
           SELECT 1 FROM OPENJSON(@catalog_json)
           WHERE ([key] IN ('protocol','attempt_id') AND [type] <> 1)
              OR ([key] IN ('candidate','products') AND [type] <> 5)
              OR [key] NOT IN ('protocol','attempt_id','candidate','products')
       )
       OR (SELECT COUNT(*) FROM OPENJSON(@evidence_json)) <> 9
       OR (SELECT COUNT(DISTINCT [key]) FROM OPENJSON(@evidence_json)) <> 9
       OR EXISTS (
           SELECT 1 FROM OPENJSON(@evidence_json)
           WHERE ([key] IN ('versioning_enabled','append_writes','append_blocks') AND [type] <> 3)
              OR ([key] IN ('account_resource_id','endpoint','container','policy_state','effective_until') AND [type] <> 1)
              OR ([key] = 'provider_readback' AND [type] <> 5)
              OR [key] NOT IN ('account_resource_id','endpoint','container','policy_state',
                              'effective_until','versioning_enabled','append_writes','append_blocks','provider_readback')
       ) THROW 51008, 'publication_seal_shape', 1;
    IF NOT EXISTS (SELECT 1 FROM OPENJSON(@evidence_json, '$.provider_readback'))
        THROW 51008, 'publication_provider_readback_missing', 1;
    BEGIN TRY
        BEGIN TRANSACTION;
        DECLARE @account nvarchar(512), @endpoint nvarchar(512), @container nvarchar(63),
                @required datetime2(7), @candidate nvarchar(max), @sealed binary(32),
                @until datetime2(7) = CONVERT(datetime2(7), SWITCHOFFSET(
                    TRY_CONVERT(datetimeoffset(7), JSON_VALUE(@evidence_json, '$.effective_until'), 127),
                    '+00:00'));
        SELECT @account = AccountResourceId, @endpoint = BlobEndpoint,
               @container = ContainerName, @required = RequiredRetainUntil
            FROM publication.Target WITH (UPDLOCK, HOLDLOCK) WHERE TargetId = @target_id;
        SELECT @candidate = CandidateJson, @sealed = CatalogDigest
            FROM publication.Attempt WITH (UPDLOCK, HOLDLOCK)
            WHERE TargetId = @target_id AND AttemptId = @attempt_id;
        IF @candidate IS NULL OR @account IS NULL OR @until IS NULL
           OR @until < @required OR @until <= SYSUTCDATETIME()
           OR ISNULL(JSON_VALUE(@evidence_json, '$.account_resource_id'), N'') COLLATE Latin1_General_100_BIN2 <> @account
           OR ISNULL(JSON_VALUE(@evidence_json, '$.endpoint'), N'') COLLATE Latin1_General_100_BIN2 <> @endpoint
           OR ISNULL(JSON_VALUE(@evidence_json, '$.container'), N'') COLLATE Latin1_General_100_BIN2 <> @container
           OR ISNULL(JSON_VALUE(@evidence_json, '$.policy_state'), N'') COLLATE Latin1_General_100_BIN2 <> N'Locked'
           OR DATALENGTH(ISNULL(JSON_VALUE(@evidence_json, '$.policy_state'), N'')) <> DATALENGTH(N'Locked')
           OR DATALENGTH(ISNULL(JSON_VALUE(@evidence_json, '$.account_resource_id'), N'')) <> DATALENGTH(@account)
           OR DATALENGTH(ISNULL(JSON_VALUE(@evidence_json, '$.endpoint'), N'')) <> DATALENGTH(@endpoint)
           OR DATALENGTH(ISNULL(JSON_VALUE(@evidence_json, '$.container'), N'')) <> DATALENGTH(@container)
           OR ISNULL(JSON_VALUE(@evidence_json, '$.versioning_enabled'), N'') <> N'false'
           OR ISNULL(JSON_VALUE(@evidence_json, '$.append_writes'), N'') <> N'false'
           OR ISNULL(JSON_VALUE(@evidence_json, '$.append_blocks'), N'') <> N'false'
           OR (SELECT COUNT(*) FROM OPENJSON(@evidence_json)
               WHERE [key] IN ('versioning_enabled','append_writes','append_blocks') AND [type] = 3) <> 3
           OR ISNULL(JSON_QUERY(@catalog_json, '$.candidate'), N'') COLLATE Latin1_General_100_BIN2 <> @candidate
           OR DATALENGTH(ISNULL(JSON_QUERY(@catalog_json, '$.candidate'), N'')) <> DATALENGTH(@candidate)
           OR ISNULL(JSON_VALUE(@catalog_json, '$.attempt_id'), N'') <> CONVERT(nvarchar(36), @attempt_id)
           OR DATALENGTH(ISNULL(JSON_VALUE(@catalog_json, '$.attempt_id'), N'')) <> 72
           OR ISNULL(JSON_VALUE(@catalog_json, '$.protocol'), N'') COLLATE Latin1_General_100_BIN2 <> N'immutable-attempt/v1'
           OR DATALENGTH(ISNULL(JSON_VALUE(@catalog_json, '$.protocol'), N'')) <> DATALENGTH(N'immutable-attempt/v1')
            THROW 51008, 'publication_seal_binding', 1;
        DECLARE @count int = (SELECT COUNT(*) FROM OPENJSON(@catalog_json, '$.products'));
        IF @count = 0 OR @count <> (SELECT COUNT(*) FROM OPENJSON(@inventory_json))
           OR @count <> (SELECT COUNT(DISTINCT JSON_VALUE([value], '$.logical_name')) FROM OPENJSON(@inventory_json))
           OR @count <> (SELECT COUNT(DISTINCT JSON_VALUE([value], '$.object_name')) FROM OPENJSON(@inventory_json))
           OR @count <> (SELECT COUNT(DISTINCT [key]) FROM OPENJSON(@catalog_json, '$.products'))
            THROW 51008, 'publication_inventory_membership', 1;
        IF EXISTS (
            SELECT 1 FROM OPENJSON(@inventory_json) i
            LEFT JOIN OPENJSON(@catalog_json, '$.products') p
              ON p.[key] = JSON_VALUE(i.[value], '$.logical_name')
            WHERE p.[key] IS NULL OR i.[type] <> 5 OR p.[type] <> 5
               OR (SELECT COUNT(*) FROM OPENJSON(i.[value])) <> 9
               OR (SELECT COUNT(DISTINCT [key]) FROM OPENJSON(i.[value])) <> 9
               OR EXISTS (
                   SELECT 1 FROM OPENJSON(i.[value])
                   WHERE [key] NOT IN ('logical_name','account_resource_id','endpoint','container',
                                       'object_name','etag','length','content_digest','version_id')
                      OR ([key] = 'version_id' AND [type] <> 0)
                      OR ([key] = 'length' AND [type] <> 2)
                      OR ([key] NOT IN ('version_id','length') AND [type] <> 1)
               )
               OR ISNULL(JSON_VALUE(i.[value], '$.account_resource_id'), N'') COLLATE Latin1_General_100_BIN2 <> @account
               OR ISNULL(JSON_VALUE(i.[value], '$.endpoint'), N'') COLLATE Latin1_General_100_BIN2 <> @endpoint
               OR ISNULL(JSON_VALUE(i.[value], '$.container'), N'') COLLATE Latin1_General_100_BIN2 <> @container
               OR DATALENGTH(ISNULL(JSON_VALUE(i.[value], '$.account_resource_id'), N'')) <> DATALENGTH(@account)
               OR DATALENGTH(ISNULL(JSON_VALUE(i.[value], '$.endpoint'), N'')) <> DATALENGTH(@endpoint)
               OR DATALENGTH(ISNULL(JSON_VALUE(i.[value], '$.container'), N'')) <> DATALENGTH(@container)
               OR ISNULL(JSON_VALUE(i.[value], '$.object_name'), N'') = N''
               OR ISNULL(JSON_VALUE(i.[value], '$.etag'), N'') = N''
               OR ISNULL(JSON_VALUE(i.[value], '$.content_digest'), N'') <>
                  ISNULL(JSON_VALUE(p.[value], '$.content_digest'), N'!')
               OR ISNULL(JSON_VALUE(i.[value], '$.object_name'), N'') <>
                  ISNULL(JSON_VALUE(p.[value], '$.artifact.object_name'), N'!')
               OR ISNULL(JSON_VALUE(i.[value], '$.etag'), N'') <>
                  ISNULL(JSON_VALUE(p.[value], '$.artifact.etag'), N'!')
               OR ISNULL(TRY_CONVERT(bigint, JSON_VALUE(i.[value], '$.length')), -1) < 0
               OR ISNULL(TRY_CONVERT(bigint, JSON_VALUE(i.[value], '$.length')), -1) <>
                  ISNULL(TRY_CONVERT(bigint, JSON_VALUE(p.[value], '$.artifact.length')), -2)
               OR JSON_VALUE(i.[value], '$.version_id') IS NOT NULL
               OR LEN(ISNULL(JSON_VALUE(i.[value], '$.content_digest'), N'')) <> 64
               OR JSON_VALUE(i.[value], '$.content_digest') COLLATE Latin1_General_100_BIN2 LIKE '%[^0-9a-f]%'
               OR (SELECT COUNT(*) FROM OPENJSON(p.[value], '$.artifact')) <> 8
               OR (SELECT COUNT(DISTINCT [key]) FROM OPENJSON(p.[value], '$.artifact')) <> 8
               OR EXISTS (
                   SELECT 1 FROM OPENJSON(p.[value], '$.artifact') a
                   FULL JOIN (
                       SELECT [key], [value], [type] FROM OPENJSON(i.[value]) WHERE [key] <> 'logical_name'
                   ) b ON a.[key] = b.[key]
                   WHERE a.[key] IS NULL OR b.[key] IS NULL OR a.[type] <> b.[type]
                      OR ISNULL(a.[value], N'') COLLATE Latin1_General_100_BIN2 <> ISNULL(b.[value], N'')
                      OR DATALENGTH(ISNULL(a.[value], N'')) <> DATALENGTH(ISNULL(b.[value], N''))
               )
        ) THROW 51008, 'publication_inventory_identity', 1;
        IF @sealed IS NOT NULL
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM publication.Attempt WHERE AttemptId = @attempt_id
                AND CatalogDigest = @catalog_digest AND CatalogJson = @catalog_json
                AND InventoryJson = @inventory_json AND EvidenceJson = @evidence_json
                AND DATALENGTH(CatalogJson) = DATALENGTH(@catalog_json)
                AND DATALENGTH(InventoryJson) = DATALENGTH(@inventory_json)
                AND DATALENGTH(EvidenceJson) = DATALENGTH(@evidence_json)
            ) THROW 51008, 'publication_seal_immutable', 1;
        END
        ELSE
        BEGIN
            UPDATE publication.Attempt
                SET CatalogJson = @catalog_json, CatalogDigest = @catalog_digest,
                    InventoryJson = @inventory_json,
                    InventoryDigest = HASHBYTES('SHA2_256', CONVERT(varchar(max),
                        @inventory_json COLLATE Latin1_General_100_BIN2_UTF8)),
                    EvidenceJson = @evidence_json,
                    EvidenceDigest = HASHBYTES('SHA2_256', CONVERT(varchar(max),
                        @evidence_json COLLATE Latin1_General_100_BIN2_UTF8)),
                    VerifierPrincipal = USER_NAME(), RetainUntil = @until, SealedAt = SYSUTCDATETIME()
                WHERE AttemptId = @attempt_id;
            INSERT publication.Audit (TargetId, Kind, DetailJson)
                VALUES (@target_id, 'seal', (
                    SELECT @attempt_id AS attempt_id, @catalog_digest AS catalog_digest,
                           USER_NAME() AS verifier_principal, @until AS effective_until
                    FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
                ));
        END;
        COMMIT;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        THROW;
    END CATCH;
END;
GO
CREATE OR ALTER PROCEDURE publication.CommitAttempt
    @target_id uniqueidentifier, @owner_id uniqueidentifier,
    @session_id uniqueidentifier, @epoch bigint, @expected_revision bigint,
    @attempt_id uniqueidentifier, @catalog_digest varbinary(max),
    @operation varchar(32), @authority_digest varbinary(max), @request_id uniqueidentifier,
    @recover_only bit = 0
AS
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    IF @operation IS NULL OR @operation COLLATE Latin1_General_100_BIN2 NOT IN ('admit','restore')
       OR @request_id IS NULL OR @authority_digest IS NULL OR @catalog_digest IS NULL
       OR DATALENGTH(@operation) NOT IN (5,7)
       OR DATALENGTH(@authority_digest) <> 32 OR DATALENGTH(@catalog_digest) <> 32
       OR @owner_id IS NULL OR @session_id IS NULL OR @epoch IS NULL OR @epoch < 1
       OR @expected_revision IS NULL OR @expected_revision < 0 OR @recover_only IS NULL
       OR @attempt_id IS NULL
        THROW 51009, 'publication_operation_invalid', 1;
    DECLARE @request_json nvarchar(max) = (
        SELECT @owner_id AS owner_id, @session_id AS session_id, @epoch AS epoch,
               @expected_revision AS revision, @attempt_id AS attempt_id,
               @catalog_digest AS digest, @operation AS operation, @authority_digest AS authority
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
    );
    DECLARE @request_digest binary(32) = HASHBYTES('SHA2_256', @request_json);
    BEGIN TRY
        BEGIN TRANSACTION;
        DECLARE @revision bigint, @result nvarchar(max), @prior binary(32);
        SELECT @revision = Revision FROM publication.Target WITH (UPDLOCK, HOLDLOCK)
            WHERE TargetId = @target_id;
        IF @revision IS NULL THROW 51001, 'publication_target_invalid', 1;
        SELECT @prior = RequestDigest, @result = ResultJson FROM publication.Operation
            WHERE TargetId = @target_id AND RequestId = @request_id;
        IF @prior IS NOT NULL
        BEGIN
            IF @prior <> @request_digest THROW 51010, 'publication_request_conflict', 1;
            COMMIT;
            IF @recover_only = 1
                SELECT N'{"found":true,"outcome":' + @result + N'}' AS result_json;
            ELSE
                SELECT @result AS result_json;
            RETURN;
        END;
        IF @recover_only = 1
        BEGIN
            -- Read-only lookup may not fall through into a fresh commit.
            COMMIT;
            SELECT N'{"found":false}' AS result_json;
            RETURN;
        END;
        -- This guarded DB state transition is the authority linearization point.
        -- No promise about acknowledgement/durable completion before expiry.
        UPDATE t SET ActiveAttempt = @attempt_id, ActiveDigest = @catalog_digest,
                     Revision = Revision + 1
        FROM publication.Target t
        WHERE t.TargetId = @target_id AND t.OwnerId = @owner_id AND t.SessionId = @session_id
          AND t.Epoch = @epoch AND t.Revision = @expected_revision
          AND t.SessionDeadline > SYSUTCDATETIME()
          AND EXISTS (
              SELECT 1 FROM publication.Attempt a
              WHERE a.TargetId = @target_id AND a.AttemptId = @attempt_id
                AND a.CatalogDigest = @catalog_digest AND a.SealedAt IS NOT NULL
                AND a.RetainUntil >= t.RequiredRetainUntil AND a.RetainUntil > SYSUTCDATETIME()
                AND (@operation = 'restore' OR
                     (a.OwnerId = @owner_id AND a.SessionId = @session_id AND a.Epoch = @epoch))
          )
          AND EXISTS (
              SELECT 1 FROM publication.AuthorityGrant g
              WHERE g.TargetId = @target_id AND g.SessionId = @session_id AND g.Epoch = @epoch
                AND g.CatalogDigest = @catalog_digest AND g.Operation = @operation
                AND g.AuthorityDigest = @authority_digest AND g.Revoked = 0
                AND g.ValidFrom <= SYSUTCDATETIME() AND g.ValidUntil > SYSUTCDATETIME()
          );
        IF @@ROWCOUNT <> 1 THROW 51011, 'publication_transition_denied', 1;
        INSERT publication.Receipt VALUES (
            @target_id, @expected_revision + 1, @attempt_id, @catalog_digest,
            @operation, SYSUTCDATETIME()
        );
        SET @result = (
            SELECT @target_id AS target_id, @owner_id AS owner_id, @session_id AS session_id,
                   @epoch AS epoch, @expected_revision + 1 AS revision,
                   @attempt_id AS active_attempt,
                   LOWER(CONVERT(varchar(64), @catalog_digest, 2)) AS active_digest
            FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
        );
        INSERT publication.Operation VALUES (@target_id, @request_id, @request_digest, @result);
        INSERT publication.Audit (TargetId, Kind, DetailJson)
            VALUES (@target_id, @operation, @result);
        COMMIT;
        SELECT @result AS result_json;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        THROW;
    END CATCH;
END;
GO
CREATE OR ALTER PROCEDURE publication.RecoverOutcome
    @target_id uniqueidentifier, @owner_id uniqueidentifier,
    @session_id uniqueidentifier, @epoch bigint, @expected_revision bigint,
    @attempt_id uniqueidentifier, @catalog_digest varbinary(max),
    @operation varchar(32), @authority_digest varbinary(max), @request_id uniqueidentifier
AS
BEGIN
    SET NOCOUNT ON;
    -- One canonical request digest/lookup implementation, no independently
    -- drifting "latest" lookup and no caller-selectable mutation route here.
    EXEC publication.CommitAttempt
        @target_id=@target_id,@owner_id=@owner_id,@session_id=@session_id,@epoch=@epoch,
        @expected_revision=@expected_revision,@attempt_id=@attempt_id,@catalog_digest=@catalog_digest,
        @operation=@operation,@authority_digest=@authority_digest,@request_id=@request_id,
        @recover_only=1;
END;
GO
CREATE OR ALTER PROCEDURE publication.ReadControl @target_id uniqueidentifier
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM publication.Target WHERE TargetId = @target_id)
        THROW 51001, 'publication_target_invalid', 1;
    SELECT (
        SELECT TargetId AS target_id, OwnerId AS owner_id, SessionId AS session_id,
               Epoch AS epoch, Revision AS revision, SessionDeadline AS session_deadline,
               ActiveAttempt AS active_attempt,
               LOWER(CONVERT(varchar(64), ActiveDigest, 2)) AS active_digest
        FROM publication.Target WHERE TargetId = @target_id
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER, INCLUDE_NULL_VALUES
    ) AS result_json;
END;
GO
CREATE OR ALTER PROCEDURE publication.ReadAttempt
    @target_id uniqueidentifier, @attempt_id uniqueidentifier, @catalog_digest varbinary(max)
AS
BEGIN
    SET NOCOUNT ON;
    IF @catalog_digest IS NULL OR DATALENGTH(@catalog_digest) <> 32
        THROW 51012, 'publication_attempt_unreadable', 1;
    SELECT CatalogJson AS catalog_json, InventoryJson AS inventory_json,
           EvidenceJson AS evidence_json FROM publication.Attempt
        WHERE TargetId = @target_id AND AttemptId = @attempt_id AND CatalogDigest = @catalog_digest
          AND SealedAt IS NOT NULL AND RetainUntil > SYSUTCDATETIME();
    IF @@ROWCOUNT <> 1 THROW 51012, 'publication_attempt_unreadable', 1;
END;
GO
CREATE OR ALTER PROCEDURE publication.BeginAttempt
    @target_id uniqueidentifier, @owner_id uniqueidentifier,
    @session_id uniqueidentifier, @epoch bigint, @candidate_json nvarchar(max),
    @request_id uniqueidentifier
AS
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    IF ISNULL(ISJSON(@candidate_json), 0) <> 1 OR @request_id IS NULL
        THROW 51004, 'publication_candidate_invalid', 1;
    IF (SELECT COUNT(*) FROM OPENJSON(@candidate_json)) <> 8
       OR (SELECT COUNT(DISTINCT [key]) FROM OPENJSON(@candidate_json)) <> 8
       OR EXISTS (
           SELECT 1 FROM OPENJSON(@candidate_json)
           WHERE [key] NOT IN ('generation_id','source_generation','content_hash','staged_manifest_digest',
                               'validation_digest','authorization_digest','attestation_digest','expected_target')
              OR ([key] = 'expected_target' AND [type] <> 5)
              OR ([key] <> 'expected_target' AND ([type] <> 1 OR [value] = N''))
       ) THROW 51004, 'publication_candidate_invalid', 1;
    BEGIN TRY
        BEGIN TRANSACTION;
        DECLARE @target_json nvarchar(max), @attempt_id uniqueidentifier;
        SELECT @target_json = TargetJson FROM publication.Target WITH (UPDLOCK, HOLDLOCK)
            WHERE TargetId = @target_id AND OwnerId = @owner_id AND SessionId = @session_id
              AND Epoch = @epoch AND SessionDeadline > SYSUTCDATETIME();
        IF @target_json IS NULL THROW 51005, 'publication_session_invalid', 1;
        IF ISNULL(JSON_QUERY(@candidate_json, '$.expected_target'), N'') COLLATE Latin1_General_100_BIN2 <> @target_json
           OR DATALENGTH(ISNULL(JSON_QUERY(@candidate_json, '$.expected_target'), N'')) <> DATALENGTH(@target_json)
            THROW 51004, 'publication_candidate_target', 1;
        -- Begin request ID is a server-owned broker operation ID; only broker
        -- procedures can allocate it. No worker path/URL is accepted.
        SET @attempt_id = @request_id;
        IF EXISTS (SELECT 1 FROM publication.Attempt WHERE AttemptId = @attempt_id)
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM publication.Attempt WHERE AttemptId = @attempt_id
                AND TargetId = @target_id AND OwnerId = @owner_id AND SessionId = @session_id
                AND Epoch = @epoch AND CandidateJson = @candidate_json
                AND DATALENGTH(CandidateJson) = DATALENGTH(@candidate_json)
            ) THROW 51006, 'publication_attempt_conflict', 1;
        END
        ELSE
            INSERT publication.Attempt (AttemptId, TargetId, OwnerId, SessionId, Epoch, CandidateJson)
                VALUES (@attempt_id, @target_id, @owner_id, @session_id, @epoch, @candidate_json);
        COMMIT;
        SELECT CONVERT(varchar(36), @attempt_id) AS attempt_id;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        THROW;
    END CATCH;
END;
GO
CREATE OR ALTER PROCEDURE publication.RecordGrant
    @target_id uniqueidentifier, @session_id uniqueidentifier, @epoch bigint,
    @catalog_digest varbinary(max), @operation varchar(32), @authority_digest varbinary(max),
    @evidence_digest varbinary(max), @valid_from datetime2(7), @valid_until datetime2(7)
AS
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    IF @operation IS NULL OR @operation COLLATE Latin1_General_100_BIN2 NOT IN ('admit','restore')
       OR @valid_from IS NULL OR @valid_until IS NULL OR @valid_until <= @valid_from
       OR DATALENGTH(@operation) NOT IN (5,7)
       OR @catalog_digest IS NULL OR DATALENGTH(@catalog_digest) <> 32
       OR @authority_digest IS NULL OR DATALENGTH(@authority_digest) <> 32
       OR @evidence_digest IS NULL OR DATALENGTH(@evidence_digest) <> 32
        THROW 51007, 'publication_grant_invalid', 1;
    BEGIN TRY
        BEGIN TRANSACTION;
        DECLARE @exists uniqueidentifier;
        SELECT @exists = TargetId FROM publication.Target WITH (UPDLOCK, HOLDLOCK)
            WHERE TargetId = @target_id AND SessionId = @session_id AND Epoch = @epoch;
        IF @exists IS NULL THROW 51005, 'publication_session_invalid', 1;
        IF EXISTS (
            SELECT 1 FROM publication.Revocation WHERE TargetId = @target_id
            AND SessionId = @session_id AND Epoch = @epoch
            AND CatalogDigest = @catalog_digest AND Operation = @operation
        ) THROW 51007, 'publication_grant_revoked', 1;
        -- Separate authority principal validates signed review bindings before
        -- invoking this procedure. Broker/verifier roles cannot issue grants.
        INSERT publication.AuthorityGrant VALUES (
            @target_id, @session_id, @epoch, @catalog_digest, @operation,
            @authority_digest, @evidence_digest, @valid_from, @valid_until, 0
        );
        INSERT publication.Audit (TargetId, Kind, DetailJson)
            VALUES (@target_id, 'grant', (
                SELECT @session_id AS session_id, @epoch AS epoch, @operation AS operation,
                       @catalog_digest AS catalog_digest, @authority_digest AS authority_digest,
                       @evidence_digest AS evidence_digest, @valid_from AS valid_from, @valid_until AS valid_until
                FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
            ));
        COMMIT;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        THROW;
    END CATCH;
END;
GO
CREATE OR ALTER PROCEDURE publication.[Revoke]
    @target_id uniqueidentifier, @session_id uniqueidentifier, @epoch bigint,
    @catalog_digest varbinary(max), @operation varchar(32)
AS
BEGIN
    SET NOCOUNT ON; SET XACT_ABORT ON;
    IF @operation IS NULL OR @operation COLLATE Latin1_General_100_BIN2 NOT IN ('admit','restore')
       OR @session_id IS NULL OR @epoch IS NULL OR @catalog_digest IS NULL
       OR DATALENGTH(@operation) NOT IN (5,7) OR DATALENGTH(@catalog_digest) <> 32
        THROW 51007, 'publication_revoke_invalid', 1;
    BEGIN TRY
        BEGIN TRANSACTION;
        DECLARE @exists uniqueidentifier;
        SELECT @exists = TargetId FROM publication.Target WITH (UPDLOCK, HOLDLOCK)
            WHERE TargetId = @target_id;
        IF @exists IS NULL THROW 51001, 'publication_target_invalid', 1;
        IF NOT EXISTS (
            SELECT 1 FROM publication.Revocation WHERE TargetId = @target_id
            AND SessionId = @session_id AND Epoch = @epoch
            AND CatalogDigest = @catalog_digest AND Operation = @operation
        )
            INSERT publication.Revocation VALUES (@target_id,@session_id,@epoch,@catalog_digest,@operation);
        UPDATE publication.AuthorityGrant SET Revoked = 1
            WHERE TargetId = @target_id AND SessionId = @session_id AND Epoch = @epoch
              AND CatalogDigest = @catalog_digest AND Operation = @operation;
        INSERT publication.Audit (TargetId, Kind, DetailJson)
            VALUES (@target_id, 'revoke', (
                SELECT @session_id AS session_id, @epoch AS epoch,
                       @catalog_digest AS catalog_digest, @operation AS operation
                FOR JSON PATH, WITHOUT_ARRAY_WRAPPER
            ));
        COMMIT;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        THROW;
    END CATCH;
END;
GO
