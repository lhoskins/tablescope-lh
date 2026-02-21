"""
MFA Configuration Model
Stores MFA enrollment status and phone number for users.
"""

import logging
from sqlalchemy.orm import relationship
from sqlalchemy_utils.models import generic_repr

from .base import db, Column
from .mixins import TimestampMixin

logger = logging.getLogger(__name__)


@generic_repr('id', 'user_id', 'phone_number_verified', 'is_enabled')
class MFAConfig(db.Model, TimestampMixin):
    """
    Stores MFA configuration for users requiring two-factor authentication.
    
    Attributes:
        id: Primary key
        user_id: Foreign key to users table (unique)
        phone_number: Phone number in E.164 format (+1234567890)
        phone_number_verified: Whether the phone number has been verified
        is_enabled: Whether MFA is currently enabled
        enrolled_at: When the user first enrolled in MFA
        last_used_at: Last time MFA was successfully used
    """
    
    __tablename__ = 'mfa_configs'
    
    id = Column(db.Integer, primary_key=True)
    user_id = Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), 
                     unique=True, nullable=False)
    phone_number = Column(db.String(20), nullable=False)
    phone_number_verified = Column(db.Boolean, default=False, nullable=False)
    is_enabled = Column(db.Boolean, default=True, nullable=False)
    enrolled_at = Column(db.DateTime(True), nullable=False, default=db.func.now())
    last_used_at = Column(db.DateTime(True), nullable=True)
    
    # Relationships
    user = relationship('User', backref=db.backref('mfa_config', uselist=False, cascade='all, delete-orphan'))
    
    # Indexes defined in migration SQL
    __table_args__ = (
        db.Index('idx_mfa_configs_user_id', 'user_id'),
        db.Index('idx_mfa_configs_enabled', 'is_enabled', postgresql_where=(is_enabled == True)),
    )
    
    def to_dict(self, include_phone=False):
        """
        Convert model to dictionary.
        
        Args:
            include_phone: If True, include full phone number (admin only)
            
        Returns:
            dict: Model data
        """
        data = {
            'id': self.id,
            'user_id': self.user_id,
            'phone_number_masked': self.get_masked_phone(),
            'phone_number_verified': self.phone_number_verified,
            'is_enabled': self.is_enabled,
            'enrolled_at': self.enrolled_at.isoformat() if self.enrolled_at else None,
            'last_used_at': self.last_used_at.isoformat() if self.last_used_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        
        if include_phone:
            data['phone_number'] = self.phone_number
        
        return data
    
    def get_masked_phone(self):
        """
        Return phone number with only last 4 digits visible.
        
        Returns:
            str: Masked phone number (e.g., "****1234")
        """
        if not self.phone_number or len(self.phone_number) < 4:
            return '****'
        return '*' * (len(self.phone_number) - 4) + self.phone_number[-4:]
    
    def mark_used(self):
        """Update last_used_at timestamp."""
        self.last_used_at = db.func.now()
        db.session.add(self)
    
    def disable(self):
        """Disable MFA for this user."""
        self.is_enabled = False
        db.session.add(self)
    
    def enable(self):
        """Enable MFA for this user."""
        self.is_enabled = True
        db.session.add(self)
    
    @classmethod
    def get_by_user_id(cls, user_id):
        """
        Get MFA config for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            MFAConfig or None
        """
        return cls.query.filter_by(user_id=user_id, is_enabled=True).first()
    
    @classmethod
    def is_enrolled(cls, user_id):
        """
        Check if user has MFA enrolled and enabled.
        
        Args:
            user_id: User ID
            
        Returns:
            bool: True if user has MFA enrolled
        """
        config = cls.get_by_user_id(user_id)
        return config is not None and config.phone_number_verified
    
    def __repr__(self):
        return '<MFAConfig user_id={} verified={} enabled={}>'.format(
            self.user_id, self.phone_number_verified, self.is_enabled
        )
