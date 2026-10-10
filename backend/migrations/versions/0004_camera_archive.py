"""Recoverable camera archive and explicit fire/smoke alarm labels."""
from alembic import op
import sqlalchemy as sa
revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None
def upgrade():
    inspector=sa.inspect(op.get_bind())
    if 'archived_at' not in {c['name'] for c in inspector.get_columns('cameras')}:
        op.add_column('cameras',sa.Column('archived_at',sa.DateTime(timezone=True),nullable=True))
    if 'candidate_label' not in {c['name'] for c in inspector.get_columns('alerts')}:
        op.add_column('alerts',sa.Column('candidate_label',sa.String(12),nullable=False,server_default='fire'))
def downgrade():
    raise RuntimeError('Destructive downgrade disabled; restore a backup instead.')
