"""Add graph typing, traversal indexes, and persisted state bounds."""
from alembic import op
import sqlalchemy as sa

revision = "8b91d1c7a04f"
down_revision = "ac05005a2b7d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint("ck_decision_revision_positive", "decisions", "current_revision > 0")
    kinds = "'decision','discussion','message','alternative','code_entity','pull_request'"
    op.create_check_constraint("ck_graph_no_self_edge", "graph_edges", "source_id <> target_id")
    op.create_check_constraint("ck_graph_source_kind", "graph_edges", f"source_kind IN ({kinds})")
    op.create_check_constraint("ck_graph_target_kind", "graph_edges", f"target_kind IN ({kinds})")
    op.create_index("ix_graph_edges_project_source", "graph_edges", ["project_id", "source_id"])
    op.create_index("ix_graph_edges_project_target", "graph_edges", ["project_id", "target_id"])
    op.create_check_constraint("ck_job_progress_range", "ingestion_jobs", "progress >= 0 AND progress <= 100")
    op.create_check_constraint("ck_job_attempts_nonnegative", "ingestion_jobs", "attempts >= 0")
    op.create_check_constraint("ck_identity_links_distinct", "identity_links", "left_id <> right_id")
    op.create_unique_constraint("uq_identity_links_pair", "identity_links", ["left_id", "right_id"])
    op.create_index("ix_jobs_project_created", "ingestion_jobs", ["project_id", "created_at"])


def downgrade():
    op.drop_index("ix_jobs_project_created", table_name="ingestion_jobs")
    op.drop_constraint("uq_identity_links_pair", "identity_links", type_="unique")
    op.drop_constraint("ck_identity_links_distinct", "identity_links", type_="check")
    op.drop_constraint("ck_job_attempts_nonnegative", "ingestion_jobs", type_="check")
    op.drop_constraint("ck_job_progress_range", "ingestion_jobs", type_="check")
    op.drop_index("ix_graph_edges_project_target", table_name="graph_edges")
    op.drop_index("ix_graph_edges_project_source", table_name="graph_edges")
    op.drop_constraint("ck_graph_target_kind", "graph_edges", type_="check")
    op.drop_constraint("ck_graph_source_kind", "graph_edges", type_="check")
    op.drop_constraint("ck_graph_no_self_edge", "graph_edges", type_="check")
    op.drop_constraint("ck_decision_revision_positive", "decisions", type_="check")
