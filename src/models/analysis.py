"""SQLAlchemy models for analysis outputs."""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class AnalysisOutput(Base):
    """Analysis output from the agent."""
    __tablename__ = "analysis_outputs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    fund_id = Column(String(50), nullable=True, index=True)
    analysis_type = Column(String(100), nullable=False, index=True)
    insights = Column(Text, nullable=False)
    recommendations = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    agent_mode = Column(String(20), nullable=False)  # 'orchestrator' or 'rag'
    metadata = Column(JSON, nullable=True)
    
    # Sign-off fields
    status = Column(String(20), nullable=False, default='pending', index=True)  # pending, approved, rejected, completed
    priority = Column(String(20), nullable=True, index=True)  # critical, high, medium, low
    reviewed_by = Column(String(255), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    engineer_notes = Column(Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "fund_id": self.fund_id,
            "analysis_type": self.analysis_type,
            "insights": self.insights,
            "recommendations": self.recommendations,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "agent_mode": self.agent_mode,
            "metadata": self.metadata,
            "status": self.status,
            "priority": self.priority,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "engineer_notes": self.engineer_notes,
        }

