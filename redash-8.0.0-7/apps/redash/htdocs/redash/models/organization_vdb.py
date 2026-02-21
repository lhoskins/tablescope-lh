"""
OrganizationVDB Model

Stores VDB (Virtual Database) mappings and credentials for each organization.
Provides organization-level data isolation through dedicated Teiid VDBs.

NOTE: Password is currently stored as plain text. Encryption will be added in a future update.
"""

from six import python_2_unicode_compatible
from sqlalchemy.orm import relationship
from sqlalchemy_utils.models import generic_repr

from .base import db, Column
from .mixins import TimestampMixin


@python_2_unicode_compatible
@generic_repr('id', 'organization_id', 'vdb_id', 'is_active')
class OrganizationVDB(TimestampMixin, db.Model):
    """
    Model for storing VDB configuration and credentials for each organization.
    
    Each organization gets its own VDB with unique credentials for data isolation.
    """
    
    __tablename__ = 'organization_vdbs'
    
    id = Column(db.Integer, primary_key=True)
    organization_id = Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False, unique=True)
    organization = relationship('Organization', backref='vdb_config')
    
    vdb_id = Column(db.String(255), unique=True, nullable=False)
    vdb_username = Column(db.String(255), nullable=False)
    
    # Plain text password (encryption to be added later)
    encrypted_password = Column('encrypted_password', db.String(255), nullable=False)
    
    vdb_host = Column(db.String(255), default='localhost')
    vdb_port = Column(db.Integer, default=31000)
    is_active = Column(db.Boolean, default=True)
    
    last_health_check = Column(db.DateTime(True), nullable=True)
    health_status = Column(db.String(50), default='unknown')
    
    def __str__(self):
        return u'OrganizationVDB(org_id={}, vdb_id={})'.format(self.organization_id, self.vdb_id)
    
    @classmethod
    def get_by_organization(cls, org_id):
        """Get VDB configuration for an organization."""
        return cls.query.filter(cls.organization_id == org_id).first()
    
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
        """
        return "postgresql://{}:{}/{}".format(
            self.vdb_host,
            self.vdb_port,
            self.vdb_id
        )
    
    def get_decrypted_password(self):
        """Return the VDB password."""
        return self.encrypted_password
    
    def set_encrypted_password(self, plain_password):
        """Store the password."""
        self.encrypted_password = plain_password
    
    def to_dict(self, include_credentials=False):
        """Serialize to dictionary."""
        d = {
            'id': self.id,
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
