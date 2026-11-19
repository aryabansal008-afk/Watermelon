"""Persist OpenRouter usage metadata for chat answers."""
from alembic import op
import sqlalchemy as sa

revision = "3fa17d42a910"
down_revision = "8b91d1c7a04f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chat_messages", sa.Column("prompt_tokens", sa.Integer(), nullable=True))
    op.add_column("chat_messages", sa.Column("completion_tokens", sa.Integer(), nullable=True))
    op.add_column("chat_messages", sa.Column("cost_usd", sa.Float(), nullable=True))


def downgrade():
    op.drop_column("chat_messages", "cost_usd")
    op.drop_column("chat_messages", "completion_tokens")
    op.drop_column("chat_messages", "prompt_tokens")
