"""add_user_phone_and_department

Revision ID: a1b2c3d4e5f6
Revises: 69e301dace34
Create Date: 2026-10-19 23:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '69e301dace34'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()
    columns = [c['name'] for c in inspector.get_columns('users')] if 'users' in existing_tables else []

    with op.batch_alter_table('users', schema=None) as batch_op:
        if 'phone' not in columns:
            batch_op.add_column(sa.Column('phone', sa.String(length=64), nullable=True))
        if 'department' not in columns:
            batch_op.add_column(sa.Column('department', sa.String(length=64), nullable=True, server_default='General'))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('department')
        batch_op.drop_column('phone')
