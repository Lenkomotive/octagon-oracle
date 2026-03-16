"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-16
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'events',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('date', sa.Date()),
        sa.Column('ufcstats_url', sa.String()),
        sa.UniqueConstraint('slug'),
    )

    op.create_table(
        'fights',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('event_id', sa.Integer(), sa.ForeignKey('events.id'), nullable=False),
        sa.Column('fighter1', sa.String(), nullable=False),
        sa.Column('fighter2', sa.String(), nullable=False),
        sa.Column('winner', sa.String()),
        sa.Column('method', sa.String()),
        sa.Column('round', sa.Integer()),
        sa.Column('time', sa.String()),
        sa.Column('weight_class', sa.String()),
    )

    op.create_table(
        'channels',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('youtube_url', sa.String(), nullable=False),
        sa.Column('keywords', sa.String()),
    )

    op.create_table(
        'videos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('video_id', sa.String(), nullable=False),
        sa.Column('channel_id', sa.Integer(), sa.ForeignKey('channels.id')),
        sa.Column('title', sa.String()),
        sa.Column('upload_date', sa.Date()),
        sa.Column('is_prediction', sa.Boolean()),
        sa.Column('transcript', sa.Text()),
        sa.Column('transcript_method', sa.String()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('video_id'),
    )

    op.create_table(
        'predictions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('video_id', sa.Integer(), sa.ForeignKey('videos.id'), nullable=False),
        sa.Column('event_id', sa.Integer(), sa.ForeignKey('events.id')),
        sa.Column('fighter_picked', sa.String(), nullable=False),
        sa.Column('fighter_against', sa.String(), nullable=False),
        sa.Column('method', sa.String()),
        sa.Column('confidence', sa.String()),
    )

    op.create_table(
        'scores',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('prediction_id', sa.Integer(), sa.ForeignKey('predictions.id'), nullable=False),
        sa.Column('fight_id', sa.Integer(), sa.ForeignKey('fights.id')),
        sa.Column('correct', sa.Boolean()),
        sa.Column('method_correct', sa.Boolean()),
        sa.UniqueConstraint('prediction_id'),
    )


def downgrade() -> None:
    op.drop_table('scores')
    op.drop_table('predictions')
    op.drop_table('videos')
    op.drop_table('channels')
    op.drop_table('fights')
    op.drop_table('events')
