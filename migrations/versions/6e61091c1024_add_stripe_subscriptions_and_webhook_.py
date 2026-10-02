"""add_stripe_subscriptions_and_webhook_events

Revision ID: 6e61091c1024
Revises: d32bec0b796e
Create Date: 2026-10-02 11:12:46.559115

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6e61091c1024'
down_revision = 'd32bec0b796e'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    # 1. Create subscriptions table if not present
    if 'subscriptions' not in existing_tables:
        op.create_table(
            'subscriptions',
            sa.Column('id', sa.String(length=64), nullable=False),
            sa.Column('organization_id', sa.String(length=64), nullable=False),
            sa.Column('stripe_customer_id', sa.String(length=128), nullable=True),
            sa.Column('stripe_subscription_id', sa.String(length=128), nullable=True),
            sa.Column('stripe_price_id', sa.String(length=128), nullable=True),
            sa.Column('plan_tier', sa.String(length=32), nullable=False, server_default='free'),
            sa.Column('status', sa.String(length=64), nullable=False, server_default='active'),
            sa.Column('billing_interval', sa.String(length=32), nullable=False, server_default='month'),
            sa.Column('current_period_start', sa.DateTime(), nullable=True),
            sa.Column('current_period_end', sa.DateTime(), nullable=True),
            sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False, server_default=sa.text('0')),
            sa.Column('canceled_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('subscriptions', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_subscriptions_organization_id'), ['organization_id'], unique=True)
            batch_op.create_index(batch_op.f('ix_subscriptions_stripe_customer_id'), ['stripe_customer_id'], unique=False)
            batch_op.create_index(batch_op.f('ix_subscriptions_stripe_subscription_id'), ['stripe_subscription_id'], unique=False)

    # 2. Create stripe_webhook_events table if not present
    if 'stripe_webhook_events' not in existing_tables:
        op.create_table(
            'stripe_webhook_events',
            sa.Column('id', sa.String(length=64), nullable=False),
            sa.Column('event_id', sa.String(length=128), nullable=False),
            sa.Column('event_type', sa.String(length=128), nullable=False),
            sa.Column('payload_summary', sa.Text(), nullable=True),
            sa.Column('status', sa.String(length=32), nullable=False, server_default='processed'),
            sa.Column('processed_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('stripe_webhook_events', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_stripe_webhook_events_event_id'), ['event_id'], unique=True)

    # 3. Add Stripe fields to organizations if not present
    org_columns = [c['name'] for c in inspector.get_columns('organizations')]
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        if 'stripe_customer_id' not in org_columns:
            batch_op.add_column(sa.Column('stripe_customer_id', sa.String(length=128), nullable=True))
            batch_op.create_index(batch_op.f('ix_organizations_stripe_customer_id'), ['stripe_customer_id'], unique=False)
        if 'stripe_subscription_id' not in org_columns:
            batch_op.add_column(sa.Column('stripe_subscription_id', sa.String(length=128), nullable=True))
            batch_op.create_index(batch_op.f('ix_organizations_stripe_subscription_id'), ['stripe_subscription_id'], unique=False)


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = inspector.get_table_names()

    org_columns = [c['name'] for c in inspector.get_columns('organizations')]
    with op.batch_alter_table('organizations', schema=None) as batch_op:
        if 'stripe_subscription_id' in org_columns:
            try:
                batch_op.drop_index(batch_op.f('ix_organizations_stripe_subscription_id'))
            except Exception:
                pass
            batch_op.drop_column('stripe_subscription_id')
        if 'stripe_customer_id' in org_columns:
            try:
                batch_op.drop_index(batch_op.f('ix_organizations_stripe_customer_id'))
            except Exception:
                pass
            batch_op.drop_column('stripe_customer_id')

    if 'stripe_webhook_events' in existing_tables:
        op.drop_table('stripe_webhook_events')
    if 'subscriptions' in existing_tables:
        op.drop_table('subscriptions')
