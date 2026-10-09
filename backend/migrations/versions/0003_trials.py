from alembic import op
from app.models import MonitorTrial, TrialEvidence
revision = "0003"
down_revision = "0002"
branch_labels = depends_on = None

def upgrade():
    for table in (MonitorTrial.__table__, TrialEvidence.__table__):
        table.create(op.get_bind(), checkfirst=True)

def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup.")
