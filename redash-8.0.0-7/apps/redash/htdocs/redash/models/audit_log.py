"""
Audit Log Model

Tracks security-relevant actions for compliance and monitoring.
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Index
from sqlalchemy.orm import relationship
from redash.models.base import db
from redash.models.mixins import BelongsToOrgMixin


class AuditLog(BelongsToOrgMixin, db.Model):
    """
    Model for tracking security-relevant actions.
    
    Logs permission checks, role assignments, and other security events
    for compliance and audit purposes.
    """
    __tablename__ = 'audit_logs'
    
    # Primary key
    id = Column(Integer, primary_key=True)
    
    # Action details
    action = Column(String(255), nullable=False)
    success = Column(Boolean, nullable=False, default=True)
    
    # User and organization
    user_id = Column(Integer, db.ForeignKey('users.id'), nullable=True)
    org_id = Column(Integer, db.ForeignKey('organizations.id'), nullable=False)
    
    # Resource details
    resource_type = Column(String(50), nullable=True)
    resource_id = Column(Integer, nullable=True)
    
    # Request context
    ip_address = Column(String(45), nullable=True)  # IPv6 max length
    user_agent = Column(Text, nullable=True)
    
    # Additional details
    details = Column(Text, nullable=True)  # JSON string for additional context
    
    # Timestamp
    created_at = Column(DateTime, nullable=False, default=db.func.now())
    
    # Relationships
    user = relationship('User', foreign_keys=[user_id])
    org = relationship('Organization', backref='audit_logs')
    
    # Indexes for query performance
    __table_args__ = (
        Index('idx_audit_logs_user_id', 'user_id'),
        Index('idx_audit_logs_org_id', 'org_id'),
        Index('idx_audit_logs_created_at', 'created_at'),
        Index('idx_audit_logs_action', 'action'),
        Index('idx_audit_logs_resource', 'resource_type', 'resource_id'),
    )
    
    def __repr__(self):
        return '<AuditLog id={} action={} user_id={} success={}>'.format(
            self.id, self.action, self.user_id, self.success
        )
    
    def to_dict(self):
        """Convert audit log to dictionary."""
        return {
            'id': self.id,
            'action': self.action,
            'success': self.success,
            'user_id': self.user_id,
            'org_id': self.org_id,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'details': self.details,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
