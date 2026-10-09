from alembic import op
from app.models import Monitor, IncidentLocation, AlertReview
revision = "0002"
down_revision = "0001"
branch_labels = depends_on = None
def upgrade():
    for table in (Monitor.__table__, IncidentLocation.__table__, AlertReview.__table__):
        table.create(op.get_bind(), checkfirst=True)
def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a verified backup.")
