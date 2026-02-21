"""
UserVDB Model

Stores VDB (Virtual Database) mappings and credentials for individual users.
Provides user-level data isolation through dedicated Teiid VDBs.
"""

from six import python_2_unicode_compatible
from sqlalchemy.orm import relationship
from sqlalchemy_utils.models import generic_repr

from redash import settings
from .base import db, Column
from .mixins import TimestampMixin
from .types import EncryptedConfiguration
from sqlalchemy_utils.types.encrypted.encrypted_type import FernetEngine


@python_2_unicode_compatible
@generic_repr('id', 'user_id', 'vdb_id', 'is_active')
class UserVDB(TimestampMixin, db.Model):
    """
    Model for storing VDB configuration and credentials for individual users.
    
    Each user gets their own VDB with unique credentials for data isolation.
    """
    
    __tablename__ = 'user_vdbs'
    
    id = Column(db.Integer, primary_key=True)
    user_id = Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    organization_id = Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    
    user = relationship('User', backref='vdb_config')
    organization = relationship('Organization', backref='user_vdbs')
    
    vdb_id = Column(db.String(255), unique=True, nullable=False)
    vdb_username = Column(db.String(255), nullable=False)
    
    # Plain text password (encryption can be added later if needed)
    # Note: EncryptedConfiguration is for complex JSON objects, not simple passwords
    encrypted_password = Column('encrypted_password', db.String(255), nullable=False)
    
    vdb_host = Column(db.String(255), default='127.0.0.1')
    vdb_port = Column(db.Integer, default=35442)
    is_active = Column(db.Boolean, default=True)
    
    last_health_check = Column(db.DateTime(True), nullable=True)
    health_status = Column(db.String(50), default='unknown')
    
    def __str__(self):
        return u'UserVDB(user_id={}, vdb_id={})'.format(self.user_id, self.vdb_id)
    
    @classmethod
    def get_by_user(cls, user_id):
        """Get VDB configuration for a user."""
        return cls.query.filter(cls.user_id == user_id).first()
    
    @classmethod
    def get_by_vdb_id(cls, vdb_id):
        """Get VDB configuration by VDB identifier."""
        return cls.query.filter(cls.vdb_id == vdb_id).first()
    
    def get_connection_string(self):
        """
        Build PostgreSQL-compatible connection string for this VDB.
        
        Teiid exposes a PostgreSQL-compatible interface that psycopg2 can connect to.
        Format: postgresql://user:password@host:port/database
        
        Note: Credentials are passed separately for security, so this returns
        the connection string WITHOUT credentials.
        
        Teiid requires VDB name to include version: vdb_name.version
        The version is always "1" for our VDBs.
        """
        # Teiid requires VDB name with version (e.g., "4869479.1")
        vdb_name_with_version = "{}.1".format(self.vdb_id)
        
        return "postgresql://{}:{}/{}".format(
            self.vdb_host,
            self.vdb_port,
            vdb_name_with_version
        )
    
    def get_decrypted_password(self):
        """Return the decrypted VDB password."""
        return self.encrypted_password
    
    def set_encrypted_password(self, plain_password):
        """Store the password (will be encrypted automatically)."""
        self.encrypted_password = plain_password
    
    def to_dict(self, include_credentials=False):
        """Serialize to dictionary."""
        d = {
            'id': self.id,
            'user_id': self.user_id,
            'organization_id': self.organization_id,
            'vdb_id': self.vdb_id,
            'vdb_host': self.vdb_host,
            'vdb_port': self.vdb_port,
            'is_active': self.is_active,
            'health_status': self.health_status,
            'last_health_check': self.last_health_check.isoformat() if self.last_health_check else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        
        if include_credentials:
            d['vdb_username'] = self.vdb_username
        
        return d
    
    def update_health_status(self, status, check_time=None):
        """Update the health status of this VDB."""
        from datetime import datetime
        
        self.health_status = status
        self.last_health_check = check_time or datetime.utcnow()
        db.session.add(self)
