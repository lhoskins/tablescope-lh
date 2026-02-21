# redash/models/permission_cache.py

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy_utils.models import generic_repr
from six import python_2_unicode_compatible
from datetime import datetime, timedelta

from redash.models.base import db


@python_2_unicode_compatible
@generic_repr('user_id', 'permission', 'resource_type', 'resource_id')
class PermissionCache(db.Model):
    """
    Model for caching user permissions for performance optimization.
    
    Stores computed permissions with expiration to reduce database queries
    for permission checks.
    """
    __tablename__ = 'permission_cache'
    
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True, nullable=False)
    permission = Column(String(100), primary_key=True, nullable=False)
    resource_type = Column(String(50), primary_key=True, nullable=True, default='')
    resource_id = Column(Integer, primary_key=True, nullable=True, default=0)
    org_id = Column(Integer, ForeignKey('organizations.id'), nullable=False)
    cached_at = Column(DateTime, default=db.func.now())
    expires_at = Column(DateTime, nullable=True)
    
    # Relationships
    user = relationship('User', backref='permission_cache')
    organization = relationship('Organization')
    
    def __str__(self):
        if self.resource_type and self.resource_id:
            return u'PermissionCache({}, {}, {}:{})'.format(
                self.user_id, self.permission, self.resource_type, self.resource_id
            )
        return u'PermissionCache({}, {})'.format(self.user_id, self.permission)
    
    def is_expired(self):
        """
        Check if this cache entry has expired.
        
        Returns:
            bool: True if expired
        """
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at
    
    def to_dict(self):
        """
        Convert permission cache to dictionary.
        
        Returns:
            dict: Permission cache data
        """
        return {
            'user_id': self.user_id,
            'permission': self.permission,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'org_id': self.org_id,
            'cached_at': self.cached_at.isoformat() if self.cached_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_expired': self.is_expired()
        }
    
    @classmethod
    def get_cached_permission(cls, user_id, permission, resource_type=None, resource_id=None):
        """
        Get a cached permission if it exists and is not expired.
        
        Args:
            user_id (int): User ID
            permission (str): Permission string
            resource_type (str, optional): Resource type
            resource_id (int, optional): Resource ID
            
        Returns:
            bool: True if permission is cached and valid, False if not cached or expired, None if explicitly denied
        """
        resource_type = resource_type or ''
        resource_id = resource_id or 0
        
        cache_entry = cls.query.filter(
            cls.user_id == user_id,
            cls.permission == permission,
            cls.resource_type == resource_type,
            cls.resource_id == resource_id
        ).first()
        
        if not cache_entry:
            return None
        
        if cache_entry.is_expired():
            # Delete expired entry
            db.session.delete(cache_entry)
            db.session.commit()
            return None
        
        return True
    
    @classmethod
    def cache_permission(cls, user_id, permission, org_id, resource_type=None, 
                        resource_id=None, ttl_seconds=300):
        """
        Cache a permission for a user.
        
        Args:
            user_id (int): User ID
            permission (str): Permission string
            org_id (int): Organization ID
            resource_type (str, optional): Resource type
            resource_id (int, optional): Resource ID
            ttl_seconds (int): Time to live in seconds (default: 300 = 5 minutes)
            
        Returns:
            PermissionCache: Created or updated cache entry
        """
        resource_type = resource_type or ''
        resource_id = resource_id or 0
        
        # Check if entry exists
        cache_entry = cls.query.filter(
            cls.user_id == user_id,
            cls.permission == permission,
            cls.resource_type == resource_type,
            cls.resource_id == resource_id
        ).first()
        
        expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        
        if cache_entry:
            # Update existing entry
            cache_entry.cached_at = datetime.utcnow()
            cache_entry.expires_at = expires_at
        else:
            # Create new entry
            cache_entry = cls(
                user_id=user_id,
                permission=permission,
                resource_type=resource_type,
                resource_id=resource_id,
                org_id=org_id,
                expires_at=expires_at
            )
            db.session.add(cache_entry)
        
        return cache_entry
    
    @classmethod
    def invalidate_user_cache(cls, user_id):
        """
        Invalidate all cached permissions for a user.
        
        Args:
            user_id (int): User ID
            
        Returns:
            int: Number of cache entries deleted
        """
        count = cls.query.filter(cls.user_id == user_id).delete()
        db.session.commit()
        return count
    
    @classmethod
    def invalidate_resource_cache(cls, resource_type, resource_id):
        """
        Invalidate all cached permissions for a specific resource.
        
        Args:
            resource_type (str): Resource type
            resource_id (int): Resource ID
            
        Returns:
            int: Number of cache entries deleted
        """
        count = cls.query.filter(
            cls.resource_type == resource_type,
            cls.resource_id == resource_id
        ).delete()
        db.session.commit()
        return count
    
    @classmethod
    def invalidate_org_cache(cls, org_id):
        """
        Invalidate all cached permissions for an organization.
        
        Args:
            org_id (int): Organization ID
            
        Returns:
            int: Number of cache entries deleted
        """
        count = cls.query.filter(cls.org_id == org_id).delete()
        db.session.commit()
        return count
    
    @classmethod
    def cleanup_expired(cls):
        """
        Remove all expired cache entries.
        
        Returns:
            int: Number of cache entries deleted
        """
        count = cls.query.filter(
            cls.expires_at.isnot(None),
            cls.expires_at < datetime.utcnow()
        ).delete()
        db.session.commit()
        return count
    
    @classmethod
    def get_user_cached_permissions(cls, user_id, org_id):
        """
        Get all cached permissions for a user in an organization.
        
        Args:
            user_id (int): User ID
            org_id (int): Organization ID
            
        Returns:
            list: List of permission strings
        """
        cache_entries = cls.query.filter(
            cls.user_id == user_id,
            cls.org_id == org_id
        ).all()
        
        # Filter out expired entries
        valid_permissions = []
        for entry in cache_entries:
            if not entry.is_expired():
                valid_permissions.append(entry.permission)
            else:
                # Delete expired entry
                db.session.delete(entry)
        
        db.session.commit()
        return valid_permissions
