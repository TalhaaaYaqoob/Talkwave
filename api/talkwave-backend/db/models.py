import secrets
from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship

from ..enums import (
    AuthType,
    ExecutionStatus,
    HttpMethod,
    IntegrationAction,
    ToolType,
    WorkflowRunMode,
    WorkflowRunState,
    WorkflowStatus,
)

Base = declarative_base()


# TODO: remove workflow_defintion after migration, remove nullable workflow_defintion_id from Workflow and Workflowrun


# Association table for many-to-many relationship between users and organizations
organization_users_association = Table(
    "organization_users",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column(
        "organization_id", Integer, ForeignKey("organizations.id"), primary_key=True
    ),
)


class UserModel(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    workflows = relationship("WorkflowModel", back_populates="user")
    selected_organization_id = Column(
        Integer, ForeignKey("organizations.id"), nullable=True
    )
    selected_organization = relationship("OrganizationModel", back_populates="users")
    organizations = relationship(
        "OrganizationModel",
        secondary=organization_users_association,
        back_populates="users",
    )
    is_superuser = Column(Boolean, default=False)


class UserConfigurationModel(Base):
    __tablename__ = "user_configurations"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    configuration = Column(JSON, nullable=False, default=dict)
    last_validated_at = Column(DateTime(timezone=True), nullable=True)


# New Organization model
class OrganizationModel(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    provider_id = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # Quota fields
    quota_type = Column(
        Enum("monthly", "annual", name="quota_type"),
        nullable=False,
        default="monthly",
        server_default=text("'monthly'::quota_type"),
    )
    quota_dograh_tokens = Column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    quota_reset_day = Column(
        Integer, nullable=False, default=1, server_default=text("1")
    )  # 1-28, only for monthly
    quota_start_date = Column(DateTime(timezone=True), nullable=True)  # Only for annual
    quota_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    price_per_second_usd = Column(Float, nullable=True)

    # Relationships
    users = relationship(
        "UserModel",
        secondary=organization_users_association,
        back_populates="organizations",
    )
    integrations = relationship("IntegrationModel", back_populates="organization")
    usage_cycles = relationship(
        "OrganizationUsageCycleModel", back_populates="organization"
    )
    configurations = relationship(
        "OrganizationConfigurationModel", back_populates="organization"
    )
    api_keys = relationship("APIKeyModel", back_populates="organization")


class APIKeyModel(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String, nullable=False)
    key_hash = Column(String, nullable=False, unique=True, index=True)
    key_prefix = Column(String, nullable=False)  # Store first 8 chars for display
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    archived_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization = relationship("OrganizationModel", back_populates="api_keys")
    created_by_user = relationship("UserModel")

    # Indexes for performance
    __table_args__ = (
        Index("ix_api_keys_organization_id", "organization_id"),
        Index("ix_api_keys_key_hash", "key_hash"),
        Index("ix_api_keys_active", "is_active"),
    )


class OrganizationConfigurationModel(Base):
    __tablename__ = "organization_configurations"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    key = Column(String, nullable=False)
    value = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    organization = relationship("OrganizationModel", back_populates="configurations")

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint("organization_id", "key", name="_organization_key_uc"),
        Index("ix_organization_configurations_organization_id", "organization_id"),
    )


class IntegrationModel(Base):
    __tablename__ = "integrations"

    id = Column(Integer, primary_key=True, index=True)
    integration_id = Column(String, nullable=False, index=True)  # Nango Connection ID
    organisation_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    provider = Column(String, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    connection_details = Column(JSON, nullable=False, default=dict)
    action = Column(String, nullable=False, default=IntegrationAction.ALL_CALLS.value)

    # Relationships
    organization = relationship("OrganizationModel", back_populates="integrations")


class WorkflowDefinitionModel(Base):
    __tablename__ = "workflow_definitions"
    id = Column(Integer, primary_key=True, index=True)
    workflow_hash = Column(String, nullable=False)
    workflow_json = Column(JSON, nullable=False, default=dict)
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=True)
    is_current = Column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # Table constraints and indexes
    __table_args__ = (
        UniqueConstraint(
            "workflow_hash", "workflow_id", name="uq_workflow_hash_workflow_id"
        ),
        Index("ix_workflow_hash_workflow_id", "workflow_hash", "workflow_id"),
    )

    # Relationships
    workflow = relationship(
        "WorkflowModel",
        back_populates="definitions",
        foreign_keys=[workflow_id],
    )
    workflow_runs = relationship("WorkflowRunModel", back_populates="definition")


class WorkflowModel(Base):
    __tablename__ = "workflows"
    
    # Table indexes for multi-tenant query optimization
    __table_args__ = (
        # Primary index for organization-based queries (most common pattern)
        Index("ix_workflows_organization_id", "organization_id"),
        # Composite index for filtered queries by organization and status
        Index("ix_workflows_org_status", "organization_id", "status"),
        # Composite index for sorting by created_at within organization
        Index("ix_workflows_org_created", "organization_id", "created_at"),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    # Opaque, unguessable public identifier used in externally-exposed URLs
    # (e.g. the Twilio inbound webhook). The sequential integer ``id`` must NOT
    # appear in semi-public URLs because it is enumerable and leaks how many
    # workflows exist platform-wide. ``public_id`` is a high-entropy token.
    public_id = Column(
        String, unique=True, index=True, nullable=True,
        default=lambda: secrets.token_urlsafe(16),
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    user = relationship("UserModel", back_populates="workflows")
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    organization = relationship("OrganizationModel")
    name = Column(String, index=True, nullable=False)
    status = Column(
        Enum(*[status.value for status in WorkflowStatus], name="workflow_status"),
        nullable=False,
        default=WorkflowStatus.ACTIVE.value,
        server_default=text("'active'::workflow_status"),
        index=True,
    )
    workflow_definition = Column(JSON, nullable=False, default=dict)
    template_context_variables = Column(JSON, nullable=False, default=dict)
    call_disposition_codes = Column(JSON, nullable=False, default=dict)
    workflow_configurations = Column(
        JSON, nullable=False, default=dict, server_default=text("'{}'::json")
    )
    runs = relationship(
        "WorkflowRunModel",
        back_populates="workflow",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    # All versions / historical definitions of this workflow
    definitions = relationship(
        "WorkflowDefinitionModel",
        back_populates="workflow",
        foreign_keys="WorkflowDefinitionModel.workflow_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # Relationship to fetch the current (is_current=True) definition
    current_definition = relationship(
        "WorkflowDefinitionModel",
        primaryjoin=lambda: and_(
            WorkflowDefinitionModel.workflow_id == WorkflowModel.id,
            WorkflowDefinitionModel.is_current.is_(True),
        ),
        uselist=False,
        viewonly=True,
    )

    @property
    def current_definition_id(self):
        """Return ID of the current workflow definition (helper for backwards-compat)."""
        current_def = self.__dict__.get("current_definition")
        if current_def is not None:
            return current_def.id

        # If relationship is not loaded, we cannot safely access definitions without
        # risking an implicit lazy load on a detached instance. Return ``None`` in
        # that scenario so callers can handle the absence explicitly.
        return None

    @property
    def workflow_definition_with_fallback(self):
        """
        Get workflow definition with fallback to legacy workflow_definition field.

        Returns:
            dict: The workflow definition JSON
        """
        # Access the relationship only if it has ALREADY been eagerly loaded on this
        # instance to avoid triggering an implicit lazy load once the SQLAlchemy
        # Session has been closed (which would raise a DetachedInstanceError).

        # ``__dict__`` will contain "current_definition" **only** when the attribute
        # has been populated (e.g. via `selectinload` or an explicit access while
        # the session was still open). Using ``__dict__.get`` guarantees that we
        # do not accidentally issue a lazy load query on a detached instance.

        current_definition = self.__dict__.get("current_definition")

        if current_definition is not None:
            return current_definition.workflow_json

        # Fallback for backwards-compatibility when the relationship is not (yet)
        # loaded. In this case we fall back to the legacy ``workflow_definition``
        # column that always contains the most recent definition JSON.
        logger.warning(
            f"Workflow {self.id} has no loaded current definition, using workflow_definition as fallback",
        )
        return self.workflow_definition


class WorkflowTemplates(Base):
    __tablename__ = "workflow_templates"
    id = Column(Integer, primary_key=True, index=True)
    template_name = Column(String, nullable=False, index=True)
    template_description = Column(String, nullable=False, index=True)
    template_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class WorkflowRunModel(Base):
    __tablename__ = "workflow_runs"
    
    # Table indexes for query optimization
    __table_args__ = (
        # Primary index for workflow-based queries (most common pattern)
        Index("ix_workflow_runs_workflow_id", "workflow_id"),
        # Composite index for paginated runs by workflow sorted by created_at
        Index("ix_workflow_runs_workflow_created", "workflow_id", "created_at"),
        # Index for filtering by completion status
        Index("ix_workflow_runs_completed", "is_completed"),
        # Composite index for campaign runs
        Index("ix_workflow_runs_campaign_id", "campaign_id"),
        # Index for state-based queries
        Index("ix_workflow_runs_state", "state"),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    workflow = relationship("WorkflowModel", back_populates="runs")
    definition_id = Column(
        Integer, ForeignKey("workflow_definitions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    definition = relationship("WorkflowDefinitionModel", back_populates="workflow_runs")
    mode = Column(
        Enum(*[mode.value for mode in WorkflowRunMode], name="workflow_run_mode"),
        nullable=False,
    )
    state = Column(
        Enum(*[state.value for state in WorkflowRunState], name="workflow_run_state"),
        nullable=False,
        default=WorkflowRunState.INITIALIZED.value,
        server_default=text("'initialized'::workflow_run_state"),
    )
    is_completed = Column(Boolean, default=False)
    recording_url = Column(String, nullable=True)
    transcript_url = Column(String, nullable=True)
    # Store storage backend as string enum (s3, supabase)
    storage_backend = Column(
        Enum("s3", "supabase", name="storage_backend"),
        nullable=False,
        default="s3",
        server_default=text("'s3'::storage_backend"),
    )
    usage_info = Column(JSON, nullable=False, default=dict)
    cost_info = Column(JSON, nullable=False, default=dict)
    initial_context = Column(JSON, nullable=False, default=dict)
    gathered_context = Column(JSON, nullable=False, default=dict)
    logs = Column(JSON, nullable=False, default=dict, server_default=text("'{}'::json"))
    annotations = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=True)
    campaign = relationship("CampaignModel")
    queued_run_id = Column(Integer, ForeignKey("queued_runs.id"), nullable=True, index=True)
    queued_run = relationship("QueuedRunModel", foreign_keys=[queued_run_id])


# LoopTalk Testing Models
class LoopTalkTestSession(Base):
    __tablename__ = "looptalk_test_sessions"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)
    status = Column(
        Enum("pending", "running", "completed", "failed", name="test_session_status"),
        nullable=False,
        default="pending",
    )

    # Workflow configuration
    actor_workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    adversary_workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)

    # Load testing configuration
    load_test_group_id = Column(String, nullable=True, index=True)
    test_index = Column(Integer, nullable=True)

    # Test metadata
    config = Column(JSON, nullable=False, default=dict)
    results = Column(JSON, nullable=False, default=dict)
    error = Column(String, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization = relationship("OrganizationModel")
    actor_workflow = relationship("WorkflowModel", foreign_keys=[actor_workflow_id])
    adversary_workflow = relationship(
        "WorkflowModel", foreign_keys=[adversary_workflow_id]
    )
    conversations = relationship("LoopTalkConversation", back_populates="test_session")

    # Indexes for performance
    __table_args__ = (
        Index("ix_looptalk_test_sessions_org_id", "organization_id"),
        Index("ix_looptalk_test_sessions_group_id", "load_test_group_id"),
        Index("ix_looptalk_test_sessions_status", "status"),
    )


class LoopTalkConversation(Base):
    __tablename__ = "looptalk_conversations"

    id = Column(Integer, primary_key=True, index=True)
    test_session_id = Column(
        Integer, ForeignKey("looptalk_test_sessions.id"), nullable=False
    )

    # Conversation metadata
    duration_seconds = Column(Integer, nullable=True)
    # Note: Turn tracking is handled by Langfuse, not stored here

    # Audio recording URLs
    actor_recording_url = Column(String, nullable=True)
    adversary_recording_url = Column(String, nullable=True)
    combined_recording_url = Column(String, nullable=True)

    # Transcripts (if needed for quick access)
    transcript = Column(JSON, nullable=False, default=dict)

    # Metrics
    metrics = Column(JSON, nullable=False, default=dict)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    ended_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    test_session = relationship("LoopTalkTestSession", back_populates="conversations")

    # Indexes
    __table_args__ = (Index("ix_looptalk_conversations_session_id", "test_session_id"),)


class OrganizationUsageCycleModel(Base):
    """
    This model is used to track the usage of Dograh tokens for an organization for a given usage
    cycle.
    """

    __tablename__ = "organization_usage_cycles"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end = Column(DateTime(timezone=True), nullable=False)
    quota_dograh_tokens = Column(Integer, nullable=False)
    used_dograh_tokens = Column(Float, nullable=False, default=0)
    total_duration_seconds = Column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # New USD tracking fields
    used_amount_usd = Column(Float, nullable=True, default=0)
    quota_amount_usd = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    organization = relationship("OrganizationModel", back_populates="usage_cycles")

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "period_start", "period_end", name="unique_org_period"
        ),
        Index("idx_usage_cycles_org_period", "organization_id", "period_end"),
    )


class CampaignModel(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Source configuration
    source_type = Column(String, nullable=False, default="google-sheet")
    source_id = Column(String, nullable=False)  # Sheet URL

    # State management
    state = Column(
        Enum(
            "created",
            "scheduled",
            "syncing",
            "running",
            "paused",
            "completed",
            "failed",
            name="campaign_state",
        ),
        nullable=False,
        default="created",
    )

    # Scheduling
    scheduled_start_at = Column(DateTime(timezone=True), nullable=True)
    calling_window_start = Column(String, nullable=True)  # HH:MM 24h format e.g. "09:00"
    calling_window_end = Column(String, nullable=True)  # HH:MM 24h format e.g. "17:00"
    calling_window_timezone = Column(String, nullable=True, default="UTC")

    # Progress tracking
    total_rows = Column(Integer, nullable=True)
    processed_rows = Column(Integer, nullable=False, default=0)
    failed_rows = Column(Integer, nullable=False, default=0)

    # Rate limiting and sync configuration
    rate_limit_per_second = Column(Integer, nullable=False, default=1)
    max_retries = Column(Integer, nullable=False, default=0)
    source_sync_status = Column(String, nullable=False, default="pending")
    source_last_synced_at = Column(DateTime(timezone=True), nullable=True)
    source_sync_error = Column(String, nullable=True)

    # Retry configuration for call failures
    retry_config = Column(
        JSON,
        nullable=False,
        default={
            "enabled": True,
            "max_retries": 2,
            "retry_delay_seconds": 120,
            "retry_on_busy": True,
            "retry_on_no_answer": True,
            "retry_on_voicemail": True,
        },
        server_default=text(
            '\'{"enabled": true, "max_retries": 2, "retry_on_busy": true, "retry_on_no_answer": true, "retry_on_voicemail": true, "retry_delay_seconds": 120}\'::jsonb'
        ),
    )

    # Orchestrator tracking fields
    last_batch_scheduled_at = Column(DateTime(timezone=True), nullable=True)
    last_activity_at = Column(DateTime(timezone=True), nullable=True)
    orchestrator_metadata = Column(
        JSON, nullable=False, default=dict, server_default=text("'{}'::json")
    )

    # Compliance configuration
    compliance_region = Column(
        Enum("us", "gb", "both", name="campaign_compliance_region"),
        nullable=False,
        default="us",
        server_default=text("'us'::campaign_compliance_region"),
    )
    ai_disclosure_enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    ai_disclosure_text = Column(String, nullable=True)
    consent_required = Column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    dnc_scrub_enabled = Column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    organization = relationship("OrganizationModel")
    workflow = relationship("WorkflowModel")
    created_by_user = relationship("UserModel")

    # Indexes
    __table_args__ = (
        Index("ix_campaigns_org_id", "organization_id"),
        Index("ix_campaigns_state", "state"),
        Index("ix_campaigns_workflow_id", "workflow_id"),
        # Index for efficient querying of active campaigns
        Index(
            "idx_campaigns_active_status",
            "state",
            postgresql_where=text("state IN ('scheduled', 'syncing', 'running', 'paused')"),
        ),
    )


class QueuedRunModel(Base):
    __tablename__ = "queued_runs"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(
        Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    source_uuid = Column(String, nullable=False)
    context_variables = Column(JSON, nullable=False, default=dict)
    state = Column(
        Enum("queued", "processed", "failed", name="queued_run_state"),
        nullable=False,
        default="queued",
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    processed_at = Column(DateTime(timezone=True), nullable=True)

    # New retry-related fields
    retry_count = Column(Integer, default=0, nullable=False, server_default=text("0"))
    parent_queued_run_id = Column(Integer, ForeignKey("queued_runs.id"), nullable=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    retry_reason = Column(String, nullable=True)  # 'busy', 'no_answer', 'voicemail'

    # Relationships
    campaign = relationship("CampaignModel")
    parent_queued_run = relationship("QueuedRunModel", remote_side=[id])

    # Indexes
    __table_args__ = (
        Index("idx_queued_runs_campaign_state", "campaign_id", "state"),
        Index("idx_queued_runs_created", "created_at"),
        Index("idx_queued_runs_source_uuid", "source_uuid"),
        Index(
            "idx_queued_runs_scheduled", "scheduled_for"
        ),  # New index for scheduled retries
        # Optimized index for checking queued runs efficiently
        Index(
            "idx_queued_runs_campaign_state_optimized",
            "campaign_id",
            "state",
            postgresql_where=text("state = 'queued'"),
        ),
        # Optimized index for scheduled retries
        Index(
            "idx_queued_runs_scheduled_optimized",
            "campaign_id",
            "scheduled_for",
            postgresql_where=text("scheduled_for IS NOT NULL"),
        ),
        UniqueConstraint(
            "campaign_id",
            "source_uuid",
            "retry_count",
            name="unique_campaign_source_retry",
        ),
    )


class EmbedTokenModel(Base):
    """Model for storing workflow embed tokens"""

    __tablename__ = "embed_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(255), unique=True, nullable=False, index=True)
    workflow_id = Column(
        Integer,
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organization_id = Column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    allowed_domains = Column(JSON, nullable=True)  # Array of whitelisted domains
    settings = Column(JSON, nullable=True)  # Widget customization settings
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    usage_limit = Column(Integer, nullable=True)  # Optional usage limit
    usage_count = Column(Integer, default=0, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    created_by = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    updated_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    workflow = relationship("WorkflowModel")
    organization = relationship("OrganizationModel")
    creator = relationship("UserModel")
    sessions = relationship(
        "EmbedSessionModel", back_populates="embed_token", cascade="all, delete-orphan"
    )


class EmbedSessionModel(Base):
    """Model for storing temporary embed sessions"""

    __tablename__ = "embed_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_token = Column(String(255), unique=True, nullable=False, index=True)
    embed_token_id = Column(
        Integer, ForeignKey("embed_tokens.id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id = Column(
        Integer, ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=True
    )
    client_ip = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    origin = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)

    # Relationships
    embed_token = relationship("EmbedTokenModel", back_populates="sessions")
    workflow_run = relationship("WorkflowRunModel")


# =============================================================================
# Custom Tools & Actions Models
# =============================================================================


class CustomToolModel(Base):
    """
    Model for storing custom tool definitions.
    
    Custom tools allow users to extend workflow capabilities with:
    - HTTP/REST API calls
    - Webhook triggers
    - Database queries (via webhooks)
    - Custom code execution
    - Third-party integrations
    """

    __tablename__ = "custom_tools"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    
    # Tool identification
    name = Column(String(255), nullable=False)  # Unique identifier within org
    display_name = Column(String(255), nullable=False)  # Human-readable name
    description = Column(Text, nullable=False)  # Description for LLM context
    
    # Tool type and configuration
    tool_type = Column(
        Enum(ToolType),
        nullable=False,
    )
    configuration = Column(JSONB, nullable=False, default=dict)
    """
    Configuration schema varies by tool_type:
    
    http_request:
        {
            "url": "https://api.example.com/endpoint",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "body_template": "{ \"data\": \"{{input}}\" }",
            "response_path": "$.result"  # JSONPath to extract result
        }
    
    webhook:
        {
            "webhook_endpoint_id": 123,
            "payload_template": "{ \"action\": \"{{action}}\" }"
        }
    
    database_query:
        {
            "webhook_endpoint_id": 123,
            "query_type": "select|insert|update",
            "table_hint": "customers"  # For LLM context
        }
    
    custom_code:
        {
            "runtime": "javascript|python",
            "code": "function execute(input) { return input.toUpperCase(); }",
            "sandbox_config": {}
        }
    
    integration:
        {
            "integration_id": "salesforce",
            "action": "create_lead",
            "mapping": {}
        }
    """
    
    # Input/Output schema (JSON Schema format for LLM function calling)
    input_schema = Column(JSONB, nullable=False, default=dict)
    """
    JSON Schema for tool input parameters, e.g.:
    {
        "type": "object",
        "properties": {
            "customer_id": {"type": "string", "description": "The customer ID to lookup"},
            "include_history": {"type": "boolean", "description": "Whether to include order history"}
        },
        "required": ["customer_id"]
    }
    """
    output_schema = Column(JSONB, nullable=True)
    
    # Tool settings
    is_active = Column(Boolean, default=True, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)  # System tools can't be deleted
    timeout_seconds = Column(Integer, default=30, nullable=False)
    retry_config = Column(JSONB, nullable=True)
    """
    {
        "max_retries": 3,
        "retry_delay_ms": 1000,
        "retry_on_status_codes": [500, 502, 503]
    }
    """
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    organization = relationship("OrganizationModel")
    creator = relationship("UserModel")
    executions = relationship("ToolExecutionModel", back_populates="tool")

    # Indexes
    __table_args__ = (
        Index("ix_custom_tools_organization_id", "organization_id"),
        Index("ix_custom_tools_name", "name"),
        Index("ix_custom_tools_tool_type", "tool_type"),
        UniqueConstraint("organization_id", "name", name="uq_custom_tools_org_name"),
    )


class ToolExecutionModel(Base):
    """
    Model for tracking tool execution history.
    
    Useful for:
    - Debugging failed executions
    - Analytics on tool usage
    - Audit trail
    """

    __tablename__ = "tool_executions"

    id = Column(Integer, primary_key=True, index=True)
    tool_id = Column(
        Integer, ForeignKey("custom_tools.id", ondelete="CASCADE"), nullable=False
    )
    workflow_run_id = Column(
        Integer, ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True
    )
    
    # Execution status
    status = Column(
        Enum(ExecutionStatus),
        nullable=False,
        default=ExecutionStatus.PENDING,
    )
    
    # Execution data
    input_data = Column(JSONB, nullable=True)
    output_data = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    tool = relationship("CustomToolModel", back_populates="executions")
    workflow_run = relationship("WorkflowRunModel")

    # Indexes
    __table_args__ = (
        Index("ix_tool_executions_tool_id", "tool_id"),
        Index("ix_tool_executions_workflow_run_id", "workflow_run_id"),
        Index("ix_tool_executions_status", "status"),
        Index("ix_tool_executions_created_at", "created_at"),
    )


class WebhookEndpointModel(Base):
    """
    Model for storing webhook endpoint configurations.
    
    Reusable webhook configurations that can be referenced by multiple tools.
    """

    __tablename__ = "webhook_endpoints"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    
    # Endpoint configuration
    name = Column(String(255), nullable=False)
    endpoint_url = Column(Text, nullable=False)
    http_method = Column(
        Enum(HttpMethod),
        nullable=False,
        default=HttpMethod.POST,
    )
    headers = Column(JSONB, nullable=True)  # Default headers
    
    # Authentication
    auth_type = Column(String(50), nullable=True)  # none, api_key, bearer, basic, oauth2
    auth_config = Column(JSONB, nullable=True)
    """
    Authentication configuration varies by auth_type:
    
    api_key:
        {
            "header_name": "X-API-Key",
            "api_key": "encrypted_value"
        }
    
    bearer:
        {
            "token": "encrypted_value"
        }
    
    basic:
        {
            "username": "user",
            "password": "encrypted_value"
        }
    
    oauth2:
        {
            "client_id": "...",
            "client_secret": "encrypted_value",
            "token_url": "...",
            "scope": "..."
        }
    """
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    organization = relationship("OrganizationModel")

    # Indexes
    __table_args__ = (
        Index("ix_webhook_endpoints_organization_id", "organization_id"),
    )


# =============================================================================
# Knowledge Base Models
# =============================================================================


class KnowledgeBaseDocumentModel(Base):
    """
    Model for storing knowledge base documents.
    
    Documents are stored per organization and can be used by agents
    to provide contextual information during conversations.
    """

    __tablename__ = "knowledge_base_documents"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    workflow_id = Column(
        Integer, ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True
    )
    
    # Document metadata
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    file_type = Column(String(50), nullable=False)  # txt, pdf, md, etc.
    file_size_bytes = Column(Integer, nullable=True)
    
    # Document content
    content = Column(Text, nullable=False)  # Raw text content
    
    # Chunking information
    chunk_count = Column(Integer, default=0, nullable=False)
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    processing_status = Column(
        String(50),
        nullable=False,
        default="pending",
        server_default="pending",
    )  # pending, processing, completed, failed
    processing_error = Column(Text, nullable=True)
    
    # Timestamps
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    organization = relationship("OrganizationModel")
    workflow = relationship("WorkflowModel", foreign_keys=[workflow_id])
    creator = relationship("UserModel")
    chunks = relationship("KnowledgeBaseChunkModel", back_populates="document", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("ix_kb_documents_organization_id", "organization_id"),
        Index("ix_kb_documents_workflow_id", "workflow_id"),
        Index("ix_kb_documents_name", "name"),
        Index("ix_kb_documents_status", "processing_status"),
    )


# =============================================================================
# Subscription Models
# =============================================================================


class SubscriptionModel(Base):
    """
    Model for tracking organization subscriptions and trial usage.

    Pricing tiers:
    - trial: 15 minutes free, 1 workflow, no campaigns
    - plus: $49/mo, 500 min, 5 workflows, unlimited campaigns, $0.12/min overage
    - pro: $149/mo, 2000 min, 10 workflows, unlimited campaigns, Gemini S2S, $0.09/min overage
    """

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    # Plan info
    plan = Column(
        String(50), nullable=False, default="trial"
    )  # trial, plus, pro
    status = Column(
        String(50), nullable=False, default="active"
    )  # active, canceled, past_due, expired

    # Stripe fields
    stripe_customer_id = Column(String(255), nullable=True, unique=True)
    stripe_subscription_id = Column(String(255), nullable=True, unique=True)
    stripe_price_id = Column(String(255), nullable=True)

    # Usage tracking
    minutes_included = Column(Integer, nullable=False, default=15)  # Minutes included in plan
    minutes_used = Column(Float, nullable=False, default=0)  # Total minutes used this period
    overage_rate_per_minute = Column(Float, nullable=True)  # Rate for overage minutes

    # Feature limits
    max_workflows = Column(Integer, nullable=False, default=1)
    max_campaign_contacts = Column(Integer, nullable=False, default=0)  # 0 = no campaigns
    gemini_s2s_enabled = Column(Boolean, nullable=False, default=False)

    # Trial tracking
    trial_minutes_total = Column(Integer, nullable=False, default=15)
    trial_started_at = Column(DateTime(timezone=True), nullable=True)
    trial_expired = Column(Boolean, nullable=False, default=False)

    # Billing period
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    canceled_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization = relationship("OrganizationModel")

    # Indexes
    __table_args__ = (
        Index("ix_subscriptions_organization_id", "organization_id"),
        Index("ix_subscriptions_stripe_customer_id", "stripe_customer_id"),
        Index("ix_subscriptions_stripe_subscription_id", "stripe_subscription_id"),
        Index("ix_subscriptions_plan", "plan"),
        Index("ix_subscriptions_status", "status"),
    )


class WorkflowImprovementModel(Base):
    """Stores AI-generated improvement suggestions from self-improving analysis."""

    __tablename__ = "workflow_improvements"

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    status = Column(
        Enum("pending", "accepted", "rejected", "auto_applied", name="improvement_status"),
        nullable=False,
        default="pending",
    )
    suggestions = Column(JSON, nullable=False, default=list)
    analysis_summary = Column(Text, nullable=True)
    calls_analyzed = Column(Integer, nullable=False, default=0)
    last_run_id_analyzed = Column(Integer, nullable=True)
    # Per-suggestion decision tracking. Each entry is the int index into
    # `suggestions`. A batch is "settled" when len(applied|rejected) == len(suggestions).
    applied_indices = Column(JSON, nullable=False, default=list)
    rejected_indices = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    workflow = relationship("WorkflowModel")
    organization = relationship("OrganizationModel")

    __table_args__ = (
        Index("ix_workflow_improvements_workflow_id", "workflow_id"),
        Index("ix_workflow_improvements_status", "status"),
        Index("ix_workflow_improvements_workflow_status", "workflow_id", "status"),
    )


class KnowledgeBaseChunkModel(Base):
    """
    Model for storing document chunks for semantic search.
    
    Each document is split into chunks for efficient retrieval.
    Chunks can be embedded and searched using vector similarity.
    """

    __tablename__ = "knowledge_base_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(
        Integer, ForeignKey("knowledge_base_documents.id", ondelete="CASCADE"), nullable=False
    )
    
    # Chunk content
    chunk_index = Column(Integer, nullable=False)  # Position in document
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=True)
    
    # Optional embedding (stored as JSON array of floats)
    # In production, use pgvector extension for better performance
    embedding = Column(JSONB, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    # Relationships
    document = relationship("KnowledgeBaseDocumentModel", back_populates="chunks")

    # Indexes
    __table_args__ = (
        Index("ix_kb_chunks_document_id", "document_id"),
        Index("ix_kb_chunks_document_index", "document_id", "chunk_index"),
    )


# =============================================================================
# Compliance Models (TCPA / DNC / PECR / UK GDPR / TPS / Ofcom)
# =============================================================================


class ComplianceDNCEntryModel(Base):
    """Internal Do-Not-Call / suppression list, scoped per organization.

    Phase A stores only org-managed entries (``internal`` / ``opt_out_request``).
    Phase B will populate ``ftc_dnc`` / ``tps`` / ``ctps`` rows from external
    registry syncs using the same table and lookup path.
    """

    __tablename__ = "compliance_dnc_entries"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    # SHA-256 of the E.164 number for fast, privacy-preserving lookups.
    phone_number_hash = Column(String(64), nullable=False, index=True)
    # E.164 number kept for display / export / regulatory reporting.
    phone_number_e164 = Column(String(20), nullable=False)
    source = Column(
        Enum(
            "internal",
            "opt_out_request",
            "ftc_dnc",
            "tps",
            "ctps",
            name="compliance_dnc_source",
        ),
        nullable=False,
        default="internal",
        server_default=text("'internal'::compliance_dnc_source"),
    )
    country_code = Column(String(2), nullable=True)  # ISO-3166 alpha-2 (US, GB)
    is_active = Column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    notes = Column(Text, nullable=True)
    added_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    added_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    expires_at = Column(DateTime(timezone=True), nullable=True)

    organization = relationship("OrganizationModel")
    added_by_user = relationship("UserModel")

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "phone_number_hash",
            "source",
            name="uq_dnc_org_phone_source",
        ),
        Index("ix_dnc_org_hash", "organization_id", "phone_number_hash"),
        Index("ix_dnc_org_active", "organization_id", "is_active"),
    )


class ComplianceConsentRecordModel(Base):
    """Consent proof for TCPA (US) and PECR / UK GDPR (UK) outbound calling."""

    __tablename__ = "compliance_consent_records"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    phone_number_hash = Column(String(64), nullable=False, index=True)
    phone_number_e164 = Column(String(20), nullable=False)
    consent_type = Column(
        Enum(
            "express_written",
            "express_oral",
            "prior_relationship",
            "opt_in",
            name="compliance_consent_type",
        ),
        nullable=False,
        default="opt_in",
    )
    regulation = Column(
        Enum("tcpa", "pecr", "uk_gdpr", name="compliance_regulation"),
        nullable=False,
        default="tcpa",
    )
    # Where consent came from: web form URL, recording id, import filename, etc.
    consent_source = Column(String(500), nullable=True)
    # Link to stored evidence (signed form, call recording).
    evidence_url = Column(String(1000), nullable=True)
    is_active = Column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    consent_given_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    consent_revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    organization = relationship("OrganizationModel")
    created_by_user = relationship("UserModel")

    __table_args__ = (
        Index("ix_consent_org_hash", "organization_id", "phone_number_hash"),
        Index("ix_consent_org_active", "organization_id", "is_active"),
    )


class ComplianceAuditLogModel(Base):
    """Immutable audit trail of every compliance decision and action.

    Retained long-term (5y TCPA / 6y UK GDPR) for regulatory reporting.
    """

    __tablename__ = "compliance_audit_log"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id = Column(
        Integer, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    workflow_run_id = Column(
        Integer, ForeignKey("workflow_runs.id", ondelete="SET NULL"), nullable=True
    )
    phone_number_hash = Column(String(64), nullable=True, index=True)
    action = Column(
        Enum(
            "call_allowed",
            "call_blocked_dnc",
            "call_blocked_no_consent",
            "call_blocked_hours",
            "consent_recorded",
            "consent_revoked",
            "dnc_added",
            "dnc_removed",
            "ai_disclosure_played",
            "data_erased",
            name="compliance_audit_action",
        ),
        nullable=False,
    )
    regulation = Column(
        Enum("tcpa", "pecr", "uk_gdpr", "dnc", "ofcom", "stir_shaken", name="compliance_audit_regulation"),
        nullable=True,
    )
    details = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True
    )

    organization = relationship("OrganizationModel")

    __table_args__ = (
        Index("ix_audit_org_created", "organization_id", "created_at"),
        Index("ix_audit_org_action", "organization_id", "action"),
        Index("ix_audit_campaign", "campaign_id"),
    )
