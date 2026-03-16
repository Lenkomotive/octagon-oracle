from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, Date, Text, Float,
    ForeignKey, UniqueConstraint, DateTime
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.sql import func
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/octagon_oracle")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, nullable=False)
    date = Column(Date)
    ufcstats_url = Column(String)

    fights = relationship("Fight", back_populates="event")
    predictions = relationship("Prediction", back_populates="event")


class Fight(Base):
    __tablename__ = "fights"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    fighter1 = Column(String, nullable=False)
    fighter2 = Column(String, nullable=False)
    winner = Column(String)
    method = Column(String)
    round = Column(Integer)
    time = Column(String)
    weight_class = Column(String)

    event = relationship("Event", back_populates="fights")
    scores = relationship("Score", back_populates="fight")


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    youtube_url = Column(String, nullable=False)
    keywords = Column(String)  # comma-separated

    videos = relationship("Video", back_populates="channel")


class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True)
    video_id = Column(String, unique=True, nullable=False)
    channel_id = Column(Integer, ForeignKey("channels.id"))
    title = Column(String)
    upload_date = Column(Date)
    is_prediction = Column(Boolean)
    transcript = Column(Text)
    transcript_method = Column(String)
    created_at = Column(DateTime, server_default=func.now())

    channel = relationship("Channel", back_populates="videos")
    predictions = relationship("Prediction", back_populates="video")


class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    event_id = Column(Integer, ForeignKey("events.id"))
    fighter_picked = Column(String, nullable=False)
    fighter_against = Column(String, nullable=False)
    method = Column(String)
    confidence = Column(String)

    video = relationship("Video", back_populates="predictions")
    event = relationship("Event", back_populates="predictions")
    score = relationship("Score", back_populates="prediction", uselist=False)


class Score(Base):
    __tablename__ = "scores"

    id = Column(Integer, primary_key=True)
    prediction_id = Column(Integer, ForeignKey("predictions.id"), unique=True, nullable=False)
    fight_id = Column(Integer, ForeignKey("fights.id"))
    correct = Column(Boolean)
    method_correct = Column(Boolean)

    prediction = relationship("Prediction", back_populates="score")
    fight = relationship("Fight", back_populates="scores")
