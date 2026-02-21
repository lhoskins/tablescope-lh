"""
MFA Backup Code Model
Stores hashed backup codes for emergency MFA access.
"""

import hashlib
import logging

# Python 2/3 compatibility for secrets module
try:
    import secrets
except ImportError:
    # Python 2 fallback
    import random
    import string
    
    class secrets:
        """Minimal secrets module implementation for Python 2."""
        
        @staticmethod
        def choice(seq):
            """Choose a random element from a non-empty sequence."""
            return random.SystemRandom().choice(seq)
from sqlalchemy.orm import relationship
from sqlalchemy_utils.models import generic_repr

from .base import db, Column
from .mixins import TimestampMixin

logger = logging.getLogger(__name__)


@generic_repr('id', 'user_id', 'is_used')
class MFABackupCode(db.Model, TimestampMixin):
    """
    Stores hashed backup codes for MFA recovery.
    
    Backup codes are 8-character alphanumeric codes that can be used
    when SMS is unavailable. Each code can only be used once.
    
    Attributes:
        id: Primary key
        user_id: Foreign key to users table
        code_hash: SHA-256 hash of the backup code
        is_used: Whether this code has been used
        used_at: When this code was used
    """
    
    __tablename__ = 'mfa_backup_codes'
    
    id = Column(db.Integer, primary_key=True)
    user_id = Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    code_hash = Column(db.String(64), nullable=False)
    is_used = Column(db.Boolean, default=False, nullable=False)
    used_at = Column(db.DateTime(True), nullable=True)
    
    # Relationships
    user = relationship('User', backref='mfa_backup_codes')
    
    # Indexes defined in migration SQL
    __table_args__ = (
        db.Index('idx_mfa_backup_codes_user_id', 'user_id'),
        db.Index('idx_mfa_backup_codes_code_hash', 'code_hash'),
        db.Index('idx_mfa_backup_codes_unused', 'user_id', 'is_used', 
                postgresql_where=(is_used == False)),
    )
    
    @staticmethod
    def generate_code():
        """
        Generate a random 8-character alphanumeric backup code.
        
        Uses characters that are easy to read and type:
        - Uppercase letters (excluding O, I)
        - Numbers (excluding 0, 1)
        
        Returns:
            str: 8-character backup code (e.g., "A3B7C9D2")
        """
        # Use characters that won't be confused: no O/0, I/1
        charset = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
        return ''.join(secrets.choice(charset) for _ in range(8))
    
    @staticmethod
    def hash_code(code):
        """
        Hash a backup code using SHA-256.
        
        Args:
            code: Plaintext backup code
            
        Returns:
            str: Hexadecimal hash of the code
        """
        return hashlib.sha256(code.encode('utf-8')).hexdigest()
    
    def verify_code(self, code):
        """
        Verify if the provided code matches this backup code.
        
        Args:
            code: Plaintext code to verify
            
        Returns:
            bool: True if code matches and hasn't been used
        """
        if self.is_used:
            return False
        
        code_upper = code.upper().strip()
        return self.code_hash == self.hash_code(code_upper)
    
    def mark_used(self):
        """Mark this backup code as used."""
        self.is_used = True
        self.used_at = db.func.now()
        db.session.add(self)
    
    @classmethod
    def generate_codes_for_user(cls, user_id, count=10):
        """
        Generate backup codes for a user.
        
        Args:
            user_id: User ID
            count: Number of codes to generate (default 10)
            
        Returns:
            list: Plaintext backup codes (store these securely!)
        """
        codes = []
        
        for _ in range(count):
            code = cls.generate_code()
            code_hash = cls.hash_code(code)
            
            backup_code = cls(
                user_id=user_id,
                code_hash=code_hash
            )
            db.session.add(backup_code)
            codes.append(code)
        
        return codes
    
    @classmethod
    def get_unused_count(cls, user_id):
        """
        Get count of unused backup codes for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            int: Number of unused backup codes
        """
        return cls.query.filter_by(user_id=user_id, is_used=False).count()
    
    @classmethod
    def verify_and_use(cls, user_id, code):
        """
        Verify a backup code and mark it as used if valid.
        
        Args:
            user_id: User ID
            code: Plaintext backup code
            
        Returns:
            tuple: (success: bool, remaining_codes: int or None)
        """
        code_upper = code.upper().strip()
        code_hash = cls.hash_code(code_upper)
        
        # Find matching unused code
        backup_code = cls.query.filter_by(
            user_id=user_id,
            code_hash=code_hash,
            is_used=False
        ).first()
        
        if backup_code:
            # Mark as used
            backup_code.mark_used()
            db.session.commit()
            
            # Count remaining codes
            remaining = cls.get_unused_count(user_id)
            
            logger.info("User {} used backup code ({} remaining)".format(user_id, remaining))
            return True, remaining
        
        logger.warning("User {} attempted invalid backup code".format(user_id))
        return False, None
    
    @classmethod
    def invalidate_all(cls, user_id):
        """
        Invalidate all backup codes for a user.
        Used when regenerating codes or disabling MFA.
        
        Args:
            user_id: User ID
            
        Returns:
            int: Number of codes invalidated
        """
        count = cls.query.filter_by(user_id=user_id).delete()
        db.session.commit()
        
        logger.info("Invalidated {} backup codes for user {}".format(count, user_id))
        return count
    
    def __repr__(self):
        return '<MFABackupCode user_id={} used={}>'.format(self.user_id, self.is_used)
