-- Explicit optional broker-composition migration, AFTER schema/permissions.
-- Historical outcome binding must not read expired artifacts.
CREATE OR ALTER PROCEDURE publication.SealOwnedAttempt
    @target_id uniqueidentifier, @owner_id uniqueidentifier,
    @session_id uniqueidentifier, @epoch bigint, @attempt_id uniqueidentifier,
    @catalog_json nvarchar(max), @catalog_digest varbinary(max),
    @inventory_json nvarchar(max), @evidence_json nvarchar(max)
AS
BEGIN
    SET NOCOUNT ON;
    -- Never commit or discard a caller-owned ambient transaction.
    IF @@TRANCOUNT <> 0
    BEGIN
        -- RAISERROR does not honor XACT_ABORT on the caller's transaction.
        RAISERROR ('publication_seal_ambient_transaction', 16, 1);
        RETURN;
    END;
    SET XACT_ABORT ON;
    BEGIN TRY
        BEGIN TRANSACTION;
        IF NOT EXISTS (
            SELECT 1 FROM publication.Target WITH (UPDLOCK, HOLDLOCK)
            WHERE TargetId = @target_id AND OwnerId = @owner_id
              AND SessionId = @session_id AND Epoch = @epoch
              AND SessionDeadline > SYSUTCDATETIME()
        ) THROW 51005, 'publication_session_invalid', 1;
        IF NOT EXISTS (
            SELECT 1 FROM publication.Attempt WITH (UPDLOCK, HOLDLOCK)
            WHERE TargetId = @target_id AND AttemptId = @attempt_id
              AND OwnerId = @owner_id AND SessionId = @session_id AND Epoch = @epoch
        ) THROW 51005, 'publication_attempt_session_invalid', 1;
        EXEC publication.SealAttempt @target_id, @attempt_id, @catalog_json,
            @catalog_digest, @inventory_json, @evidence_json;
        COMMIT;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK;
        THROW;
    END CATCH;
END;
GO
CREATE OR ALTER PROCEDURE publication.ReadReferenceMetadata
    @target_id uniqueidentifier, @attempt_id uniqueidentifier, @catalog_digest varbinary(max)
AS
BEGIN
    SET NOCOUNT ON;
    IF @catalog_digest IS NULL OR DATALENGTH(@catalog_digest) <> 32
        THROW 51012, 'publication_reference_metadata_invalid', 1;
    DECLARE @generation nvarchar(128);
    SELECT @generation = JSON_VALUE(CatalogJson, '$.candidate.generation_id')
        FROM publication.Attempt
        WHERE TargetId = @target_id AND AttemptId = @attempt_id
          AND CatalogDigest = @catalog_digest AND SealedAt IS NOT NULL;
    IF @generation IS NULL THROW 51012, 'publication_reference_metadata_missing', 1;
    SELECT (SELECT @generation AS generation_id FOR JSON PATH, WITHOUT_ARRAY_WRAPPER) AS result_json;
END;
GO
CREATE OR ALTER PROCEDURE publication.ReadReadableReferenceMetadata
    @target_id uniqueidentifier, @attempt_id uniqueidentifier, @catalog_digest varbinary(max)
AS
BEGIN
    SET NOCOUNT ON;
    IF @catalog_digest IS NULL OR DATALENGTH(@catalog_digest) <> 32
        THROW 51012, 'publication_reference_metadata_invalid', 1;
    DECLARE @generation nvarchar(128);
    SELECT @generation = JSON_VALUE(CatalogJson, '$.candidate.generation_id')
        FROM publication.Attempt
        WHERE TargetId = @target_id AND AttemptId = @attempt_id
          AND CatalogDigest = @catalog_digest AND SealedAt IS NOT NULL
          AND RetainUntil > SYSUTCDATETIME();
    IF @generation IS NULL THROW 51012, 'publication_attempt_unreadable', 1;
    SELECT (SELECT @generation AS generation_id FOR JSON PATH, WITHOUT_ARRAY_WRAPPER) AS result_json;
END;
GO
GRANT EXECUTE ON OBJECT::publication.ReadReferenceMetadata TO publication_broker;
GRANT EXECUTE ON OBJECT::publication.ReadReferenceMetadata TO publication_reader;
GRANT EXECUTE ON OBJECT::publication.ReadReadableReferenceMetadata TO publication_broker;
GRANT EXECUTE ON OBJECT::publication.ReadReadableReferenceMetadata TO publication_reader;
GRANT EXECUTE ON OBJECT::publication.SealOwnedAttempt TO publication_verifier;
GO
